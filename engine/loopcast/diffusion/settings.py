"""Réglages du module diffusion, lus une fois avec leurs valeurs par défaut.

Sources (un réglage absent prend la valeur par défaut ci-dessous) :
- `config/devices.yaml`, section `defaults` : fuseau, créneaux, présence humaine, écart minimal, plafond humain ;
- `config/settings.yaml` : `pipeline.*`, `regulator.*`, `metrics_every_hours`, `post_mode`, `stock_target`,
  et la section propre au module, `diffusion.*`.

Le plafond de 5 posts par jour et par compte (REPRISE §3) n'est PAS un réglage : c'est HARD_CAP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HARD_CAP = 5                     # posts par jour et par compte, quoi qu'en disent les réglages

DEFAULT_WINDOWS = ["07:30-09:00", "12:00-14:00", "18:00-22:30"]
DEFAULT_HUMAN_WINDOWS = ["09:00-21:00"]
DEFAULT_RAMP = [{"from_day": 0, "per_day": 1}, {"from_day": 7, "per_day": 2}, {"from_day": 14, "per_day": "max"}]

# Canaux qui demandent une personne au bout de la chaîne : le post ne part qu'aux heures de présence.
HUMAN_CHANNELS = {"manual", "api_draft"}


class SettingsError(ValueError):
    """Réglage illisible : le message dit lequel et ce qui est attendu."""


@dataclass(frozen=True)
class RampStep:
    from_day: int
    per_day: int | None          # None = « max » : la cadence visée


@dataclass
class IosAppSettings:
    enabled: bool = False                    # brouillon non vérifié : désactivé tant qu'un humain ne l'a pas validé
    mode: str = "assist"                     # assist = s'arrête avant « Publier » ; auto = appuie dessus
    inbox_bundle_id: str = "com.apple.Keynote"   # app avec partage de fichiers où la vidéo transite (USB)
    shortcut_name: str = "Loopcast Import"
    album: str = "Loopcast"
    import_timeout_s: int = 120


@dataclass
class DiffusionSettings:
    timezone: str = "Europe/Paris"
    windows: list[str] = field(default_factory=lambda: list(DEFAULT_WINDOWS))
    human_windows: list[str] = field(default_factory=lambda: list(DEFAULT_HUMAN_WINDOWS))
    min_gap_minutes: int = 180
    max_per_day: int | None = None           # plafond posé à la main dans devices.yaml (facultatif)
    posts_per_day: int = 3                   # pipeline.posts_per_day_per_account (si pas de stratégie approuvée)
    ramp: list[RampStep] = field(default_factory=list)
    metrics_min_age_hours: int = 24
    slow_down_ratio: float = 0.4
    speed_up_ratio: float = 1.5
    dead_views: int = 30
    pause_hours: int = 48
    metrics_every_hours: int = 6
    metrics_days: int = 30                   # on relève les vues des posts publiés depuis ce nombre de jours
    stock_target: int = 6
    stock_check_hours: int = 6
    jitter_minutes: int = 20
    instagram_offset_minutes: tuple[int, int] = (30, 90)
    retry_minutes: tuple[int, ...] = (10, 30)
    late_tolerance_minutes: int = 60
    lead_minutes: int = 5
    running_timeout_minutes: int = 45
    winners_window_days: int = 14
    winners_top_share: float = 0.2
    winners_min_posts: int = 5
    dry_run: bool = False
    post_mode: str = "assist"
    notify: dict[str, Any] = field(default_factory=dict)
    ios_app: IosAppSettings = field(default_factory=IosAppSettings)

    def __post_init__(self) -> None:
        if not self.ramp:
            self.ramp = parse_ramp(DEFAULT_RAMP)

    @property
    def tz(self) -> ZoneInfo:
        return zone(self.timezone)

    @property
    def max_attempts(self) -> int:
        """Première tentative + une par délai de `retry_minutes` (2 nouvelles tentatives par défaut)."""
        return 1 + len(self.retry_minutes)

    @classmethod
    def from_config(cls, config: Any) -> "DiffusionSettings":
        settings = dict(getattr(config, "settings", None) or {})
        defaults = dict(getattr(config, "defaults", None) or {})
        regulator = dict(settings.get("regulator") or {})
        pipeline = dict(settings.get("pipeline") or {})
        mine = dict(settings.get("diffusion") or {})
        winners = dict(mine.get("winners") or {})
        ios = dict(mine.get("ios_app") or {})
        post_mode = str(settings.get("post_mode") or "assist")

        def num(section: dict, key: str, default: int, label: str, lo: int = 0) -> int:
            return _int(section.get(key), default, label, lo=lo)

        max_per_day = defaults.get("max_per_day")
        out = cls(
            timezone=str(defaults.get("timezone") or "Europe/Paris"),
            windows=_str_list(defaults.get("windows"), DEFAULT_WINDOWS, "defaults.windows"),
            human_windows=_str_list(defaults.get("human_windows"), DEFAULT_HUMAN_WINDOWS, "defaults.human_windows"),
            min_gap_minutes=num(defaults, "min_gap_minutes", 180, "defaults.min_gap_minutes"),
            max_per_day=(None if max_per_day in (None, "", "max")
                         else _int(max_per_day, 3, "defaults.max_per_day", lo=0)),
            posts_per_day=num(pipeline, "posts_per_day_per_account", 3, "pipeline.posts_per_day_per_account"),
            ramp=parse_ramp(regulator.get("ramp") or DEFAULT_RAMP),
            metrics_min_age_hours=num(regulator, "metrics_min_age_hours", 24, "regulator.metrics_min_age_hours"),
            slow_down_ratio=_float(regulator.get("slow_down_ratio"), 0.4, "regulator.slow_down_ratio"),
            speed_up_ratio=_float(regulator.get("speed_up_ratio"), 1.5, "regulator.speed_up_ratio"),
            dead_views=num(regulator, "dead_views", 30, "regulator.dead_views"),
            pause_hours=num(regulator, "pause_hours", 48, "regulator.pause_hours", lo=1),
            metrics_every_hours=_int(mine.get("metrics_every_hours", settings.get("metrics_every_hours")), 6,
                                     "metrics_every_hours", lo=1),
            metrics_days=num(mine, "metrics_days", 30, "diffusion.metrics_days", lo=1),
            stock_target=_int(pipeline.get("stock_target", settings.get("stock_target")), 6,
                              "pipeline.stock_target", lo=0),
            stock_check_hours=num(mine, "stock_check_hours", 6, "diffusion.stock_check_hours", lo=1),
            jitter_minutes=num(mine, "jitter_minutes", 20, "diffusion.jitter_minutes"),
            instagram_offset_minutes=_pair(mine.get("instagram_offset_minutes"), (30, 90),
                                           "diffusion.instagram_offset_minutes"),
            retry_minutes=tuple(_int(v, 10, "diffusion.retry_minutes", lo=1)
                                for v in (mine.get("retry_minutes") or (10, 30))),
            late_tolerance_minutes=num(mine, "late_tolerance_minutes", 60, "diffusion.late_tolerance_minutes", lo=1),
            lead_minutes=num(mine, "lead_minutes", 5, "diffusion.lead_minutes"),
            running_timeout_minutes=num(mine, "running_timeout_minutes", 45, "diffusion.running_timeout_minutes", lo=5),
            winners_window_days=num(winners, "window_days", 14, "diffusion.winners.window_days", lo=1),
            winners_top_share=_float(winners.get("top_share"), 0.2, "diffusion.winners.top_share"),
            winners_min_posts=num(winners, "min_posts", 5, "diffusion.winners.min_posts", lo=1),
            dry_run=bool(mine.get("dry_run", False)),
            post_mode=post_mode,
            notify=dict(settings.get("notify") or {}),
            ios_app=IosAppSettings(
                enabled=bool(ios.get("enabled", False)),
                mode=str(ios.get("mode") or post_mode),
                inbox_bundle_id=str(ios.get("inbox_bundle_id") or IosAppSettings.inbox_bundle_id),
                shortcut_name=str(ios.get("shortcut_name") or IosAppSettings.shortcut_name),
                album=str(ios.get("album") or IosAppSettings.album),
                import_timeout_s=num(ios, "import_timeout_s", 120, "diffusion.ios_app.import_timeout_s", lo=10),
            ),
        )
        zone(out.timezone)                              # fuseau inconnu : erreur claire tout de suite
        for label, wins in (("windows", out.windows), ("human_windows", out.human_windows)):
            for w in wins:
                parse_window(w, label)
        return out


# --- Lecture tolérante, erreurs explicites ---------------------------------------------------------

def _int(value: Any, default: int, label: str, lo: int | None = None) -> int:
    if value is None or value == "":
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{label} : nombre entier attendu, pas « {value} »") from None
    if lo is not None and out < lo:
        raise SettingsError(f"{label} : {out} est trop petit (minimum {lo})")
    return out


def _float(value: Any, default: float, label: str) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{label} : nombre attendu, pas « {value} »") from None


def _pair(value: Any, default: tuple[int, int], label: str) -> tuple[int, int]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value), int(value)
    try:
        lo, hi = (int(v) for v in value)
    except (TypeError, ValueError):
        raise SettingsError(f"{label} : [minimum, maximum] en minutes attendu, pas « {value} »") from None
    return (min(lo, hi), max(lo, hi))


def _str_list(value: Any, default: list[str], label: str) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise SettingsError(f"{label} : liste de créneaux « HH:MM-HH:MM » attendue")
    return [str(v) for v in value]


def parse_ramp(raw: Any) -> list[RampStep]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise SettingsError("regulator.ramp : liste de {from_day, per_day} attendue")
    steps = []
    for item in raw:
        if not isinstance(item, dict) or "from_day" not in item:
            raise SettingsError(f"regulator.ramp : étape illisible « {item} » (attendu {{from_day: 7, per_day: 2}})")
        per_day = item.get("per_day", "max")
        steps.append(RampStep(_int(item["from_day"], 0, "regulator.ramp.from_day", lo=0),
                              None if per_day in (None, "max") else _int(per_day, 1, "regulator.ramp.per_day", lo=0)))
    return sorted(steps, key=lambda s: s.from_day)


# --- Heures et fuseaux ---------------------------------------------------------------------------------

def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SettingsError(f"fuseau horaire inconnu : « {name} » (ex. Europe/Paris)") from None


def parse_window(text: str, label: str = "windows") -> tuple[int, int]:
    """« 07:30-09:00 » → (450, 540), en minutes depuis minuit. Un créneau qui passe minuit s'arrête à minuit."""
    try:
        a, b = (part.strip() for part in str(text).split("-"))
        start, end = _minutes(a), _minutes(b)
    except ValueError:
        raise SettingsError(f"{label} : créneau illisible « {text} » (attendu HH:MM-HH:MM)") from None
    if end == start:
        raise SettingsError(f"{label} : créneau vide « {text} »")
    if end < start:
        end = 24 * 60 - 1
    return start, end


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 24 and 0 <= m < 60) or h * 60 + m > 24 * 60:
        raise ValueError(hhmm)
    return min(h * 60 + m, 24 * 60 - 1)


def parse_windows(texts: list[str], label: str = "windows") -> list[tuple[int, int]]:
    """Créneaux triés et fusionnés quand ils se chevauchent."""
    spans = sorted(parse_window(t, label) for t in texts)
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


MIN_SPAN_MINUTES = 15            # une intersection plus courte forcerait la même heure pile chaque jour


def intersect(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if e - s >= MIN_SPAN_MINUTES:
                out.append((s, e))
    return sorted(out)


def local_day(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Début et fin (exclue) de la journée locale, en UTC."""
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def at_minute(day: date, minute: int, tz: ZoneInfo) -> datetime:
    """La minute `minute` de la journée locale `day`, en UTC."""
    minute = max(0, min(int(minute), 24 * 60 - 1))
    local = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=tz)
    return local.astimezone(timezone.utc)


def minute_of(dt: datetime, day: date, tz: ZoneInfo) -> int:
    """Heure locale de `dt` en minutes depuis minuit le jour `day` (heure murale : les changements
    d'heure ne décalent rien ; hors de 0..1439 si `dt` tombe un autre jour)."""
    local = dt.astimezone(tz)
    return (local.date() - day).days * 24 * 60 + local.hour * 60 + local.minute
