import type { CaseView } from "@/types/caseview";

/** The local demo API (`make api`). Live runs and live exports go here; cached mode never needs it. */
export const API_BASE = process.env.NEXT_PUBLIC_PAIR_API ?? "http://127.0.0.1:8000";
/** The hosted copy (Vercel) sets NEXT_PUBLIC_PAIR_API to "" so it never calls a local API. */
export const LIVE_AVAILABLE = API_BASE !== "";
export const LIVE_PREFIX = "live-";

export interface CaseRow {
  case_id: string;
  policy_id: string | null;
  policy_title: string | null;
  service: string | null;
  overall: string | null;
  files: Record<string, string>;
}

export interface Health {
  status: string;
  cache: { ok: boolean; cases: number };
  live: { enabled: boolean; reachable: boolean };
}

/** An error with a message that is safe to show to the patient. */
export class DataError extends Error {
  constructor(
    message: string,
    readonly code: string = "data_error",
  ) {
    super(message);
    this.name = "DataError";
  }
}

async function getJson<T>(url: string, missing: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new DataError(missing, response.status === 404 ? "not_found" : "http_error");
  return (await response.json()) as T;
}

/** The published demo cases (web/public/demo/index.json). */
export async function loadIndex(): Promise<CaseRow[]> {
  const index = await getJson<{ cases: CaseRow[] }>("/demo/index.json", "No demo cases are published.");
  return index.cases;
}

/** One cached CaseView. */
export function loadCachedView(caseId: string): Promise<CaseView> {
  return getJson<CaseView>(`/demo/views/${encodeURIComponent(caseId)}.json`, "We could not find this case.");
}

/** A cached letter file's URL. */
export function cachedFileUrl(caseId: string, fmt: "docx" | "pdf"): string {
  return `/demo/files/${encodeURIComponent(caseId)}.${fmt}`;
}

/** The API's health, or null if it isn't running. */
export async function apiHealth(timeoutMs = 2500): Promise<Health | null> {
  if (!LIVE_AVAILABLE) return null;
  try {
    const response = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(timeoutMs) });
    return response.ok ? ((await response.json()) as Health) : null;
  } catch {
    return null;
  }
}

async function apiError(response: Response): Promise<DataError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    if (body.error?.message) return new DataError(body.error.message, body.error.code ?? "api_error");
  } catch {
    /* not the error envelope */
  }
  return new DataError("The live checker failed. Try again, or use a demo case.", "api_error");
}

/** A file's bytes as base64, read in memory. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(new DataError(`We could not read ${file.name}.`, "read_failed"));
    reader.readAsDataURL(file);
  });
}

/** Run steps 1 to 7 on the patient's files through the local API. */
export async function runLive(
  denial: File,
  records: File[],
  context: Record<string, boolean | null> = {},
): Promise<{ view: CaseView; seconds: number }> {
  const body = {
    denial: { name: denial.name, data: await fileToBase64(denial) },
    documents: await Promise.all(records.map(async (f) => ({ name: f.name, data: await fileToBase64(f) }))),
    context,
  };
  const response = await fetch(`${API_BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await apiError(response);
  return { view: (await response.json()) as CaseView, seconds: Number(response.headers.get("X-Run-Seconds") ?? "0") };
}

/** The letter of a live CaseView as a file, rendered by the API. */
export async function exportLive(view: CaseView, fmt: "docx" | "pdf"): Promise<Blob> {
  const response = await fetch(`${API_BASE}/export/${fmt}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(view),
  });
  if (!response.ok) throw await apiError(response);
  return response.blob();
}
