import Fastify from "fastify";
import multipart from "@fastify/multipart";
import { createReadStream, existsSync, statSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { config } from "../config";
import { log } from "../logger";
import { createStorage } from "../storage/index";
import { JobStore } from "./db";
import { startQueue } from "./queue";

const DATA_DIR = path.resolve(process.env.DATA_DIR ?? "data");
const PORT = Number(process.env.PORT ?? 8787);

const JobInputSchema = z
  .object({
    url: z.string().url().optional(),
    title: z.string().min(1).max(200).optional(),
    description: z.string().max(2000).optional(),
    price: z.string().max(50).optional(),
    photos: z.array(z.string()).max(10).optional(),
    music: z.string().optional(),
    bpm: z.number().int().min(40).max(220).optional(),
    render: z.boolean().optional(),
  })
  .refine((v) => v.url || v.title, { message: "Provide `url` or `title`" });

async function main(): Promise<void> {
  const store = new JobStore(DATA_DIR);
  const storage = createStorage();
  const queue = startQueue({ store, storage, dataDir: DATA_DIR });

  const app = Fastify({ logger: false });
  await app.register(multipart, {
    limits: { fileSize: 60 * 1024 * 1024, files: 1 },
  });

  app.get("/health", async () => ({
    ok: true,
    mock: config.mock,
    time: new Date().toISOString(),
  }));

  // Dashboard.
  const webDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "web");
  app.get("/", async (_req, reply) => {
    const html = await readFile(path.join(webDir, "index.html"), "utf8");
    reply.header("content-type", "text/html; charset=utf-8");
    return reply.send(html);
  });

  // Photo/clip/music upload (multipart, one file per request).
  const ALLOWED_EXT = new Set([".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mp3", ".wav"]);
  app.post("/uploads", async (req, reply) => {
    const part = await req.file();
    if (!part) return reply.code(400).send({ error: "no file" });
    const ext = path.extname(part.filename ?? "").toLowerCase();
    if (!ALLOWED_EXT.has(ext)) {
      return reply.code(400).send({ error: `unsupported file type "${ext}"` });
    }
    const dir = path.join(DATA_DIR, "uploads");
    await mkdir(dir, { recursive: true });
    const dest = path.join(dir, `${randomUUID()}${ext}`);
    await writeFile(dest, await part.toBuffer());
    log.info(`upload → ${dest}`);
    return reply.code(201).send({ path: dest });
  });

  // Submit a job: { url } or { title, photos: [paths from /uploads] }.
  app.post("/jobs", async (req, reply) => {
    const parsed = JobInputSchema.safeParse(req.body);
    if (!parsed.success) {
      return reply.code(400).send({ error: parsed.error.issues[0]?.message ?? "invalid body" });
    }
    // photos/music must point inside the uploads dir — never arbitrary
    // server paths (they get copied into the served public dir).
    const uploadsDir = path.join(DATA_DIR, "uploads") + path.sep;
    const mediaPaths = [...(parsed.data.photos ?? []), parsed.data.music].filter(
      (p): p is string => Boolean(p),
    );
    for (const p of mediaPaths) {
      if (!path.resolve(p).startsWith(uploadsDir)) {
        return reply.code(400).send({ error: "media paths must come from /uploads" });
      }
    }
    const job = store.create(parsed.data);
    log.info(`job ${job.id} queued (${parsed.data.url ?? parsed.data.title})`);
    return reply.code(201).send(publicJob(job));
  });

  app.get("/jobs", async () => store.list().map(publicJob));

  app.get<{ Params: { id: string } }>("/jobs/:id", async (req, reply) => {
    const job = store.get(req.params.id);
    if (!job) return reply.code(404).send({ error: "job not found" });
    return publicJob(job);
  });

  // Serve finished artifacts from the local job dir (LocalStorage mode).
  app.get<{ Params: { id: string; name: string } }>(
    "/jobs/:id/files/:name",
    async (req, reply) => {
      const { id, name } = req.params;
      // Only expect our own artifact names; block traversal.
      if (!/^[\w.-]+$/.test(name) || name.includes("..")) {
        return reply.code(400).send({ error: "bad filename" });
      }
      const job = store.get(id);
      if (!job) return reply.code(404).send({ error: "job not found" });
      const filePath = path.join(DATA_DIR, "jobs", id, name);
      if (!existsSync(filePath) || !statSync(filePath).isFile()) {
        return reply.code(404).send({ error: "file not found" });
      }
      const type = name.endsWith(".mp4")
        ? "video/mp4"
        : name.endsWith(".json")
          ? "application/json"
          : "application/octet-stream";
      reply.header("content-type", type);
      return reply.send(createReadStream(filePath));
    },
  );

  const close = async (): Promise<void> => {
    queue.stop();
    await app.close();
    store.close();
    process.exit(0);
  };
  process.on("SIGINT", () => void close());
  process.on("SIGTERM", () => void close());

  await app.listen({ port: PORT, host: "0.0.0.0" });
  log.step(`API listening on :${PORT}${config.mock ? " (MOCK mode)" : ""}`);
  log.info(`POST /jobs {"url": "..."} → GET /jobs/:id → download at results[].video`);
}

function publicJob(job: ReturnType<JobStore["create"]>) {
  return {
    id: job.id,
    title: job.input.title ?? job.input.url ?? job.id.slice(0, 8),
    status: job.status,
    progress: job.progress,
    error: job.error,
    results: job.results?.map((r) => ({
      index: r.index,
      hook: r.hook,
      // LocalStorage returns "/jobs/<id>/<name>" → rewrite to the file route.
      video: r.video?.startsWith("/jobs/")
        ? `/jobs/${job.id}/files/${path.posix.basename(r.video)}`
        : r.video,
      props: r.props.startsWith("/jobs/")
        ? `/jobs/${job.id}/files/${path.posix.basename(r.props)}`
        : r.props,
    })),
    created_at: job.created_at,
    updated_at: job.updated_at,
  };
}

main().catch((err) => {
  log.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
