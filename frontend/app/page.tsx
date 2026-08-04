"use client";

import { useCallback, useState } from "react";
import { LandingView } from "@/components/LandingView";
import { ProcessingView } from "@/components/ProcessingView";
import { EmptyResults, ResultsView } from "@/components/ResultsView";
import { SiteHeader } from "@/components/SiteHeader";
import { useJobPolling } from "@/hooks/useJobPolling";
import type { Job } from "@/lib/api";

export default function Page() {
  /** The job as returned by POST /jobs — used until the first poll lands. */
  const [created, setCreated] = useState<Job | null>(null);
  const { job, clips, lastActiveStage, error, retry } = useJobPolling(created?.id ?? null);

  const current = job ?? created;

  const reset = useCallback(() => setCreated(null), []);

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader onReset={current ? reset : undefined} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 sm:px-8">
        {!current ? (
          <LandingView onCreated={setCreated} />
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
