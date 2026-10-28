"""fal.ai, l'agrégateur de modèles (REPRISE §2), par son API de file d'attente (httpx).

Protocole vérifié le 29/10/2026 (https://fal.ai/docs/model-apis/model-endpoints/queue et
https://fal.ai/docs/documentation/model-apis/errors.md) :

- soumission : POST https://queue.fal.run/{endpoint}, corps = les entrées du modèle (JSON)
               → {request_id, response_url, status_url, cancel_url, queue_position}
- statut     : GET  https://queue.fal.run/{owner}/{app}/requests/{id}/status
               → {status: IN_QUEUE | IN_PROGRESS | COMPLETED, queue_position, error, error_type}
- résultat   : GET  https://queue.fal.run/{owner}/{app}/requests/{id} → la sortie du modèle
               ({"video": {"url", "content_type", "file_size"}} ou {"images": [{"url"}]}) ; erreur de modèle :
               422 {"detail": [{loc, msg, type}]} (filtre de contenu, paramètre refusé), 500 / 504 si passagère
- annulation : PUT  https://queue.fal.run/{owner}/{app}/requests/{id}/cancel
               → 200 OK | 202 CANCELLATION_REQUESTED | 400 ALREADY_COMPLETED | 404 NOT_FOUND

Statut, résultat et annulation n'utilisent que « owner/app », pas le chemin complet du modèle (sinon 405).
En-tête : `Authorization: Key <clé>`. La clé vient de la variable FAL_KEY ou du trousseau macOS
(service « loopcast-fal ») ; jamais de git ni de settings.yaml. Une image de départ part en data URI
(JPEG), ce que fal.ai accepte pour toute entrée fichier.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import httpx

from loopcast import llm
from loopcast.providers.base import ProviderAuthError, ProviderError, check_image, check_video, status

QUEUE_URL = "https://queue.fal.run"
KEYCHAIN_SERVICE = "loopcast-fal"

# Types d'erreur pour lesquels relancer le même modèle a une chance de marcher (doc fal.ai).
RETRYABLE_TYPES = {
    "internal_server_error", "generation_timeout", "downstream_service_error", "downstream_service_unavailable",
    "request_timeout", "startup_timeout", "runner_scheduling_failure", "runner_connection_timeout",
    "runner_disconnected", "runner_connection_refused", "runner_connection_error",
    "runner_incomplete_response", "runner_server_error", "internal_error",
}
ERROR_LABELS = {
    "content_policy_violation": "refusé par le filtre de contenu",
    "no_media_generated": "aucun fichier produit",
    "generation_timeout": "génération trop longue",
    "downstream_service_unavailable": "modèle partenaire indisponible",
    "downstream_service_error": "erreur du modèle partenaire",
    "internal_server_error": "erreur interne de fal.ai",
    "image_too_small": "image de départ trop petite",
    "image_too_large": "image de départ trop grande",
    "image_load_error": "image de départ illisible",
    "file_download_error": "fichier d'entrée inaccessible",
    "feature_not_supported": "combinaison de paramètres non prise en charge",
    "client_cancelled": "annulé",
}


class FalUnavailable(RuntimeError):
    """fal.ai ne répond pas (réseau, 429, 5xx sans détail) : la file de tâches réessaiera plus tard."""


def find_key(settings: dict | None = None) -> tuple[str | None, str]:
    """(clé, d'où elle vient) : la variable FAL_KEY, sinon le trousseau macOS."""
    key = (os.environ.get("FAL_KEY") or "").strip()
    if key:
        return key, "variable FAL_KEY"
    fal_cfg = ((settings or {}).get("providers") or {}).get("fal") or {}
    service = fal_cfg.get("keychain_service") or KEYCHAIN_SERVICE
    key = llm.keychain_secret(service)
    if key:
        return key, f"trousseau macOS (« {service} »)"
    return None, ""


def image_data_uri(path: Path, max_side: int = 1920) -> str:
    """L'image de départ en JPEG base64 (≤ 1920 px de côté : légère, et ≥ 720 p pour Veo)."""
    from PIL import Image

    if not path.is_file():
        raise ProviderError(f"image de départ introuvable : {path}")
    with Image.open(path) as img:
        rgb = img.convert("RGB")
    if max(rgb.size) > max_side:
        rgb.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _error_from(r: httpx.Response, what: str) -> ProviderError:
    """Erreur de modèle structurée ({"detail": [{loc, msg, type}]} ou {"detail", "error_type"})."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    detail = body.get("detail")
    etype = body.get("error_type") or r.headers.get("x-fal-error-type")
    msg = ""
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        etype = etype or first.get("type")
        loc = ".".join(str(x) for x in first.get("loc") or [] if x != "body")
        msg = f"{loc} : {first.get('msg', '')}" if loc else str(first.get("msg", ""))
    elif isinstance(detail, str):
        msg = detail
    label = ERROR_LABELS.get(etype, etype or f"HTTP {r.status_code}")
    retryable = etype in RETRYABLE_TYPES if etype else r.status_code >= 500
    return ProviderError(f"fal.ai ({what}) : {label}" + (f" — {msg[:300]}" if msg else ""),
                         retryable=retryable, code=etype or str(r.status_code))


class FalClient:
    """Les quatre appels de la file d'attente, plus le téléchargement du fichier produit."""

    def __init__(self, key: str, *, http: httpx.Client | None = None, base_url: str = QUEUE_URL,
                 timeout_s: float = 30.0):
        if not key:
            raise ProviderAuthError("clé fal.ai absente (FAL_KEY ou trousseau « loopcast-fal »)")
        self.base = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._auth = {"Authorization": f"Key {key}"}

    @staticmethod
    def app_of(endpoint: str) -> str:
        parts = endpoint.strip("/").split("/")
        if len(parts) < 2:
            raise ProviderError(f"endpoint fal.ai invalide : {endpoint}")
        return "/".join(parts[:2])

    def _request_url(self, endpoint: str, request_id: str) -> str:
        return f"{self.base}/{self.app_of(endpoint)}/requests/{request_id}"

    def _call(self, method: str, url: str, what: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, headers=self._auth, **kw)
        except httpx.HTTPError as e:
            raise FalUnavailable(f"fal.ai injoignable ({what}) : {e}") from e
        if r.status_code in (401, 403):
            raise ProviderAuthError(f"clé fal.ai refusée ({r.status_code}) : vérifier FAL_KEY ou le trousseau "
                                    f"macOS « {KEYCHAIN_SERVICE} »")
        if r.status_code < 400:
            return r
        if r.status_code == 429:
            raise FalUnavailable(f"fal.ai limite le débit ({what}, 429)")
        err = _error_from(r, what)
        if r.status_code >= 500 and err.code == str(r.status_code):      # panne sans détail exploitable
            raise FalUnavailable(f"fal.ai en erreur ({what}, {r.status_code})")
        raise err

    @staticmethod
    def _json(r: httpx.Response, what: str) -> dict:
        try:
            data = r.json()
        except ValueError as e:
            raise FalUnavailable(f"réponse illisible de fal.ai ({what})") from e
        if not isinstance(data, dict):
            raise FalUnavailable(f"réponse inattendue de fal.ai ({what})")
        return data

    def submit(self, endpoint: str, inputs: dict) -> dict:
        data = self._json(self._call("POST", f"{self.base}/{endpoint.strip('/')}", "soumission", json=inputs),
                          "soumission")
        if not data.get("request_id"):
            raise FalUnavailable("fal.ai n'a pas renvoyé de request_id")
        return data

    def status(self, endpoint: str, request_id: str) -> dict:
        return self._json(self._call("GET", self._request_url(endpoint, request_id) + "/status", "statut"),
                          "statut")

    def result(self, endpoint: str, request_id: str) -> dict:
        return self._json(self._call("GET", self._request_url(endpoint, request_id), "résultat"), "résultat")

    def cancel(self, endpoint: str, request_id: str) -> str:
        """OK, CANCELLATION_REQUESTED, ALREADY_COMPLETED ou NOT_FOUND (aucun n'est une erreur pour nous)."""
        r = self._call_lenient("PUT", self._request_url(endpoint, request_id) + "/cancel")
        try:
            return str((r.json() or {}).get("status") or r.status_code)
        except ValueError:
            return str(r.status_code)

    def _call_lenient(self, method: str, url: str) -> httpx.Response:
        try:
            r = self.http.request(method, url, headers=self._auth)
        except httpx.HTTPError as e:
            raise FalUnavailable(f"fal.ai injoignable (annulation) : {e}") from e
        if r.status_code in (401, 403):
            raise ProviderAuthError(f"clé fal.ai refusée ({r.status_code})")
        return r

    def fetch(self, url: str, dest: Path, *, max_bytes: int) -> str:
        """Télécharge le fichier produit (CDN public de fal, sans la clé) ; renvoie son Content-Type."""
        try:
            with self.http.stream("GET", url) as r:
                if r.status_code >= 500 or r.status_code == 429:
                    raise FalUnavailable(f"téléchargement impossible pour l'instant ({r.status_code})")
                if r.status_code >= 400:
                    raise ProviderError(f"fichier produit inaccessible ({r.status_code}) : il a peut-être expiré",
                                        retryable=True, code="download_error")
                declared = int(r.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise ProviderError(f"fichier trop lourd ({declared / 1e6:.0f} Mo)", code="bad_output")
                received = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        received += len(chunk)
                        if received > max_bytes:
                            raise ProviderError(f"fichier trop lourd (> {max_bytes / 1e6:.0f} Mo)", code="bad_output")
                        f.write(chunk)
                content_type = r.headers.get("content-type", "")
        except httpx.HTTPError as e:
            raise FalUnavailable(f"téléchargement interrompu : {e}") from e
        if declared and received != declared:
            raise FalUnavailable(f"téléchargement incomplet ({received} / {declared} octets)")
        return content_type


def _split(handle: str) -> tuple[str, str]:
    endpoint, sep, request_id = handle.rpartition("#")
    if not sep or not endpoint or not request_id:
        raise ProviderError(f"identifiant fal.ai invalide : {handle[:80]}")
    return endpoint, request_id


class _FalProvider:
    """Un modèle du catalogue servi par fal.ai. L'identifiant renvoyé : « {endpoint}#{request_id} »."""
    name = "fal"
    kind = ""
    default_suffix = ""
    suffixes: tuple[str, ...] = ()

    def __init__(self, model, client: FalClient, *, max_bytes: int = 300_000_000):
        self.model = model
        self.client = client
        self.max_bytes = max_bytes
        self._results: dict[str, dict] = {}     # réponse du résultat, gardée entre poll() et download()

    def estimate(self, req) -> float:
        return self.model.price(req)

    def submit(self, req) -> str:
        image_url = image_data_uri(Path(req.image_path)) if req.image_path else None
        endpoint = self._endpoint(req)
        data = self.client.submit(endpoint, self.model.inputs(req, image_url))
        return f"{endpoint}#{data['request_id']}"

    def poll(self, handle: str) -> dict:
        endpoint, request_id = _split(handle)
        try:
            st = self.client.status(endpoint, request_id)
            state = st.get("status")
            if state == "IN_QUEUE":
                return status("queued", queue_position=st.get("queue_position"))
            if state != "COMPLETED":
                return status("running")
            if st.get("error"):
                etype = st.get("error_type")
                label = ERROR_LABELS.get(etype, etype or "erreur")
                return status("failed", error=f"fal.ai : {label} — {str(st['error'])[:300]}",
                              retryable=etype in RETRYABLE_TYPES, code=etype)
            data = self.client.result(endpoint, request_id)
        except ProviderAuthError:
            raise
        except ProviderError as e:
            return status("failed", error=str(e), retryable=e.retryable, code=e.code)
        if not self._media_url(data):
            return status("failed", error="fal.ai n'a renvoyé aucun fichier", retryable=False,
                          code="no_media_generated")
        self._results[handle] = data
        return status("done", progress=1.0)

    def download(self, handle: str, dest_dir: Path, *, name: str | None = None, expect: dict | None = None) -> Path:
        endpoint, request_id = _split(handle)
        data = self._results.pop(handle, None) or self.client.result(endpoint, request_id)
        url = self._media_url(data)
        if not url:
            raise ProviderError("aucun fichier dans la réponse de fal.ai", code="no_media_generated")
        suffix = self._suffix(url)
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name or request_id}{suffix}"
        tmp = dest_dir / f".{dest.stem}.part{suffix}"
        try:
            content_type = self.client.fetch(url, tmp, max_bytes=self.max_bytes)
            if content_type.startswith(("text/", "application/json")):
                raise ProviderError(f"type reçu « {content_type} » au lieu d'un fichier {self.kind}", code="bad_output")
            self._check(tmp, expect or {})
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest

    def cancel(self, handle: str) -> None:
        endpoint, request_id = _split(handle)
        self.client.cancel(endpoint, request_id)

    def cost(self, handle: str) -> float | None:
        return None          # fal.ai ne renvoie pas le coût d'une requête : on inscrit l'estimation

    def _suffix(self, url: str) -> str:
        ext = Path(url.split("?")[0]).suffix.lower()
        return ext if ext in self.suffixes else self.default_suffix

    def _endpoint(self, req) -> str:
        raise NotImplementedError

    def _media_url(self, data: dict) -> str | None:
        raise NotImplementedError

    def _check(self, path: Path, expect: dict) -> None:
        raise NotImplementedError


class FalVideoProvider(_FalProvider):
    kind = "video"
    default_suffix = ".mp4"
    suffixes = (".mp4", ".mov")

    def _endpoint(self, req) -> str:
        endpoint = self.model.endpoint_i2v if req.image_path else self.model.endpoint
        if not endpoint:
            raise ProviderError(f"{self.model.id} : pas d'endpoint pour cette requête")
        return endpoint

    def _media_url(self, data: dict) -> str | None:
        video = data.get("video")
        return video.get("url") if isinstance(video, dict) else None

    def _check(self, path: Path, expect: dict) -> None:
        check_video(path, duration_s=expect.get("duration_s"), aspect=expect.get("aspect"), max_bytes=self.max_bytes)


class FalImageProvider(_FalProvider):
    kind = "image"
    default_suffix = ".png"
    suffixes = (".png", ".jpg", ".jpeg", ".webp")

    def _endpoint(self, req) -> str:
        endpoint = self.model.endpoint_edit if req.image_path else self.model.endpoint
        if not endpoint:
            raise ProviderError(f"{self.model.id} : pas d'endpoint pour cette requête")
        return endpoint

    def _media_url(self, data: dict) -> str | None:
        images = data.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict):
            return images[0].get("url")
        image = data.get("image")
        return image.get("url") if isinstance(image, dict) else None

    def _check(self, path: Path, expect: dict) -> None:
        check_image(path, aspect=expect.get("aspect"))
