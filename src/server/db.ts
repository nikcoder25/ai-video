import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { JobInput } from "../pipeline/run";

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface JobRow {
  id: string;
  status: JobStatus;
  input: JobInput;
  progress: string | null;
  error: string | null;
  /** Populated on completion: per-ad hook + file names. */
  results: { index: number; hook: string; video: string | null; props: string }[] | null;
  created_at: string;
  updated_at: string;
}

/**
 * SQLite-backed job store using Node's built-in driver (no native deps).
 * Single-writer usage: the API process owns the DB and runs the queue loop.
 */
export class JobStore {
  private db: DatabaseSync;

  constructor(dataDir: string) {
    mkdirSync(dataDir, { recursive: true });
    this.db = new DatabaseSync(path.join(dataDir, "jobs.db"));
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'queued',
        input TEXT NOT NULL,
        progress TEXT,
        error TEXT,
        results TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
    `);
  }

  create(input: JobInput): JobRow {
    const id = randomUUID();
    this.db
      .prepare("INSERT INTO jobs (id, input) VALUES (?, ?)")
      .run(id, JSON.stringify(input));
    return this.get(id)!;
  }

  get(id: string): JobRow | null {
    const row = this.db.prepare("SELECT * FROM jobs WHERE id = ?").get(id) as
      | Record<string, unknown>
      | undefined;
    return row ? hydrate(row) : null;
  }

  list(limit = 50): JobRow[] {
    const rows = this.db
      .prepare("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?")
      .all(limit) as Record<string, unknown>[];
    return rows.map(hydrate);
  }

  /** Atomically claim the oldest queued job (single-process queue). */
  claimNext(): JobRow | null {
    const row = this.db
      .prepare(
        `UPDATE jobs SET status = 'running', updated_at = datetime('now')
         WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1)
         RETURNING *`,
      )
      .get() as Record<string, unknown> | undefined;
    return row ? hydrate(row) : null;
  }

  setProgress(id: string, progress: string): void {
    this.db
      .prepare("UPDATE jobs SET progress = ?, updated_at = datetime('now') WHERE id = ?")
      .run(progress, id);
  }

  complete(id: string, results: NonNullable<JobRow["results"]>): void {
    this.db
      .prepare(
        `UPDATE jobs SET status = 'completed', results = ?, progress = 'done',
         updated_at = datetime('now') WHERE id = ?`,
      )
      .run(JSON.stringify(results), id);
  }

  fail(id: string, error: string): void {
    this.db
      .prepare(
        `UPDATE jobs SET status = 'failed', error = ?, updated_at = datetime('now')
         WHERE id = ?`,
      )
      .run(error.slice(0, 2000), id);
  }

  /** Re-queue jobs left 'running' by a crashed process (call on boot). */
  recoverStale(): number {
    const res = this.db
      .prepare(`UPDATE jobs SET status = 'queued', progress = 'recovered' WHERE status = 'running'`)
      .run();
    return Number(res.changes);
  }

  close(): void {
    this.db.close();
  }
}

function hydrate(row: Record<string, unknown>): JobRow {
  return {
    id: String(row.id),
    status: row.status as JobStatus,
    input: JSON.parse(String(row.input)) as JobInput,
    progress: (row.progress as string | null) ?? null,
    error: (row.error as string | null) ?? null,
    results: row.results ? (JSON.parse(String(row.results)) as JobRow["results"]) : null,
    created_at: String(row.created_at),
    updated_at: String(row.updated_at),
  };
}
