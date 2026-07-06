import path from "node:path";
import { log } from "../logger";
import { runJob } from "../pipeline/run";
import { artifactKey, type Storage } from "../storage/index";
import type { JobStore } from "./db";

/**
 * In-process queue worker: polls the job store, claims one job at a time
 * (renders are CPU-bound — no parallel renders on a small VPS), runs the
 * pipeline, uploads artifacts. Swap for Upstash/BullMQ when going multi-node.
 */
export function startQueue(opts: {
  store: JobStore;
  storage: Storage;
  dataDir: string;
  pollMs?: number;
}): { stop: () => void } {
  const { store, storage, dataDir, pollMs = 1500 } = opts;
  let running = false;
  let stopped = false;

  const recovered = store.recoverStale();
  if (recovered > 0) log.warn(`re-queued ${recovered} stale running job(s)`);

  const tick = async (): Promise<void> => {
    if (running || stopped) return;
    const job = store.claimNext();
    if (!job) return;
    running = true;
    log.step(`Queue: job ${job.id}`);

    try {
      const jobDir = path.join(dataDir, "jobs", job.id);
      const result = await runJob(job.id, job.input, jobDir, (stage, detail) => {
        store.setProgress(job.id, detail ? `${stage}: ${detail}` : stage);
      });

      store.setProgress(job.id, "uploading");
      const results: { index: number; hook: string; video: string | null; props: string }[] = [];
      for (const ad of result.ads) {
        const propsUrl = await storage.store(
          ad.propsPath,
          artifactKey(job.id, path.basename(ad.propsPath)),
        );
        let videoUrl: string | null = null;
        if (ad.videoPath) {
          videoUrl = await storage.store(
            ad.videoPath,
            artifactKey(job.id, path.basename(ad.videoPath)),
          );
        }
        results.push({ index: ad.index, hook: ad.hook, video: videoUrl, props: propsUrl });
      }

      store.complete(job.id, results);
      log.ok(`job ${job.id} completed (${results.length} ads)`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      store.fail(job.id, msg);
      log.error(`job ${job.id} failed: ${msg}`);
    } finally {
      running = false;
    }
  };

  const interval = setInterval(() => void tick(), pollMs);
  void tick();

  return {
    stop: () => {
      stopped = true;
      clearInterval(interval);
    },
  };
}
