"""Publishers : registre par canal (replis manuels), ManualPublisher, légende, et le brouillon iPhone
contre un faux Appium et un faux pymobiledevice3 (jamais contre un vrai téléphone)."""

import base64
import json
import subprocess
from pathlib import Path

import httpx

from loopcast.accounts import Account
from loopcast.diffusion.publishers import ManualPublisher, Publishers
from loopcast.diffusion.publishers.base import ContentItem
from loopcast.diffusion.publishers.ios_app import IosAppPublisher, ShortcutImporter, predicate, shortcut_url
from loopcast.diffusion.publishers.official import InstagramGraphPublisher, TikTokPublisher
from loopcast.diffusion.settings import IosAppSettings
from loopcast.farm.control import WDA_SETTINGS, PhoneController

from .conftest import make_config, phone


def account(channel="manual", platform="tiktok", device="phone-1") -> Account:
    return Account(f"{device}:{platform}", device, platform, "@habitudo.fr", "2026-10-01", channel, "habitudo", "fr",
                   True)


def item(**kw) -> ContentItem:
    base = dict(id="c1", app_id="habitudo", lang="fr", format="notes-app", kind="video", caption="Ma légende",
                hashtags=["habitudes", "#focus"], files=[])
    base.update(kw)
    return ContentItem(**base)


def test_registry_falls_back_to_manual_until_apis_are_wired(tmp_path):
    reg = Publishers(make_config(tmp_path))
    direct = reg.for_account(account("api_direct"))
    assert isinstance(direct, ManualPublisher) and "squelette" in direct.reason
    assert isinstance(reg.for_account(account("api_draft", "instagram")), ManualPublisher)
    ios = reg.for_account(account("ios_app"))
    assert isinstance(ios, ManualPublisher) and "diffusion.ios_app.enabled" in ios.reason
    assert "Canal inconnu" in reg.for_account(account("pigeon")).reason
    assert reg.requires_human(account("api_draft")) and reg.requires_human(account("api_direct"))
    enabled = Publishers(make_config(tmp_path, settings={"diffusion": {"ios_app": {"enabled": True}}}))
    assert isinstance(enabled.for_account(account("ios_appium")), IosAppPublisher)
    assert enabled.requires_human(account("ios_app"))                          # mode assist par défaut


def test_api_skeletons_never_call_out():
    for api in (TikTokPublisher("direct"), TikTokPublisher("inbox"), InstagramGraphPublisher()):
        assert not api.available and "squelette" in api.unavailable_reason
        res = api.publish(account(), item(), [])
        assert res.status == "failed" and not res.retryable
        assert api.fetch_metrics(account(), ["1"]) == {}
    assert TikTokPublisher("inbox").requires_human


def test_manual_publisher_says_what_to_do(tmp_path):
    res = ManualPublisher("Canal api_draft pas encore branché.").publish(
        account(), item(ai_label=True), [tmp_path / "c1.mp4"])
    assert res.status == "needs_human"
    assert "TikTok (@habitudo.fr) depuis le téléphone phone-1" in res.log and "c1.mp4" in res.log
    assert "pas encore branché" in res.log and "contenu généré par IA" in res.log


def test_caption_and_hashtags():
    assert item().post_text() == "Ma légende\n\n#habitudes #focus"
    assert item(caption="", hashtags=["a"]).post_text() == "#a"
    many = item(caption="x" * 2190, hashtags=[f"t{i}" for i in range(40)]).post_text()
    assert len(many) == 2200 and many.count("#") <= 30


def test_shortcut_url_and_predicate():
    assert shortcut_url("Loopcast Import", "loopcast-c1-0.mp4") == \
        "shortcuts://run-shortcut?name=Loopcast%20Import&input=text&text=loopcast-c1-0.mp4"
    assert predicate(("Publier", "Post"), "XCUIElementTypeButton") == (
        "type == 'XCUIElementTypeButton' AND (label IN {'Publier', 'Post'} OR name IN {'Publier', 'Post'}) "
        "AND visible == 1")
    assert "'l\\'app'" in predicate(("l'app",))


# --- Brouillon iPhone (NON VÉRIFIÉ sur un vrai téléphone) -------------------------------------------------------

class FakeWda:
    """Faux Appium : chaque élément cherché est trouvé, sauf les libellés de `absent`."""

    def __init__(self, absent=("Pas maintenant",)):
        self.absent = absent
        self.calls: list[tuple[str, str, dict | None]] = []
        self.elements: dict[str, str] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if request.method == "POST" and path == "/session":
            return httpx.Response(200, json={"value": {"sessionId": "s1", "capabilities": {}}})
        if path.endswith("/window/rect"):
            return httpx.Response(200, json={"value": {"x": 0, "y": 0, "width": 393, "height": 852}})
        if path.endswith("/screenshot"):
            return httpx.Response(200, json={"value": base64.b64encode(b"PNG").decode()})
        if path.endswith("/element") and request.method == "POST":
            if any(a in body["value"] for a in self.absent):
                return httpx.Response(404, json={"value": {"error": "no such element", "message": "absent"}})
            el = f"el{len(self.elements) + 1}"
            self.elements[el] = body["value"]
            return httpx.Response(200, json={"value": {"element-6066-11e4-a52e-4f735466cecf": el}})
        return httpx.Response(200, json={"value": None})

    def clicked(self) -> list[str]:
        return [self.elements[p.split("/")[4]] for m, p, _ in self.calls if p.endswith("/click")]

    def scripts(self) -> list[dict]:
        return [b for m, p, b in self.calls if p.endswith("/execute/sync")]


class FakeCli:
    """Faux pymobiledevice3 : le reçu « .ok » du raccourci est là au `receipt_after`-ième essai."""

    def __init__(self, receipt_after=1):
        self.commands: list[list[str]] = []
        self.receipt_after = receipt_after
        self.pulls = 0

    def __call__(self, cmd, **kw):
        self.commands.append(cmd)
        code = 0
        if cmd[1:3] == ["apps", "pull"]:
            self.pulls += 1
            code = 0 if self.pulls >= self.receipt_after else 1
        return subprocess.CompletedProcess(cmd, code, "", "" if code == 0 else "ObjectNotFound")


class Ticker:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def ios_setup(tmp_path, conn, *, mode="assist", absent=("Pas maintenant",), receipt_after=1, udid=True):
    cfg = make_config(tmp_path, [phone("phone-1", tiktok={"channel": "ios_app"}, instagram={"channel": "ios_app"})])
    if not udid:
        cfg.phones[0].udid = None
    conn.execute("INSERT INTO phones(udid, phone_id) VALUES ('UDID-phone-1', 'phone-1')")
    wda = FakeWda(absent)
    ctl = PhoneController(cfg, conn, httpx.Client(transport=httpx.MockTransport(wda), base_url="http://appium"))
    tick, runner = Ticker(), FakeCli(receipt_after)
    settings = IosAppSettings(enabled=True, mode=mode, import_timeout_s=30)
    importer = ShortcutImporter(settings, run=runner, sleep=tick.sleep, monotonic=tick)
    pub = IosAppPublisher(cfg, settings, controller_factory=lambda: ctl, importer=importer, sleep=tick.sleep,
                          monotonic=tick)
    video = tmp_path / "c1.mp4"
    video.write_bytes(b"x")
    return pub, wda, runner, video


def test_ios_assist_prepares_everything_and_stops_before_publish(tmp_path, conn):
    pub, wda, runner, video = ios_setup(tmp_path, conn)
    res = pub.publish(account("ios_app"), item(files=[str(video)]), [video])
    assert res.status == "needs_human" and "non vérifié" in res.log and "« Publier »" in res.log
    push = runner.commands[0]
    assert push[:4] == ["pymobiledevice3", "apps", "push", "com.apple.Keynote"]
    assert push[5:] == ["/Documents/loopcast-c1-0.mp4", "--documents", "--udid", "UDID-phone-1"]
    assert wda.scripts()[0] == {"script": "mobile: deepLink", "args": [
        {"url": "shortcuts://run-shortcut?name=Loopcast%20Import&input=text&text=loopcast-c1-0.mp4"}]}
    assert wda.scripts()[1] == {"script": "mobile: launchApp", "args": [{"bundleId": "com.zhiliaoapp.musically"}]}
    clicked = wda.clicked()
    assert "Créer" in clicked[0] and "Importer" in clicked[1] and "Suivant" in clicked[-2]
    publish = predicate(("Publier", "Post"), "XCUIElementTypeButton")
    assert list(wda.elements.values())[-1] == publish                         # cherché à la fin…
    assert publish not in clicked                                             # … jamais appuyé en mode assist
    typed = [b for m, p, b in wda.calls if p.endswith("/value")]
    assert typed == [{"text": "Ma légende\n\n#habitudes #focus"}]
    settings_calls = [b["settings"] for m, p, b in wda.calls if p.endswith("/appium/settings")]
    assert settings_calls[-1] == WDA_SETTINGS                                 # réglages de la ferme rétablis


def test_ios_auto_mode_presses_publish_but_not_for_ai_content(tmp_path, conn):
    pub, wda, _runner, video = ios_setup(tmp_path, conn, mode="auto")
    res = pub.publish(account("ios_app", "instagram"), item(files=[str(video)], ai_label=True), [video])
    assert res.status == "needs_human" and "étiquette" in res.log             # label IA : à la main
    assert not any("Partager" in c for c in wda.clicked())


def test_ios_auto_mode_leaves_the_mandatory_disclosures_to_a_human(tmp_path, conn):
    """TikTok exige « Votre marque » pour sa propre app : tant que le parcours ne l'active pas, un humain publie."""
    pub, wda, _runner, video = ios_setup(tmp_path, conn, mode="auto")
    res = pub.publish(account("ios_app", "tiktok"), item(files=[str(video)], ai_label=False), [video])
    assert res.status == "needs_human" and "Votre marque" in res.log
    assert not {"Publier", "Post"} & set(wda.clicked())        # le bouton final n'est jamais touché


def test_ios_failure_keeps_a_screenshot(tmp_path, conn):
    pub, _wda, _runner, video = ios_setup(tmp_path, conn, absent=("Pas maintenant", "Importer"))
    res = pub.publish(account("ios_app"), item(files=[str(video)]), [video])
    assert res.status == "failed" and res.retryable and "introuvable : « Importer" in res.log
    shots = list((Path(tmp_path) / "data" / "ios_app").glob("*.png"))
    assert len(shots) == 1 and shots[0].read_bytes() == b"PNG"


def test_ios_import_not_confirmed(tmp_path, conn):
    pub, wda, _runner, video = ios_setup(tmp_path, conn, receipt_after=99)
    res = pub.publish(account("ios_app"), item(files=[str(video)]), [video])
    assert res.status == "failed" and "import dans Photos non confirmé" in res.log
    assert not wda.clicked()


def test_ios_needs_an_udid(tmp_path, conn):
    pub, wda, _runner, video = ios_setup(tmp_path, conn, udid=False)
    res = pub.publish(account("ios_app"), item(files=[str(video)]), [video])
    assert res.status == "failed" and not res.retryable and "UDID" in res.log and wda.calls == []


def test_ios_needs_the_rendered_file(tmp_path, conn):
    pub, wda, runner, _video = ios_setup(tmp_path, conn)
    res = pub.publish(account("ios_app"), item(), [Path("/nulle/part.mp4")])
    assert res.status == "failed" and not res.retryable and "fichier introuvable" in res.log
    assert wda.calls == [] and runner.commands == []
