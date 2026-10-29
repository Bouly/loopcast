import {
  Alert02Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  Loading03Icon,
  PlayIcon,
  VolumeHighIcon,
  VolumeOffIcon,
} from "@hugeicons/core-free-icons";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
} from "react";
import { Icon } from "../../ui";
import type { ContentItem } from "./api";
import { reducedMotion } from "./bits";

export type SwipeDirection = "left" | "right";

export type PlayerHandle = {
  togglePlay: () => void;
  /** Appelé dans le geste (clic, touche) : Safari n'accepte le son que là. */
  toggleSound: () => void;
  /** Carrousel : image précédente (-1) ou suivante (+1). */
  step: (delta: number) => void;
  /** La carte part sur le côté (geste confirmé) pendant que la suivante s'affiche. */
  flyOut: (direction: SwipeDirection) => void;
};

type Props = {
  item: ContentItem;
  muted: boolean;
  onMuted: (muted: boolean) => void;
  /** Absent : pas de geste (historique). Droite = garder, gauche = jeter. */
  onSwipe?: (direction: SwipeDirection) => void;
  /** Où en est le fichier : la page refuse de garder une vidéo qu'on n'a pas pu voir. */
  onStatus?: (status: MediaStatus) => void;
  label: string;
};

export type MediaStatus = "loading" | "ready" | "error";

type Ghost = { id: number; src: string; direction: SwipeDirection; from: number };

const SWIPE_MIN = 40;

/** La vidéo (ou le carrousel) en 9:16 : lecture en boucle sans son au départ, glisser pour décider. */
export const Player = forwardRef<PlayerHandle, Props>(function Player(
  { item, muted, onMuted, onSwipe, onStatus, label },
  ref,
) {
  const isCarousel = item.kind === "carousel";
  const mediaKey = `${item.id}:${item.run ?? 0}:${item.media.join("|")}`;

  const [key, setKey] = useState(mediaKey);
  const [status, setStatus] = useState<MediaStatus>("loading");
  const [paused, setPaused] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [index, setIndex] = useState(0);
  const [enter, setEnter] = useState(0);
  if (key !== mediaKey) {
    // Nouvelle vidéo : on repart de zéro (le même élément <video> est gardé, il garde le son autorisé sur iPhone).
    setKey(mediaKey);
    setStatus("loading");
    setPaused(false);
    setBuffering(false);
    setAttempt(0);
    setIndex(0);
    setEnter((n) => n + 1);
  }

  const video = useRef<HTMLVideoElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const total = item.media.length;
  const src = item.media[isCarousel ? index : 0];
  const url = src ? `${src}${attempt ? `?essai=${attempt}` : ""}` : null;

  const effective: MediaStatus = url ? status : "error";
  useEffect(() => onStatus?.(effective), [effective, onStatus]);

  // --- Vidéo : son, lecture automatique, progression ---------------------------------------------------

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.muted = muted;
    v.defaultMuted = muted;
  }, [muted, url]);

  useEffect(() => {
    const v = video.current;
    if (!v || !url || isCarousel) return;
    v.play().catch((e: DOMException) => {
      // Lecture avec le son refusée sans geste (Safari) : on repart sans le son, la personne le remettra.
      if (e?.name === "NotAllowedError" && !v.muted) {
        onMuted(true);
        v.muted = true;
        void v.play().catch(() => setPaused(true));
      } else if (e?.name === "NotAllowedError") {
        setPaused(true);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, isCarousel]);

  useEffect(() => {
    if (isCarousel || paused) return;
    let frame = 0;
    const tick = () => {
      const v = video.current;
      if (v && bar.current && v.duration) bar.current.style.transform = `scaleX(${v.currentTime / v.duration})`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [isCarousel, paused, url]);

  const togglePlay = useCallback(() => {
    const v = video.current;
    if (!v || isCarousel) return;
    if (v.paused) void v.play().catch(() => setPaused(true));
    else v.pause();
  }, [isCarousel]);

  const toggleSound = useCallback(() => {
    const v = video.current;
    if (isCarousel) return;
    const next = !muted;
    if (v) {
      v.muted = next; // dans le geste lui-même : Safari n'autorise le son qu'ici
      if (!next && v.paused) void v.play().catch(() => {});
    }
    onMuted(next);
  }, [isCarousel, muted, onMuted]);

  const seek = (e: MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    const v = video.current;
    if (!v || !v.duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    v.currentTime = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 0.999) * v.duration;
  };

  // --- Carrousel ------------------------------------------------------------------------------------------

  const indexRef = useRef(index);
  indexRef.current = index;
  const step = useCallback(
    (delta: number) => {
      if (!isCarousel || total < 2) return;
      const next = Math.min(Math.max(indexRef.current + delta, 0), total - 1);
      if (next === indexRef.current) return;
      indexRef.current = next; // deux appuis rapides s'additionnent avant le prochain rendu
      setIndex(next);
      setStatus("loading");
    },
    [isCarousel, total],
  );

  useEffect(() => {
    // Les images voisines se chargent d'avance : passer de l'une à l'autre est instantané.
    if (!isCarousel) return;
    for (const n of [index - 1, index + 1]) if (item.media[n]) new Image().src = item.media[n];
  }, [isCarousel, index, item.media]);

  // --- Geste : glisser à droite (garder) ou à gauche (jeter) -------------------------------------------------

  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; y: number; id: number; t: number; width: number } | null>(null);
  const active = useRef(false);
  const moved = useRef(false);
  const released = useRef({ dx: 0, at: 0 });
  const [ghosts, setGhosts] = useState<Ghost[]>([]);

  const flyOut = useCallback(
    (direction: SwipeDirection) => {
      const poster = item.poster ?? (isCarousel ? item.media[0] : null);
      if (!poster || reducedMotion()) return;
      const from = performance.now() - released.current.at < 400 ? released.current.dx : 0;
      const ghost = { id: Date.now(), src: poster, direction, from };
      setGhosts((g) => [...g, ghost]);
      window.setTimeout(() => setGhosts((g) => g.filter((x) => x.id !== ghost.id)), 240);
    },
    [item.poster, item.media, isCarousel],
  );

  useImperativeHandle(ref, () => ({ togglePlay, toggleSound, step, flyOut }), [togglePlay, toggleSound, step, flyOut]);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!onSwipe || e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, .rv-seek")) return;
    start.current = { x: e.clientX, y: e.clientY, id: e.pointerId, t: e.timeStamp, width: e.currentTarget.offsetWidth };
    active.current = false;
    moved.current = false;
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const s = start.current;
    if (!s || e.pointerId !== s.id) return;
    const mx = e.clientX - s.x;
    const my = e.clientY - s.y;
    if (!active.current) {
      if (Math.abs(mx) > 10 && Math.abs(mx) > Math.abs(my) * 1.2) {
        active.current = true;
        moved.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        setDragging(true);
      } else if (Math.abs(my) > 12) {
        start.current = null; // la page défile : ce n'est pas un geste de décision
        return;
      } else return;
    }
    setDx(mx);
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>, cancelled = false) => {
    const s = start.current;
    start.current = null;
    if (!s || !active.current) return;
    active.current = false;
    setDragging(false);
    setDx(0);
    const mx = e.clientX - s.x;
    const speed = mx / Math.max(1, e.timeStamp - s.t); // px par ms
    const threshold = Math.min(120, s.width * 0.3);
    released.current = { dx: mx, at: performance.now() };
    if (cancelled || !onSwipe) return;
    if (mx > threshold || (speed > 0.6 && mx > SWIPE_MIN)) onSwipe("right");
    else if (mx < -threshold || (speed < -0.6 && mx < -SWIPE_MIN)) onSwipe("left");
  };
  const onClickCapture = (e: MouseEvent) => {
    if (moved.current) {
      moved.current = false;
      e.stopPropagation();
      e.preventDefault();
    }
  };

  const onMediaClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!isCarousel) return togglePlay();
    const r = e.currentTarget.getBoundingClientRect();
    step(e.clientX - r.left < r.width * 0.35 ? -1 : 1);
  };

  const strength = Math.min(1, Math.abs(dx) / 110);

  return (
    <div className="rv-card-slot">
      <div
        className={`rv-card ${dragging ? "dragging" : ""} ${enter ? (enter % 2 ? "in-a" : "in-b") : ""}`}
        style={dx ? { transform: `translateX(${dx}px) rotate(${dx * 0.03}deg)` } : undefined}
        role="group"
        aria-roledescription="vidéo à valider"
        aria-label={label}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(e) => endDrag(e)}
        onPointerCancel={(e) => endDrag(e, true)}
        onClickCapture={onClickCapture}
      >
        <div className="rv-media-box" onClick={onMediaClick}>
          {!url ? (
            <div className="rv-media-msg">
              <Icon icon={Alert02Icon} size={22} className="rv-ic-bad" />
              <span>Aucun fichier rendu pour ce contenu.</span>
            </div>
          ) : isCarousel ? (
            <img
              key={url}
              className="rv-media"
              src={url}
              alt={`Image ${index + 1} sur ${total}`}
              draggable={false}
              onLoad={() => setStatus("ready")}
              onError={() => setStatus("error")}
            />
          ) : (
            <video
              ref={video}
              className="rv-media"
              src={url}
              poster={item.poster ?? undefined}
              autoPlay
              muted={muted}
              loop
              playsInline
              preload="auto"
              aria-label="Lecture de la vidéo"
              onLoadedData={() => setStatus("ready")}
              onPlaying={() => {
                setStatus("ready");
                setBuffering(false);
                setPaused(false);
              }}
              onPlay={() => setPaused(false)}
              onPause={() => setPaused(true)}
              onWaiting={() => setBuffering(true)}
              onError={() => setStatus("error")}
            />
          )}

          {status === "error" ? (
            <div className="rv-media-msg" onClick={(e) => e.stopPropagation()}>
              <Icon icon={Alert02Icon} size={22} className="rv-ic-bad" />
              <strong>{isCarousel ? `L'image ${index + 1} ne se charge pas.` : "La vidéo ne se charge pas."}</strong>
              <span>Le serveur ne la renvoie pas pour l'instant. Réessayez ; si rien ne change, relancez la production.</span>
              <button className="btn sm" onClick={() => setAttempt((n) => n + 1)}>
                Réessayer
              </button>
            </div>
          ) : (
            (status === "loading" || (!isCarousel && buffering)) && (
              <span className="rv-spinner" aria-hidden>
                <Icon icon={Loading03Icon} size={22} />
              </span>
            )
          )}

          {!isCarousel && paused && status === "ready" && (
            <span className="rv-paused" aria-hidden>
              <Icon icon={PlayIcon} size={22} />
            </span>
          )}
        </div>

        {/* Repères par-dessus l'image : ce qui se règle et où l'on en est */}
        {isCarousel ? (
          <>
            <span className="rv-ov-chip num" aria-live="polite">
              {index + 1} / {total}
            </span>
            {total > 1 && (
              <>
                <button
                  className="rv-ov-btn rv-prev"
                  onClick={() => step(-1)}
                  disabled={index === 0}
                  aria-label="Image précédente"
                >
                  <Icon icon={ArrowLeft01Icon} />
                </button>
                <button
                  className="rv-ov-btn rv-next"
                  onClick={() => step(1)}
                  disabled={index === total - 1}
                  aria-label="Image suivante"
                >
                  <Icon icon={ArrowRight01Icon} />
                </button>
              </>
            )}
          </>
        ) : (
          <>
            <button
              className="rv-ov-btn rv-sound"
              onClick={toggleSound}
              aria-label={muted ? "Activer le son" : "Couper le son"}
              aria-pressed={!muted}
              title={muted ? "Activer le son (M)" : "Couper le son (M)"}
            >
              <Icon icon={muted ? VolumeOffIcon : VolumeHighIcon} />
            </button>
            <div className="rv-seek" onClick={seek} title="Aller à ce moment">
              <div className="rv-track">
                <div className="rv-progress" ref={bar} />
              </div>
            </div>
          </>
        )}

        {onSwipe && dx !== 0 && (
          <span className={`rv-swipe-label ${dx > 0 ? "keep" : "drop"}`} style={{ opacity: strength }} aria-hidden>
            {dx > 0 ? "Garder" : "Jeter"}
          </span>
        )}
      </div>

      {ghosts.map((g) => (
        <div key={g.id} className={`rv-ghost ${g.direction}`} style={{ ["--from" as string]: g.from }} aria-hidden>
          <img src={g.src} alt="" draggable={false} />
        </div>
      ))}
    </div>
  );
});
