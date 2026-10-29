"""Ajouter un iPhone à la ferme depuis le dashboard : son UDID s'écrit dans config/devices.yaml.

Le fichier reste la référence, lisible et commenté : on ne touche qu'aux lignes `udid:` / `owner:` / `model:` d'un
bloc, ou on ajoute un bloc à la fin de la liste. Jamais de réécriture complète : les commentaires restent, et
l'ordre des lignes, qui fixe les ports de chaque iPhone, ne bouge pas. La configuration en mémoire suit aussitôt :
pas besoin de relancer Loopcast.

Rien ne s'ajoute tout seul : un iPhone branché pour charger ne doit pas se retrouver piloté. Il faut un clic.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import yaml

from loopcast.config import Config, PhoneConfig

_lock = threading.Lock()


class RegistryError(Exception):
    """Ajout impossible ; le message s'affiche tel quel dans le dashboard."""


def devices_path(config: Config) -> Path:
    return config.root / "config" / "devices.yaml"


def slots(config: Config, connected: set[str]) -> list[dict]:
    """Les lignes de devices.yaml, dans l'ordre : libres (sans UDID), ou occupées par un iPhone branché ou non.
    `connected` : les UDID qui répondent en ce moment (un iPhone branché ne peut pas être remplacé)."""
    return [
        {
            "phone_id": p.id,
            "udid": p.udid,
            "free": not p.udid,
            "connected": bool(p.udid and p.udid in connected),
            "lang": p.lang,
            "owner": p.owner,
            "apps": list(p.apps),
            "accounts": {platform: (acc or {}).get("handle") or "" for platform, acc in p.accounts.items()},
        }
        for p in config.phones
    ]


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _item_start(phone_id: str) -> re.Pattern:
    return re.compile(rf"^(\s*)-\s+id:\s*[\"']?{re.escape(phone_id)}[\"']?\s*(#.*)?$")


ITEM = re.compile(r"^(\s*)-\s+\S")


def _set_fields(text: str, phone_id: str, fields: dict[str, str]) -> str:
    """Remplace la valeur de chaque champ dans le bloc de `phone_id` (en gardant un commentaire en fin de ligne),
    ou ajoute la ligne juste sous `- id:` si le champ manque."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if _item_start(phone_id).match(line)), None)
    if start is None:
        raise RegistryError(f"{phone_id} introuvable dans config/devices.yaml.")
    dash_indent = len(_item_start(phone_id).match(lines[start]).group(1))
    key_indent = " " * (dash_indent + 2)
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent <= dash_indent:       # bloc suivant (`- id:`) ou nouvelle clé de premier niveau
                break
        end += 1
    for key, value in fields.items():
        pattern = re.compile(rf"^({key_indent}{key}:[ \t]*)([^#\n]*?)([ \t]*#[^\n]*)?(\r?\n)?$")
        for i in range(start + 1, end):
            m = pattern.match(lines[i])
            if m:
                lines[i] = f"{m.group(1)}{_quote(value)}{m.group(3) or ''}{m.group(4) or ''}"
                break
        else:
            lines.insert(start + 1, f"{key_indent}{key}: {_quote(value)}\n")
            end += 1
    return "".join(lines)


def _append(text: str, phone: PhoneConfig, model: str) -> str:
    """Un bloc de plus à la fin de la liste `devices:`, au même retrait que les autres."""
    lines = text.splitlines(keepends=True)
    head = next((i for i, line in enumerate(lines) if re.match(r"^devices:\s*(#.*)?$", line)), None)
    if head is None:
        raise RegistryError("Liste `devices:` introuvable dans config/devices.yaml.")
    last, dash = head, "  "
    for i in range(head + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and not line.startswith("-"):
            break                           # clé de premier niveau suivante : fin de la liste
        last = i
        m = ITEM.match(line)
        if m:
            dash = m.group(1)
    keys = " " * (len(dash) + 2)
    block = (
        f"\n{dash}- id: {phone.id}\n"
        f"{keys}model: {_quote(model or 'iPhone')}\n"
        f"{keys}udid: {_quote(phone.udid or '')}\n"
        f"{keys}owner: {_quote(phone.owner)}\n"
        f"{keys}lang: {phone.lang}\n"
        f"{keys}brands: []\n"
        f"{keys}accounts: {{}}\n"
    )
    if lines and not lines[last].endswith("\n"):
        lines[last] += "\n"
    return "".join(lines[: last + 1]) + block + "".join(lines[last + 1 :])


def _write(path: Path, text: str, phone_id: str, udid: str) -> None:
    """Vérifie que le fichier se relit avec le bon UDID au bon endroit, puis l'écrit d'un coup (pas de fichier
    à moitié écrit si le Mac s'arrête)."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise RegistryError(f"config/devices.yaml ne se relirait pas : {e}") from e
    found = [d for d in data.get("devices") or [] if d.get("id") == phone_id]
    if len(found) != 1 or found[0].get("udid") != udid:
        raise RegistryError("Modification de config/devices.yaml impossible à vérifier : rien n'a été écrit.")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".devices-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _next_id(config: Config) -> str:
    numbers = [int(m.group(1)) for p in config.phones if (m := re.fullmatch(r"phone-(\d+)", p.id))]
    return f"phone-{max(numbers, default=0) + 1}"


def adopt(config: Config, udid: str, phone_id: str | None, *, connected: set[str], owner: str = "",
          model: str = "", lang: str = "fr") -> PhoneConfig:
    """Place l'iPhone `udid` sur la ligne `phone_id` : libre, ou occupée par un iPhone débranché qu'il remplace
    (il reprend ses comptes). Sans `phone_id`, une nouvelle ligne à la fin, dans la langue `lang`."""
    if config.demo:
        raise RegistryError("En démo, la ferme ne s'écrit pas : devices.yaml est celui de la vraie ferme.")
    owner = owner.strip()
    with _lock:
        existing = config.phone_by_udid(udid)
        if existing:
            raise RegistryError(f"Cet iPhone fait déjà partie de la ferme : {existing.id}.")
        path = devices_path(config)
        if not path.exists():
            example = path.with_name("devices.example.yaml")
            path.parent.mkdir(parents=True, exist_ok=True)
            if example.exists():
                shutil.copyfile(example, path)
            else:
                path.write_text("devices:\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8")

        if phone_id:
            phone = config.phone_by_id(phone_id)
            if phone is None:
                raise RegistryError(f"{phone_id} n'existe pas dans config/devices.yaml.")
            if phone.udid and phone.udid in connected:
                raise RegistryError(f"{phone_id} est branché en ce moment : impossible de le remplacer.")
            fields = {"udid": udid}
            if owner:
                fields["owner"] = owner
            if model:
                fields["model"] = model
            _write(path, _set_fields(text, phone_id, fields), phone_id, udid)
            phone.udid = udid
            if owner:
                phone.owner = owner
            return phone

        phone = PhoneConfig(_next_id(config), udid, owner=owner, lang=lang if lang in ("fr", "en") else "fr",
                            slot=len(config.phones))
        _write(path, _append(text, phone, model), phone.id, udid)
        config.phones.append(phone)
        return phone
