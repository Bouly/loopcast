export type Problem = { code: string; message: string };

export type Phone = {
  udid: string | null;
  phone_id: string | null;
  name: string;
  model: string;
  model_name: string;
  ios: string;
  connection: string | null;
  status: "ok" | "attention" | "offline" | "unknown" | "never_seen";
  problems: Problem[];
  battery: number | null;
  charging: number | null;
  session_id: string | null;
  owner: string;
  last_seen: string | null;
  screen_etag: string | null;
};

export type LogEvent = { id?: number; at?: string; phone_udid?: string | null; kind: string; message: string };

export type Size = { width: number; height: number };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { detail?: string }).detail ?? `Erreur ${r.status}`);
  return data as T;
}

const phone = (udid: string) => `/api/phones/${encodeURIComponent(udid)}`;

export const api = {
  phones: () => call<Phone[]>("GET", "/api/phones"),
  events: (limit = 80) => call<LogEvent[]>("GET", `/api/events?limit=${limit}`),
  refresh: () => call<{ seen: number }>("POST", "/api/farm/refresh"),
  take: (udid: string) => call<{ session_id: string; size: Size }>("POST", `${phone(udid)}/session`),
  release: (udid: string) => call("DELETE", `${phone(udid)}/session`),
  size: (udid: string) => call<Size>("GET", `${phone(udid)}/size`),
  tap: (udid: string, x: number, y: number) => call("POST", `${phone(udid)}/tap`, { x, y }),
  swipe: (udid: string, x1: number, y1: number, x2: number, y2: number, duration_ms: number) =>
    call("POST", `${phone(udid)}/swipe`, { x1, y1, x2, y2, duration_ms }),
  type: (udid: string, text: string) => call("POST", `${phone(udid)}/type`, { text }),
  button: (udid: string, name: string) => call("POST", `${phone(udid)}/button`, { name }),
  launch: (udid: string, app: string) => call("POST", `${phone(udid)}/launch`, { app }),
  screenshotUrl: (udid: string, etag: string | null) => `${phone(udid)}/screenshot?v=${etag ?? "0"}`,
  streamUrl: (udid: string, nonce: number) => `${phone(udid)}/stream?n=${nonce}`,
};
