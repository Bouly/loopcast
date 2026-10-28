"""Publication par les APIs officielles (REPRISE §5.6) : SQUELETTE DOCUMENTÉ, aucun appel réel.

Ce fichier fixe l'interface et le parcours de chaque API pour celui qui les branchera (jetons OAuth,
stockage objet). Tant que `available` est faux, le registre bascule le compte en publication manuelle
(le post passe « à finir ») : la chaîne tourne quand même, et le dashboard dit pourquoi.

Vérifié dans la documentation officielle le 29/10/2026 (à revérifier au moment de brancher) :

TikTok — Content Posting API, https://open.tiktokapis.com, jeton utilisateur OAuth (`Authorization: Bearer`)
- Avant une publication directe : POST /v2/post/publish/creator_info/query/ → `privacy_level_options` (la
  valeur envoyée doit en faire partie), durée maximale, interactions désactivées.
- Publication directe (canal api_direct), scope `video.publish` : POST /v2/post/publish/video/init/
  `{"post_info": {"title": légende ≤ 2200, "privacy_level": …, "disable_duet", "disable_comment",
  "disable_stitch", "video_cover_timestamp_ms", "is_aigc": content.ai_label},
   "source_info": {"source": "PULL_FROM_URL", "video_url": …}}` (ou FILE_UPLOAD : video_size, chunk_size,
  total_chunk_count, puis PUT sur `upload_url`, valable 1 h) → `publish_id`.
  Tant que l'app n'est pas auditée par TikTok, tout ce qu'elle publie reste PRIVÉ.
- Brouillon (canal api_draft), scope `video.upload` : POST /v2/post/publish/inbox/video/init/
  `{"source_info": {...}}` → `publish_id` ; la vidéo arrive dans la boîte de réception TikTok du compte,
  la personne finit le post dans l'app → statut `needs_human`. Limites : 6 requêtes/min par jeton,
  au plus 5 partages en attente sur 24 h.
- Suivi : POST /v2/post/publish/status/fetch/ `{"publish_id"}` → status (PROCESSING_UPLOAD,
  PROCESSING_DOWNLOAD, SEND_TO_USER_INBOX, PUBLISH_COMPLETE, FAILED) et, une fois public,
  `publicaly_available_post_id` (orthographe de l'API) = l'id de la vidéo.
- Photos (format slideshow) : POST /v2/post/publish/content/init/ avec `media_type: PHOTO`,
  `post_mode: DIRECT_POST | MEDIA_UPLOAD`, images par URL sur un domaine vérifié chez TikTok.
- PULL_FROM_URL : le domaine (ou préfixe d'URL) des médias doit être vérifié, sinon 403
  `url_ownership_unverified`.
- Métriques, scope `video.list` : POST /v2/video/query/?fields=id,view_count,like_count,comment_count,share_count
  `{"filters": {"video_ids": [...]}}` (20 ids au plus par appel).

Instagram — Instagram API avec Instagram Login, https://graph.instagram.com/<version>/, compte
professionnel, permissions `instagram_business_basic`, `instagram_business_content_publish`
(+ `instagram_business_manage_insights` pour les vues)
- Reel : POST /<IG_ID>/media `media_type=REELS, video_url, caption, share_to_feed=true` → id du conteneur ;
  GET /<container_id>?fields=status_code jusqu'à FINISHED (IN_PROGRESS, ERROR, EXPIRED) ;
  POST /<IG_ID>/media_publish `creation_id=<container_id>` → id du média.
- Carrousel : un conteneur par image (JPEG seulement, `is_carousel_item=true`), puis un conteneur
  `media_type=CAROUSEL, children=…` (10 au plus), puis media_publish.
- Avant de publier : GET /<IG_ID>/content_publishing_limit (plafond sur 24 h glissantes, très au-dessus
  de nos 5 posts/jour).
- Métriques : GET /<IG_MEDIA_ID>/insights?metric=views,likes,comments,shares,saved,reach
  (`impressions` est abandonnée pour les médias publiés après le 02/07/2024).
- Label IA : pas de paramètre de publication trouvé dans la doc de l'API ; à vérifier avant de publier
  un contenu `ai_label` par API (sinon : canal manuel pour ces contenus).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, PublishResult

TIKTOK_API = "https://open.tiktokapis.com"
INSTAGRAM_API = "https://graph.instagram.com"

NOT_WIRED = ("squelette : les appels réels à l'API ne sont pas encore écrits "
             "(jetons OAuth et stockage objet à brancher, voir diffusion/publishers/official.py)")

TokenProvider = Callable[[Account], "str | None"]


class _ApiSkeleton:
    """Commun aux deux squelettes : indisponible tant que les appels ne sont pas écrits."""

    name = "api"
    requires_human = False

    def __init__(self, token_provider: TokenProvider | None = None):
        self.token_provider = token_provider

    @property
    def available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str:
        return NOT_WIRED

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult:
        return PublishResult.failed(f"{self.name} : {NOT_WIRED}", retryable=False)

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]:
        return {}


class TikTokPublisher(_ApiSkeleton):
    """Content Posting API. `mode="direct"` (canal api_direct) ou `"inbox"` (api_draft, brouillon)."""

    def __init__(self, mode: str = "direct", token_provider: TokenProvider | None = None):
        if mode not in ("direct", "inbox"):
            raise ValueError(f"mode TikTok inconnu : {mode}")
        super().__init__(token_provider)
        self.mode = mode
        self.name = f"tiktok_{mode}"
        self.requires_human = mode == "inbox"

    # Parcours prévu de publish() :
    #   1. media → URL publique temporaire (storage.py, domaine vérifié chez TikTok)
    #   2. direct : _creator_info() puis _init_direct_post() ; inbox : _init_inbox_upload()
    #   3. _fetch_status(publish_id) jusqu'à PUBLISH_COMPLETE (direct → posted, external_id =
    #      publicaly_available_post_id) ou SEND_TO_USER_INBOX (inbox → needs_human)
    #   4. supprimer le fichier du stockage objet
    # fetch_metrics() : _query_videos(external_ids) par paquets de 20.

    def _creator_info(self, token: str) -> dict:
        raise NotImplementedError("POST /v2/post/publish/creator_info/query/")

    def _init_direct_post(self, token: str, content: ContentItem, video_url: str, privacy_level: str) -> str:
        raise NotImplementedError("POST /v2/post/publish/video/init/ (post_info.is_aigc = content.ai_label)")

    def _init_inbox_upload(self, token: str, video_url: str) -> str:
        raise NotImplementedError("POST /v2/post/publish/inbox/video/init/")

    def _fetch_status(self, token: str, publish_id: str) -> dict:
        raise NotImplementedError("POST /v2/post/publish/status/fetch/")

    def _query_videos(self, token: str, video_ids: list[str]) -> dict[str, Metrics]:
        raise NotImplementedError("POST /v2/video/query/?fields=id,view_count,like_count,comment_count,share_count")


class InstagramGraphPublisher(_ApiSkeleton):
    """Instagram API avec Instagram Login (compte professionnel). Canal api_direct."""

    name = "instagram_graph"

    # Parcours prévu de publish() :
    #   1. _publishing_limit() ; refuser proprement si le plafond est atteint (failed, retryable)
    #   2. media → URL publique temporaire ; vidéo : _create_reel_container() ; carrousel : JPEG + enfants
    #   3. _wait_container() jusqu'à FINISHED (RetryLater côté tâche si long), puis _publish_container()
    #   4. posted, external_id = id du média ; supprimer les fichiers du stockage objet
    # fetch_metrics() : _insights(media_id) pour chaque id.

    def _publishing_limit(self, token: str, ig_id: str) -> dict:
        raise NotImplementedError("GET /<IG_ID>/content_publishing_limit")

    def _create_reel_container(self, token: str, ig_id: str, video_url: str, caption: str) -> str:
        raise NotImplementedError("POST /<IG_ID>/media media_type=REELS")

    def _wait_container(self, token: str, container_id: str) -> str:
        raise NotImplementedError("GET /<container_id>?fields=status_code")

    def _publish_container(self, token: str, ig_id: str, container_id: str) -> str:
        raise NotImplementedError("POST /<IG_ID>/media_publish creation_id=…")

    def _insights(self, token: str, media_id: str) -> Metrics:
        raise NotImplementedError("GET /<IG_MEDIA_ID>/insights?metric=views,likes,comments,shares")
