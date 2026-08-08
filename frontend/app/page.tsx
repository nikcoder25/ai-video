"use client";

import { useCallback, useEffect, useState } from "react";
import { LandingView } from "@/components/LandingView";
import { ProcessingView } from "@/components/ProcessingView";
import { EmptyResults, ResultsView } from "@/components/ResultsView";
import { SiteHeader } from "@/components/SiteHeader";
import { useJobPolling } from "@/hooks/useJobPolling";
import type { Job } from "@/lib/api";

/**
 * The job id lives in the URL rather than in React state alone.
 *
 * A render takes minutes, and people reload, restore tabs and send links to
 * themselves. Holding the id only in memory means a refresh abandons a job
 * that is still running on the server, with no way to ever see its clips —
 * they exist, but nothing knows their id any more.
 */
const JOB_PARAM = "job";

function readJobFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(JOB_PARAM);
}

function writeJobToUrl(jobId: string | null): void {
  const url = new URL(window.location.href);
  if (jobId) {
    url.searchParams.set(JOB_PARAM, jobId);
  } else {
    url.searchParams.delete(JOB_PARAM);
  }
  window.history.replaceState(null, "", url.toString());
}

export default function Page() {
  const [jobId, setJobId] = useState<string | null>(null);
  /** The job as returned by POST /jobs — used until the first poll lands. */
  const [created, setCreated] = useState<Job | null>(null);
  // Rendering can't start until we know whether the URL names a job, or the
  // landing page would flash before the restored job replaced it.
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    setJobId(readJobFromUrl());
    setRestoring(false);
  }, []);

  const { job, clips, lastActiveStage, error, notFound, retry } = useJobPolling(jobId);

  const onCreated = useCallback((next: Job) => {
    setCreated(next);
    setJobId(next.id);
    writeJobToUrl(next.id);
  }, []);

  const reset = useCallback(() => {
    setCreated(null);
    setJobId(null);
    writeJobToUrl(null);
  }, []);

  // A link to a job that has since been deleted should land on the form, not
  // on an error about an id the visitor never typed.
  useEffect(() => {
    if (notFound) reset();
  }, [notFound, reset]);

  const current = job ?? created;
  // Restored from a URL: the id is known but the first poll hasn't landed.
  const awaitingFirstPoll = jobId !== null && current === null && !notFound;

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader onReset={current ? reset : undefined} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 sm:px-8">
        {restoring || awaitingFirstPoll ? (
          <p className="py-24 text-center text-sm text-fg-faint">Loading your job…</p>
        ) : !current ? (
          <LandingView onCreated={onCreated} />
        ) : current.status === "done" && clips !== null ? (
          clips.length > 0 ? (
            <ResultsView job={current} clips={clips} onReset={reset} />
          ) : (
            <EmptyResults job={current} onReset={reset} />
          )
        ) : (
          <ProcessingView
            job={current}
            lastActiveStage={lastActiveStage}
            pollError={error}
            onRetry={retry}
            onReset={reset}
          />
        )}
      </main>

      <footer className="mx-auto w-full max-w-6xl px-5 pt-10 pb-8 sm:px-8">
        <div className="rule mb-6" />
        <p className="text-xs text-fg-faint">
          ClipViral · 20–58s cuts · word-level captions · face-centered 9:16 crop
        </p>
      </footer>
    </div>
  );
}
