"""fal.ai par sa file d'attente, simulée avec httpx.MockTransport : aucun appel réseau, aucune clé réelle."""

import base64
import io
import json

import httpx
import pytest
from PIL import Image
from providers_testkit import TEST_SCALE, job_row, run_until_settled, video_model

from loopcast import jobs
from loopcast.providers import catalog, fal
from loopcast.providers import tasks  # noqa: F401  (enregistre video.generate)
from loopcast.providers.base import ImageRequest, ProviderAuthError, ProviderError, VideoRequest, probe_video
from loopcast.providers.fake import FakeVideoProvider
from loopcast.providers.router import Router

CDN = "https://v3b.fal.media/files/abc/out.mp4"


@pytest.fixture(scope="module")
def mp4(tmp_path_factory) -> bytes:
    """Un vrai mp4 9:16 de 5 s, servi par le faux CDN."""
    out = tmp_path_factory.mktemp("cdn")
    fake = FakeVideoProvider(video_model("cdn"), scale=TEST_SCALE)
    return fake.download(fake.submit(VideoRequest(prompt="cdn", duration_s=5)), out).read_bytes()


class FakeFalServer:
    """queue.fal.run et le CDN fal.media, simulés. `responses[étape]` : une fonction qui remplace la réponse."""

    def __init__(self, media: bytes, media_type: str = "video/mp4",
                 statuses=("IN_QUEUE", "IN_PROGRESS", "COMPLETED")):
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses)
        self.media, self.media_type = media, media_type
        self.result = {"video": {"url": CDN, "content_type": "video/mp4", "file_size": len(media)}}
        self.responses = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host.endswith("fal.media"):
            return httpx.Response(200, content=self.media, headers={"content-type": self.media_type})
        path = request.url.path
        step = ("submit" if request.method == "POST" else "cancel" if path.endswith("/cancel")
                else "status" if path.endswith("/status") else "result")
        if step in self.responses:
            return self.responses[step]()
        if step == "submit":
            app = "/".join(path.strip("/").split("/")[:2])
            base = f"https://queue.fal.run/{app}/requests/req-1"
            return httpx.Response(200, json={"request_id": "req-1", "response_url": base, "status_url": base + "/status",
                                             "cancel_url": base + "/cancel", "queue_position": 0})
        if step == "status":
            state = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json={"status": state, "request_id": "req-1",
                                             **({"queue_position": 3} if state == "IN_QUEUE" else {})})
        if step == "cancel":
            return httpx.Response(202, json={"status": "CANCELLATION_REQUESTED"})
        return httpx.Response(200, json=self.result)


def client(server) -> fal.FalClient:
    return fal.FalClient("test-key", http=httpx.Client(transport=httpx.MockTransport(server)))


def model(model_id: str):
    return catalog.find(catalog.video_models(), model_id)


def test_submit_poll_download(tmp_path, mp4):
    server = FakeFalServer(mp4)
    provider = fal.FalVideoProvider(model("kling3-std"), client(server))
    handle = provider.submit(VideoRequest(prompt="A runner at dawn", duration_s=5, negative_prompt="blur"))
    assert handle == "fal-ai/kling-video/v3/standard/text-to-video#req-1"
    sub = server.requests[0]
    assert sub.method == "POST" and str(sub.url) == "https://queue.fal.run/fal-ai/kling-video/v3/standard/text-to-video"
    assert sub.headers["authorization"] == "Key test-key"
    assert json.loads(sub.content) == {"prompt": "A runner at dawn", "duration": "5", "aspect_ratio": "9:16",
                                       "generate_audio": False, "negative_prompt": "blur"}
    first = provider.poll(handle)
    assert first["status"] == "queued" and first["queue_position"] == 3
    assert server.requests[1].url.path == "/fal-ai/kling-video/requests/req-1/status"   # owner/app seulement
    assert provider.poll(handle)["status"] == "running"
    assert provider.poll(handle)["status"] == "done"
    assert server.requests[-1].url.path == "/fal-ai/kling-video/requests/req-1"
    path = provider.download(handle, tmp_path, name="shot-00", expect={"duration_s": 5, "aspect": "9:16"})
    assert path.name == "shot-00.mp4" and probe_video(path).duration_s == pytest.approx(5.0, abs=0.05)
    cdn = server.requests[-1]
    assert cdn.url.host == "v3b.fal.media" and "authorization" not in cdn.headers   # la clé ne part pas au CDN
    assert provider.cost(handle) is None and provider.estimate(VideoRequest(prompt="x", duration_s=5)) == 0.42
    assert not list(tmp_path.glob(".*part*"))


def test_download_checks_the_file(tmp_path, mp4):
    server = FakeFalServer(mp4, statuses=("COMPLETED",))
    provider = fal.FalVideoProvider(model("kling3-std"), client(server))
    handle = provider.submit(VideoRequest(prompt="x", duration_s=10))
    with pytest.raises(ProviderError, match="durée 5.0 s au lieu de 10 s") as e:
        provider.download(handle, tmp_path, expect={"duration_s": 10, "aspect": "9:16"})
    assert e.value.code == "bad_output" and not e.value.retryable
    with pytest.raises(ProviderError, match="format 16:9"):
        provider.download(handle, tmp_path, expect={"aspect": "16:9"})
    server.media_type = "text/html"
    with pytest.raises(ProviderError, match="text/html"):
        provider.download(handle, tmp_path)
    assert not list(tmp_path.iterdir())                                 # rien de bancal ne reste sur le disque


def test_generation_errors(mp4):
    server = FakeFalServer(mp4, statuses=("COMPLETED",))
    provider = fal.FalVideoProvider(model("veo31-fast-1080p"), client(server))
    handle = provider.submit(VideoRequest(prompt="x", duration_s=4))
    server.responses["status"] = lambda: httpx.Response(200, json={
        "status": "COMPLETED", "error": "took too long", "error_type": "generation_timeout"})
    st = provider.poll(handle)
    assert st["status"] == "failed" and st["retryable"] and "trop longue" in st["error"]
    server.responses["status"] = lambda: httpx.Response(200, json={"status": "COMPLETED"})
    server.responses["result"] = lambda: httpx.Response(422, json={"detail": [
        {"loc": ["body", "prompt"], "msg": "flagged", "type": "content_policy_violation"}]})
    st = provider.poll(handle)
    assert st["status"] == "failed" and not st["retryable"] and "filtre de contenu" in st["error"]
    server.responses["status"] = lambda: httpx.Response(404, json={"status": "NOT_FOUND"})
    assert provider.poll(handle)["status"] == "failed"
    server.responses["submit"] = lambda: httpx.Response(422, json={"detail": [
        {"loc": ["body", "duration"], "msg": "Input should be '4s', '6s' or '8s'", "type": "one_of"}]})
    with pytest.raises(ProviderError, match="duration") as e:
        provider.submit(VideoRequest(prompt="x", duration_s=4))
    assert not e.value.retryable
    server.responses["submit"] = lambda: httpx.Response(401, json={"detail": "Unauthorized"})
    with pytest.raises(ProviderAuthError, match="FAL_KEY"):
        provider.submit(VideoRequest(prompt="x", duration_s=4))
    for code in (429, 503):
        server.responses["submit"] = lambda code=code: httpx.Response(code, text="busy")
        with pytest.raises(fal.FalUnavailable):
            provider.submit(VideoRequest(prompt="x", duration_s=4))

    def unreachable(request):
        raise httpx.ConnectError("no route to host")

    offline = fal.FalVideoProvider(model("veo31-fast-1080p"),
                                   fal.FalClient("k", http=httpx.Client(transport=httpx.MockTransport(unreachable))))
    with pytest.raises(fal.FalUnavailable, match="injoignable"):
        offline.poll(handle)


def test_image_to_video_and_cancel(tmp_path, mp4):
    start = tmp_path / "screen.png"
    Image.new("RGB", (1290, 2796), (200, 40, 90)).save(start)
    server = FakeFalServer(mp4)
    provider = fal.FalVideoProvider(model("h3-max-768p"), client(server))
    handle = provider.submit(VideoRequest(prompt="The app screen scrolls", duration_s=5, image_path=str(start)))
    assert handle == "minimax/h3-max/image-to-video#req-1"
    body = json.loads(server.requests[0].content)
    assert body["duration"] == 5.0 and body["resolution"] == "768P" and "aspect_ratio" not in body
    head, data = body["image_url"].split(",", 1)
    assert head == "data:image/jpeg;base64"
    with Image.open(io.BytesIO(base64.b64decode(data))) as img:
        assert max(img.size) == 1920                                   # réduite avant l'envoi
    provider.cancel(handle)
    cancel = server.requests[-1]
    assert cancel.method == "PUT" and cancel.url.path == "/minimax/h3-max/requests/req-1/cancel"


def test_image_provider(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (768, 1344), (30, 30, 60)).save(buf, "PNG")
    server = FakeFalServer(buf.getvalue(), media_type="image/png", statuses=("COMPLETED",))
    server.result = {"images": [{"url": "https://v3b.fal.media/files/abc/out.png", "content_type": "image/png"}],
                     "description": ""}
    image_model = catalog.find(catalog.image_models(), "nano-banana")
    provider = fal.FalImageProvider(image_model, client(server))
    handle = provider.submit(ImageRequest(prompt="Soft pastel background", seed=4))
    assert json.loads(server.requests[0].content) == {"prompt": "Soft pastel background", "aspect_ratio": "9:16",
                                                      "seed": 4, "num_images": 1}
    assert provider.poll(handle)["status"] == "done"
    path = provider.download(handle, tmp_path, name="image-00", expect={"aspect": "9:16"})
    assert path.name == "image-00.png"


def test_key_from_env_or_keychain(monkeypatch):
    monkeypatch.setenv("FAL_KEY", " k-env ")
    assert fal.find_key({}) == ("k-env", "variable FAL_KEY")
    monkeypatch.delenv("FAL_KEY")
    asked = []
    monkeypatch.setattr(fal.llm, "keychain_secret", lambda service: asked.append(service) or "k-mac")
    assert fal.find_key({}) == ("k-mac", "trousseau macOS (« loopcast-fal »)")
    monkeypatch.setattr(fal.llm, "keychain_secret", lambda service: None)
    assert fal.find_key({"providers": {"fal": {"keychain_service": "autre"}}}) == (None, "")
    assert asked == ["loopcast-fal"]


def test_video_generate_task_through_fal(conn, config, clock, mp4):
    """De bout en bout avec fal.ai simulé : fal ne donne pas le coût → l'estimation est inscrite, marquée."""
    server = FakeFalServer(mp4)
    kling = model("kling3-std")
    router = Router("video", [kling], {kling.id: fal.FalVideoProvider(kling, client(server))}, mode="fal", why="tests")
    job_id = jobs.enqueue(conn, "video.generate", {"content_id": "habitudo-fr-0007", "shot_index": 0,
                                                   "request": {"prompt": "A runner at dawn", "duration_s": 5}},
                          app_id="habitudo", clock=clock)
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "done"
    result = json.loads(job_row(conn, job_id)["result"])
    assert result["provider"] == "fal" and result["model"] == "kling3-std"
    assert result["cost_usd"] == pytest.approx(0.42) and result["estimated"] is True
    assert result["path"] == str(config.data_dir / "media" / "habitudo-fr-0007" / "shot-00.mp4")
    ledger = conn.execute("SELECT * FROM cost_ledger").fetchall()
    assert len(ledger) == 1 and ledger[0]["estimated"] == 1 and ledger[0]["provider"] == "fal"
    assert ledger[0]["ref"] == "kling3-std|fal-ai/kling-video/v3/standard/text-to-video#req-1"
    assert ledger[0]["units"] == 5 and ledger[0]["unit"] == "seconds" and ledger[0]["app_id"] == "habitudo"
    assert sum(r.method == "POST" for r in server.requests) == 1
