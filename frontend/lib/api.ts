/**
 * Typed client for the ClipViral backend. Every network call in the app goes
 * through this module so error shapes stay consistent.
 */

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"
).replace(/\/+$/, "");

export type JobStatus = "queued" | "running" | "done" | "failed";

export type JobStage =
  | "queued"
  | "downloading"
  | "transcribing"
  | "selecting"
  | "rendering"
  | "uploading"
  | "done"
  | "failed";

export interface Job {
  id: string;
  status: JobStatus;
  stage: JobStage;
  /** 0.0 - 1.0, monotonic */
  progress: number;
  source_title: string | null;
  source_url: string | null;
  /** seconds, null until probed */
  duration: number | null;
  clip_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Clip {
  id: string;
  job_id: string;
  title: string;
  /** 1 - 10 */
  hook_score: number;
  reason: string;
  /** seconds into the source */
  start: number;
  end: number;
  duration: number;
  /** relative ("/files/...") or absolute (presigned) */
  url: string;
  size_bytes: number;
  width: number;
  height: number;
  index: number;
}

export type ApiErrorKind = "network" | "http" | "parse" | "aborted";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(message: string, kind: ApiErrorKind, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }

  /** True when retrying later could plausibly work. */
  get retryable(): boolean {
    return this.kind === "network" || (this.status !== null && this.status >= 500);
  }
}

const UNREACHABLE = `Can't reach the ClipViral API at ${API_BASE}. Is the backend running?`;

function isAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/** FastAPI puts human-readable messages in `detail`. */
function extractDetail(body: string): string | null {
  if (!body) return null;
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const detail = (parsed as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const first = detail[0] as { msg?: unknown } | undefined;
        if (first && typeof first.msg === "string") return first.msg;
      }
      const message = (parsed as { message?: unknown }).message;
      if (typeof message === "string") return message;
    }
  } catch {
    // Not JSON — fall through and use the raw text if it is short enough.
  }
  const trimmed = body.trim();
  return trimmed.length > 0 && trimmed.length < 300 ? trimmed : null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (isAbort(error) || init?.signal?.aborted) {
      throw new ApiError("Request cancelled.", "aborted");
    }
    throw new ApiError(UNREACHABLE, "network");
  }

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = extractDetail(body);
    throw new ApiError(
      detail ?? `The API returned ${response.status} ${response.statusText}.`,
      "http",
      response.status,
    );
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The API returned a response we couldn't read.", "parse");
  }
}

export function createJobFromUrl(youtubeUrl: string, signal?: AbortSignal): Promise<Job> {
  return request<Job>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ youtube_url: youtubeUrl }),
    signal,
  });
}

export interface UploadOptions {
  /** Receives 0-1, or null when the browser can't measure the total. */
  onProgress?: (fraction: number | null) => void;
  signal?: AbortSignal;
}

/**
 * Uploads via XHR rather than fetch purely so we can report real upload
 * progress — fetch has no equivalent of `upload.onprogress`.
 */
export function createJobFromFile(file: File, options: UploadOptions = {}): Promise<Job> {
  const { onProgress, signal } = options;

  return new Promise<Job>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiError("Upload cancelled.", "aborted"));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs`);
    xhr.responseType = "text";

    const detach = () => signal?.removeEventListener("abort", onAbortSignal);
    const onAbortSignal = () => xhr.abort();
    signal?.addEventListener("abort", onAbortSignal);

    xhr.upload.addEventListener("progress", (event) => {
      if (!onProgress) return;
      onProgress(event.lengthComputable && event.total > 0 ? event.loaded / event.total : null);
    });

    xhr.addEventListener("load", () => {
      detach();
      const body = xhr.responseText ?? "";
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = extractDetail(body);
        reject(new ApiError(detail ?? `The API returned ${xhr.status}.`, "http", xhr.status));
        return;
      }
      try {
        resolve(JSON.parse(body) as Job);
      } catch {
        reject(new ApiError("The API returned a response we couldn't read.", "parse"));
      }
    });

    xhr.addEventListener("error", () => {
      detach();
      reject(new ApiError(UNREACHABLE, "network"));
    });

    xhr.addEventListener("timeout", () => {
      detach();
      reject(new ApiError("The upload timed out.", "network"));
    });

    xhr.addEventListener("abort", () => {
      detach();
      reject(new ApiError("Upload cancelled.", "aborted"));
    });

    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`, { signal, cache: "no-store" });
}

export function getClips(jobId: string, signal?: AbortSignal): Promise<Clip[]> {
  return request<Clip[]>(`/jobs/${encodeURIComponent(jobId)}/clips`, {
    signal,
    cache: "no-store",
  });
}

/**
 * Remove a job, its stored clips, and its server-side files. 409 while the
 * job is still running.
 */
export async function deleteJob(jobId: string, signal?: AbortSignal): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      signal,
    });
  } catch (error) {
    if (isAbort(error) || signal?.aborted) throw new ApiError("Request cancelled.", "aborted");
    throw new ApiError(UNREACHABLE, "network");
  }
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(
      extractDetail(body) ?? `The API returned ${response.status}.`,
      "http",
      response.status,
    );
  }
}

/** Clip URLs may be relative to the API host. */
export function resolveClipUrl(url: string): string {
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong.";
}
