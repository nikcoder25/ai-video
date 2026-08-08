"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getClips,
  getJob,
  messageFor,
  type Clip,
  type Job,
  type JobStage,
} from "@/lib/api";

const POLL_INTERVAL_MS = 3000;
/** Tolerate transient blips; surface an error once it looks persistent. */
const MAX_CONSECUTIVE_FAILURES = 3;

export interface JobPollingState {
  job: Job | null;
  /** null until the job reaches `done` and the clips have been fetched. */
  clips: Clip[] | null;
  /** Last stage seen before a failure, so the step list can point at it. */
  lastActiveStage: JobStage | null;
  error: string | null;
  /** The job id doesn't exist any more — deleted, or from an older database. */
  notFound: boolean;
  retry: () => void;
}

function byHookScore(a: Clip, b: Clip): number {
  return b.hook_score - a.hook_score || a.index - b.index;
}

/**
 * Polls `GET /jobs/{id}` on a `setTimeout` chain (never `setInterval`, so a
 * slow response can't stack requests), stops on `done` / `failed`, and tears
 * the loop down — including any in-flight request — on unmount or id change.
 */
export function useJobPolling(jobId: string | null): JobPollingState {
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const lastActiveStage = useRef<JobStage | null>(null);

  const retry = useCallback(() => {
    setError(null);
    setNotFound(false);
    setAttempt((value) => value + 1);
  }, []);

  // Anything we know about a previous job is stale the moment the id changes.
  useEffect(() => {
    setJob(null);
    setClips(null);
    setError(null);
    setNotFound(false);
    lastActiveStage.current = null;
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    const controller = new AbortController();

    const poll = async (): Promise<void> => {
      try {
        const next = await getJob(jobId, controller.signal);
        if (cancelled) return;

        failures = 0;
        setJob(next);
        setError(null);

        if (next.stage !== "failed" && next.stage !== "done" && next.stage !== "queued") {
          lastActiveStage.current = next.stage;
        }

        if (next.status === "failed") return; // terminal — stop polling

        if (next.status === "done") {
          const fetched = await getClips(jobId, controller.signal);
          if (cancelled) return;
          setClips([...fetched].sort(byHookScore));
          return; // terminal — stop polling
        }
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.kind === "aborted") return;

        // A 404 is settled, not flaky. Retrying it two more times just delays
        // telling the caller that this id is gone.
        if (caught instanceof ApiError && caught.status === 404) {
          setNotFound(true);
          return;
        }

        failures += 1;
        if (failures >= MAX_CONSECUTIVE_FAILURES) {
          setError(messageFor(caught));
          return; // stop; the user can retry explicitly
        }
      }

      if (cancelled) return;
      timer = setTimeout(() => {
        void poll();
      }, POLL_INTERVAL_MS);
    };

    void poll();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== null) clearTimeout(timer);
    };
  }, [jobId, attempt]);

  return { job, clips, lastActiveStage: lastActiveStage.current, error, notFound, retry };
}
