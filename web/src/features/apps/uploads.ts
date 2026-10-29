import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { ApiError, uploadAsset, type AssetKind } from "./api";

/**
 * File d'envoi des fichiers, tenue hors de React : un envoi continue (et reste visible) quand on change
 * d'onglet ou qu'on revient à la liste. Deux fichiers à la fois, un fichier par requête (erreur par fichier).
 */

export type UploadState = "queued" | "sending" | "done" | "duplicate" | "error";

export type Upload = {
  key: string;
  appId: string;
  name: string;
  size: number;
  kind: AssetKind | null;
  progress: number;
  state: UploadState;
  error?: string;
  retryable?: boolean;
  file: File;
  abort?: () => void;
};

const PARALLEL = 2;
const IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif", "heic", "heif", "bmp", "tif", "tiff"];
const VIDEO_EXT = ["mov", "mp4", "m4v", "webm"];

let items: Upload[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const uploaded = new Set<(appId: string) => void>();
const emit = () => listeners.forEach((fn) => fn());

function patch(key: string, change: Partial<Upload>) {
  items = items.map((u) => (u.key === key ? { ...u, ...change } : u));
  emit();
}

function remove(key: string) {
  items = items.filter((u) => u.key !== key);
  emit();
}

/** Une image devient une capture, une vidéo une vidéo de démo : le back vérifie qu'elle est lisible. */
export function kindFor(file: File): AssetKind | null {
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  if (file.type.startsWith("image/") || IMAGE_EXT.includes(ext)) return "screenshot";
  if (file.type.startsWith("video/") || VIDEO_EXT.includes(ext)) return "demo_video";
  return null; // documents : le back décide (PDF, texte…)
}

function pump() {
  let active = items.filter((u) => u.state === "sending").length;
  for (const u of items) {
    if (active >= PARALLEL) break;
    if (u.state !== "queued") continue;
    active += 1;
    start(u);
  }
}

function start(u: Upload) {
  const { done, abort } = uploadAsset(u.appId, u.file, u.kind, (p) => patch(u.key, { progress: p }));
  patch(u.key, { state: "sending", progress: 0, abort });
  done
    .then(
      (res) => {
        const duplicate = res.created === 0 && res.duplicates > 0;
        patch(u.key, { state: duplicate ? "duplicate" : "done", progress: 1, abort: undefined });
        uploaded.forEach((fn) => fn(u.appId));
        window.setTimeout(() => remove(u.key), duplicate ? 6000 : 2500);
      },
      (e: ApiError) => {
        if (e.status === -1) remove(u.key);
        else patch(u.key, { state: "error", error: e.message, retryable: e.status === 0 || e.status >= 500, abort: undefined });
      },
    )
    .finally(pump);
}

export function enqueueUploads(appId: string, files: File[]) {
  if (!files.length) return;
  items = [
    ...items,
    ...files.map((file) => ({
      key: `u${(seq += 1)}`,
      appId,
      name: file.name,
      size: file.size,
      kind: kindFor(file),
      progress: 0,
      state: "queued" as const,
      file,
    })),
  ];
  emit();
  pump();
}

export function retryUpload(key: string) {
  patch(key, { state: "queued", error: undefined, progress: 0 });
  pump();
}

/** Annule un envoi en cours, ou retire une ligne terminée ou en erreur. */
export function dismissUpload(key: string) {
  items.find((u) => u.key === key)?.abort?.();
  remove(key);
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

/** Les envois de cette app ; `onUploaded` est appelé (regroupé) quand un fichier est arrivé. */
export function useUploads(appId: string, onUploaded: () => void): Upload[] {
  const all = useSyncExternalStore(subscribe, () => items);
  const ref = useRef(onUploaded);
  ref.current = onUploaded;
  useEffect(() => {
    let timer: number | undefined;
    const fn = (id: string) => {
      if (id !== appId) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => ref.current(), 300);
    };
    uploaded.add(fn);
    return () => {
      window.clearTimeout(timer);
      uploaded.delete(fn);
    };
  }, [appId]);
  return useMemo(() => all.filter((u) => u.appId === appId), [all, appId]);
}
