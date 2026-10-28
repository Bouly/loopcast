"""Publication en pilotant l'app TikTok ou Instagram sur l'iPhone, via la ferme (Appium + WebDriverAgent).

!!! BROUILLON NON VÉRIFIÉ !!!
Écrit le 29/10/2026 sans iPhone branché : aucune étape, aucun libellé, aucune commande pymobiledevice3
de ce fichier n'a été essayé sur un vrai téléphone (seulement contre un faux Appium dans les tests).
Désactivé par défaut : canal `ios_app` (ou `ios_appium`) ET `diffusion.ios_app.enabled: true`. C'est le plan B
de REPRISE §5.6 ; à n'activer qu'après un essai complet, en mode assist, sur un iPhone de la ferme.

1. Mettre la vidéo dans la photothèque de l'iPhone depuis le Mac (recherche du 29/10/2026)
   - AFC (`pymobiledevice3 afc push` vers /DCIM) : le fichier arrive sur le disque mais Photos ne l'indexe
     pas (sa base ne le connaît pas) ; forcer la reconstruction de la base détruit albums et retouches. Exclu.
   - Appium `mobile: pushFile` sur un vrai iPhone : seulement dans le conteneur d'une app qui a
     `UIFileSharingEnabled` (dossier Documents, visible dans Fichiers › Sur mon iPhone) ; `simctl addmedia`
     n'existe que sur simulateur. pymobiledevice3 n'a pas de commande d'import dans Photos, mais
     `apps push <bundle> <local> <distant> --documents` (service house_arrest) dépose un fichier dans les
     Documents d'une app avec partage de fichiers, par le câble USB.
   - Raccourci iOS lancé par URL (doc Apple « Exécuter un raccourci depuis une URL ») :
     `shortcuts://run-shortcut?name=…&input=text&text=…`, ouvert depuis le Mac par Appium
     `mobile: deepLink` (driver XCUITest ≥ 4.17, iOS ≥ 16.4). Le raccourci sait « Obtenir le fichier »
     et « Enregistrer dans l'album photo ».
   → Retenu (ce fichier) : house_arrest vers les Documents d'une app à partage de fichiers (Keynote par
     défaut, app Apple gratuite) + raccourci « Loopcast Import » qui enregistre le fichier dans l'album
     « Loopcast », le supprime et dépose un reçu `<nom>.ok` que le Mac relit. Tout passe par l'USB.
   - Variante de REPRISE §5.6 (le raccourci télécharge la vidéo sur l'API locale via Tailscale) : écartée
     par défaut, car il faut soit un VPN actif sur des téléphones qui portent des comptes TikTok (signal
     possible pour l'anti-fraude), soit exposer l'API sur le Wi-Fi.
   - Le plus solide à terme : une petite app iOS maison (signée avec le compte Apple Developer, comme
     WebDriverAgent), avec partage de fichiers et PHPhotoLibrary, ouverte par URL, qui importe son dossier
     Documents et écrit un reçu (localIdentifier). Pas écrite.
   - Écartés aussi : synchro Finder (manuelle, incompatible avec Photos iCloud), AirDrop (acceptation à
     l'écran), albums partagés iCloud (720p, un identifiant Apple par téléphone).

   Préparation, une fois par iPhone (à la main) :
   a. Installer Keynote (ou régler `diffusion.ios_app.inbox_bundle_id` sur une autre app à partage de fichiers).
   b. Créer l'album « Loopcast » dans Photos.
   c. Créer le raccourci « Loopcast Import » : Entrée = texte (le nom du fichier) ; « Obtenir le fichier »
      dans Sur mon iPhone › Keynote, chemin = Entrée du raccourci, erreur si introuvable ; « Enregistrer
      dans l'album photo » Loopcast ; « Supprimer les fichiers » sans confirmation ; texte « ok » ;
      « Enregistrer le fichier » dans Sur mon iPhone › Keynote sous le nom « Entrée.ok », sans demander, en
      remplaçant.
   d. Lancer le raccourci une fois à la main et autoriser l'accès à Photos (« Toujours autoriser ») ;
      dans TikTok et Instagram, autoriser l'accès complet à Photos.

2. Le parcours dans l'app : étapes déclaratives (FLOWS), chaque bouton cherché par ses libellés FR et EN
   (attribut `label` ou `name` de l'arbre XCUITest). Les libellés sont des hypothèses à confirmer en lisant
   l'arbre (`PhoneController.source`) sur un vrai téléphone : chaque mise à jour de TikTok peut en casser.

3. Mode assist (défaut, `post_mode`) : tout est prêt dans l'app, on s'arrête AVANT « Publier » → le post
   passe « à finir », une personne vérifie et appuie. Mode auto : on appuie, sauf pour un contenu à label
   IA (l'étiquette se pose à la main tant que ce parcours n'est pas vérifié).

Aucune action d'engagement : ce parcours ouvre l'app, importe NOTRE vidéo et prépare NOTRE post, rien d'autre.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

import httpx

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, PublishResult
from loopcast.diffusion.settings import IosAppSettings

VERIFIED = False          # passera à True quand un parcours complet aura été fait sur un vrai iPhone

BUNDLES = {"tiktok": "com.zhiliaoapp.musically", "instagram": "com.burbn.instagram"}


class IosFlowError(RuntimeError):
    """Une étape du parcours a échoué (bouton introuvable, import non confirmé…)."""


@dataclass(frozen=True)
class Step:
    action: str                       # launch | tap | tap_first_media | caption | publish
    labels: tuple[str, ...] = ()      # libellés acceptés, FR puis EN
    kind: str | None = None           # type XCUITest (XCUIElementTypeButton…), facultatif
    optional: bool = False            # absent = on passe (fenêtre « Pas maintenant » qui n'apparaît pas…)
    timeout_s: float = 12.0
    note: str = ""


# Hypothèses de parcours (NON VÉRIFIÉES), interface de fin 2026.
FLOWS: dict[str, list[Step]] = {
    "tiktok": [
        Step("launch"),
        Step("tap", ("Pas maintenant", "Plus tard", "Not now", "Later"), optional=True, timeout_s=3,
             note="fenêtre d'accueil éventuelle"),
        Step("tap", ("Créer", "Publier une vidéo", "Create", "Post a video"), "XCUIElementTypeButton",
             note="bouton + de la barre du bas"),
        Step("tap", ("Importer", "Télécharger", "Upload"), note="galerie, en bas à droite de la caméra"),
        Step("tap", ("Vidéos", "Videos"), optional=True, timeout_s=4, note="onglet des vidéos de la galerie"),
        Step("tap_first_media", note="la plus récente = celle qu'on vient d'importer"),
        Step("tap", ("Suivant", "Next"), "XCUIElementTypeButton"),
        Step("tap", ("Suivant", "Next"), "XCUIElementTypeButton", note="écran d'édition"),
        Step("caption", ("Ajouter une description", "Décrivez votre publication", "Add description",
                         "Describe your post"), note="champ de description"),
        Step("publish", ("Publier", "Post"), "XCUIElementTypeButton"),
    ],
    "instagram": [
        Step("launch"),
        Step("tap", ("Pas maintenant", "Not now"), optional=True, timeout_s=3),
        Step("tap", ("Créer", "Nouvelle publication", "Create", "New post"), "XCUIElementTypeButton",
             note="bouton + de l'accueil"),
        Step("tap", ("REEL", "Reel"), note="onglet Reel en bas de l'écran de création"),
        Step("tap_first_media", note="la plus récente = celle qu'on vient d'importer"),
        Step("tap", ("Suivant", "Ajouter", "Next", "Add"), "XCUIElementTypeButton"),
        Step("tap", ("Suivant", "Next"), "XCUIElementTypeButton", note="écran d'édition"),
        Step("caption", ("Écrivez une légende", "Ajoutez une légende", "Write a caption", "Add a caption")),
        Step("publish", ("Partager", "Share"), "XCUIElementTypeButton"),
    ],
}

# Réglages WebDriverAgent le temps du parcours : lire l'arbre de l'app (la ferme vise l'écran d'accueil
# pour que le pilotage à distance reste fluide ; on remet ses réglages à la fin).
FLOW_WDA_SETTINGS = {"snapshotMaxDepth": 60, "customSnapshotTimeout": 15}


def shortcut_url(name: str, text: str) -> str:
    """URL documentée par Apple ; les espaces en %20 comme dans ses exemples."""
    return "shortcuts://run-shortcut?" + urlencode({"name": name, "input": "text", "text": text}, quote_via=quote)


def predicate(labels: tuple[str, ...], kind: str | None = None) -> str:
    """Prédicat XCUITest : un élément visible dont le label ou le nom est l'un des libellés."""
    values = ", ".join("'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'" for v in labels)
    pred = f"(label IN {{{values}}} OR name IN {{{values}}}) AND visible == 1"
    return f"type == '{kind}' AND {pred}" if kind else pred


# --- WebDriver : ce que PhoneController (farm, lecture seule ici) n'expose pas encore -------------------

class Wda:
    """Recherche d'éléments, réglages et liens profonds sur la session Appium de la ferme.

    Passe par `controller.http` et `controller.session_id` (publics). Quand farm/control.py exposera
    find/click/settings/deep_link, cette classe se réduira à des appels de PhoneController.
    """

    W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"

    def __init__(self, controller, udid: str, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.controller = controller
        self.udid = udid
        self.sleep = sleep
        self.monotonic = monotonic

    def open(self) -> str:
        return self.controller.start(self.udid)

    def _sid(self) -> str:
        sid = self.controller.session_id(self.udid)
        if not sid:
            raise IosFlowError("pas de session Appium ouverte sur cet iPhone")
        return sid

    def _request(self, method: str, path: str, body: dict | None = None):
        try:
            resp = self.controller.http.request(method, f"/session/{self._sid()}{path}", json=body)
        except httpx.HTTPError as e:
            raise IosFlowError(f"Appium injoignable : {e}") from e
        try:
            data = resp.json()
        except ValueError:
            raise IosFlowError(f"Appium {resp.status_code} : {resp.text[:200]}") from None
        value = data.get("value") if isinstance(data, dict) else None
        if resp.status_code >= 400:
            error = value.get("error") if isinstance(value, dict) else None
            message = value.get("message") if isinstance(value, dict) else value
            if error == "no such element":
                raise _NotFound(str(message))
            raise IosFlowError(f"Appium {resp.status_code} : {str(message)[:300]}")
        return value

    def settings(self, values: dict) -> None:
        self._request("POST", "/appium/settings", {"settings": values})

    def deep_link(self, url: str, bundle_id: str | None = None) -> None:
        args = {"url": url}
        if bundle_id:
            args["bundleId"] = bundle_id
        self._request("POST", "/execute/sync", {"script": "mobile: deepLink", "args": [args]})

    def launch(self, bundle_id: str) -> None:
        self._request("POST", "/execute/sync", {"script": "mobile: launchApp", "args": [{"bundleId": bundle_id}]})

    def find(self, pred: str, timeout_s: float) -> str | None:
        deadline = self.monotonic() + timeout_s
        while True:
            try:
                el = self._request("POST", "/element", {"using": "-ios predicate string", "value": pred})
                if isinstance(el, dict) and el:
                    return el.get(self.W3C_ELEMENT) or next(iter(el.values()))
                raise IosFlowError(f"réponse inattendue d'Appium pour un élément : {el}")
            except _NotFound:
                if self.monotonic() >= deadline:
                    return None
                self.sleep(1.0)

    def click(self, element_id: str) -> None:
        self._request("POST", f"/element/{element_id}/click", {})

    def type_into(self, element_id: str, text: str) -> None:
        self._request("POST", f"/element/{element_id}/value", {"text": text})

    def screenshot(self) -> bytes | None:
        try:
            return self.controller.screenshot(self.udid)
        except Exception:  # noqa: BLE001 : un diagnostic ne doit pas masquer l'erreur d'origine
            return None


class _NotFound(Exception):
    pass


# --- Import dans Photos ---------------------------------------------------------------------------------

class ShortcutImporter:
    """Vidéo → Photos par le câble : house_arrest (pymobiledevice3) puis raccourci « Loopcast Import »."""

    def __init__(self, settings: IosAppSettings, exe: str = "pymobiledevice3",
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.exe = exe
        self.run = run
        self.sleep = sleep
        self.monotonic = monotonic

    def _cli(self, *args: str, check: bool = True) -> bool:
        try:
            proc = self.run([self.exe, *args], capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise IosFlowError(f"pymobiledevice3 {' '.join(args[:2])} : {e}") from e
        if proc.returncode != 0 and check:
            raise IosFlowError(f"pymobiledevice3 {' '.join(args[:2])} : {(proc.stderr or proc.stdout).strip()[-300:]}")
        return proc.returncode == 0

    def import_media(self, udid: str, files: list[Path], wda: Wda, tag: str) -> list[str]:
        bundle = self.settings.inbox_bundle_id
        names = []
        for i, path in enumerate(files):
            name = f"loopcast-{tag}-{i}{path.suffix.lower()}"
            # À vérifier : en mode --documents, le chemin distant est-il « /Documents/x » ou « /x » ?
            self._cli("apps", "push", bundle, str(path), f"/Documents/{name}", "--documents", "--udid", udid)
            wda.deep_link(shortcut_url(self.settings.shortcut_name, name))
            self._wait_receipt(udid, bundle, name)
            names.append(name)
        return names

    def _wait_receipt(self, udid: str, bundle: str, name: str) -> None:
        deadline = self.monotonic() + self.settings.import_timeout_s
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "receipt")
            while True:
                if self._cli("apps", "pull", bundle, f"/Documents/{name}.ok", target, "--documents", "--udid", udid,
                             check=False):
                    self._cli("apps", "rm", bundle, f"/Documents/{name}.ok", "--documents", "--udid", udid, check=False)
                    return
                if self.monotonic() >= deadline:
                    raise IosFlowError(f"import dans Photos non confirmé après {self.settings.import_timeout_s} s "
                                       f"(raccourci « {self.settings.shortcut_name} » absent ou en erreur ?)")
                self.sleep(3.0)


# --- Le publisher ---------------------------------------------------------------------------------------

class IosAppPublisher:
    name = "ios_app"

    def __init__(self, config, settings: IosAppSettings, *, controller_factory: Callable[[], object] | None = None,
                 importer: ShortcutImporter | None = None, flows: dict[str, list[Step]] | None = None,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.config = config
        self.settings = settings
        self.controller_factory = controller_factory or self._default_controller
        self.importer = importer or ShortcutImporter(settings, exe=config.farm.pymobiledevice3)
        self.flows = flows or FLOWS
        self.sleep = sleep
        self.monotonic = monotonic

    @property
    def requires_human(self) -> bool:
        return self.settings.mode != "auto"

    def _default_controller(self):
        """Un PhoneController (et sa connexion SQLite) pour toute la vie du publisher."""
        if getattr(self, "_controller", None) is None:
            from loopcast import db
            from loopcast.farm.control import PhoneController

            self._controller = PhoneController(self.config, db.connect(self.config.db_path, run_migrations=False))
        return self._controller

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult:
        phone = self.config.phone_by_id(account.device)
        if phone is None or not phone.udid:
            return PublishResult.failed(f"iPhone {account.device} : UDID à renseigner dans devices.yaml",
                                        retryable=False)
        flow = self.flows.get(account.platform)
        if not flow:
            return PublishResult.failed(f"pas de parcours iPhone pour {account.platform}", retryable=False)
        missing = [str(p) for p in media if not p.exists()]
        if not media or missing:
            return PublishResult.failed(f"fichier introuvable : {', '.join(missing) or 'aucun'}", retryable=False)

        from loopcast.farm.control import WDA_SETTINGS, ControlError

        wda = Wda(self.controller_factory(), phone.udid, self.sleep, self.monotonic)
        done: list[str] = []
        try:
            wda.open()
            self.importer.import_media(phone.udid, media, wda, tag=content.id)
            done.append(f"{len(media)} fichier(s) dans Photos (album {self.settings.album})")
            if content.kind != "video":
                return PublishResult.needs_human(
                    f"Brouillon iPhone (non vérifié) : carrousel importé dans Photos sur {account.device} ; "
                    "sélection multiple et publication à faire à la main.")
            wda.settings({**FLOW_WDA_SETTINGS, "defaultActiveApplication": BUNDLES[account.platform]})
            for step in flow:
                if step.action == "publish":
                    return self._finish(wda, step, account, content, done)
                self._run(wda, step, account, content)
                done.append(step.note or step.action)
            raise IosFlowError("parcours sans étape « publish »")
        except (IosFlowError, ControlError) as e:
            where = self._save_failure(content.id, account.id, wda.screenshot())
            shot = f" ; capture : {where}" if where else ""
            return PublishResult.failed(f"iPhone {account.device} : {e} (après : {', '.join(done) or 'rien'}){shot}")
        finally:
            try:
                wda.settings(WDA_SETTINGS)
            except (IosFlowError, ControlError):
                pass

    def _run(self, wda: Wda, step: Step, account: Account, content: ContentItem) -> None:
        if step.action == "launch":
            wda.launch(BUNDLES[account.platform])
            return
        if step.action == "tap_first_media":
            el = wda.find("(type == 'XCUIElementTypeCell' OR type == 'XCUIElementTypeImage') AND visible == 1",
                          step.timeout_s)
            if el is None:
                raise IosFlowError("galerie : aucune vidéo visible")
            wda.click(el)
            return
        el = wda.find(predicate(step.labels, step.kind), step.timeout_s)
        if el is None:
            if step.optional:
                return
            note = f" ({step.note})" if step.note else ""
            raise IosFlowError(f"introuvable : « {' / '.join(step.labels)} »{note}")
        wda.click(el)
        if step.action == "caption":
            wda.type_into(el, content.post_text())

    def _finish(self, wda: Wda, step: Step, account: Account, content: ContentItem, done: list[str]) -> PublishResult:
        el = wda.find(predicate(step.labels, step.kind), step.timeout_s)
        if el is None:
            raise IosFlowError(f"bouton « {' / '.join(step.labels)} » introuvable à la fin du parcours")
        label = step.labels[0]
        if self.settings.mode != "auto" or content.ai_label:
            why = " Activer l'étiquette « contenu généré par IA » avant." if content.ai_label else ""
            return PublishResult.needs_human(
                f"Brouillon iPhone (non vérifié) : tout est prêt dans {account.platform} sur {account.device}, "
                f"vérifier puis appuyer sur « {label} », et cliquer « Publié » dans Loopcast.{why}")
        wda.click(el)
        deadline = self.monotonic() + 90
        while wda.find(predicate(step.labels, step.kind), 1) is not None:
            if self.monotonic() >= deadline:
                raise IosFlowError(f"« {label} » touché mais l'écran n'a pas changé en 90 s")
            self.sleep(2.0)
        return PublishResult.posted(log=f"publié depuis l'app sur {account.device} (brouillon non vérifié : "
                                        "contrôler dans l'app ; vues à saisir à la main)")

    def _save_failure(self, content_id: str, account_id: str, png: bytes | None) -> str | None:
        if not png:
            return None
        folder = Path(self.config.data_dir) / "ios_app"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{account_id.replace(':', '-')}-{content_id}-{int(time.time())}.png"
            path.write_bytes(png)
            return str(path)
        except OSError:
            return None

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]:
        return {}        # pas de lecture des vues dans l'app : saisie manuelle, ou API officielle plus tard
