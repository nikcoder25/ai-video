import { readFile } from "node:fs/promises";
import path from "node:path";
import { log } from "../logger";

/**
 * Where finished renders live. Local disk by default (served by the API);
 * Supabase Storage when SUPABASE_URL + SUPABASE_SERVICE_KEY are set.
 */
export interface Storage {
  /** Persist a finished file; returns a URL/path clients can use. */
  store(localPath: string, key: string): Promise<string>;
}

/** Files stay in the job dir; the API serves them at /jobs/:id/files/:name. */
export class LocalStorage implements Storage {
  async store(_localPath: string, key: string): Promise<string> {
    return `/jobs/${key}`; // API route serves straight from the job dir
  }
}

/** Uploads to a Supabase Storage bucket via the REST API (no SDK needed). */
export class SupabaseStorage implements Storage {
  constructor(
    private url: string,
    private serviceKey: string,
    private bucket: string,
  ) {}

  async store(localPath: string, key: string): Promise<string> {
    const body = await readFile(localPath);
    const contentType = localPath.endsWith(".mp4")
      ? "video/mp4"
      : localPath.endsWith(".json")
        ? "application/json"
        : "application/octet-stream";

    const endpoint = `${this.url}/storage/v1/object/${this.bucket}/${key}`;
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.serviceKey}`,
        "content-type": contentType,
        "x-upsert": "true",
      },
      body,
    });
    if (!res.ok) {
      throw new Error(`Supabase upload ${res.status}: ${await res.text().catch(() => "")}`);
    }
    log.ok(`uploaded ${key} to Supabase`);
    return `${this.url}/storage/v1/object/public/${this.bucket}/${key}`;
  }
}

export function createStorage(): Storage {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  const bucket = process.env.SUPABASE_BUCKET ?? "renders";
  if (url && key) {
    log.info(`storage: Supabase bucket "${bucket}"`);
    return new SupabaseStorage(url, key, bucket);
  }
  return new LocalStorage();
}

/** Storage key for a job artifact, e.g. `jobs/<id>/ad-1.mp4`. */
export function artifactKey(jobId: string, filename: string): string {
  return path.posix.join(jobId, filename);
}
