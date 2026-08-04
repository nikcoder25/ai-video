"use client";

import { useElapsed } from "@/hooks/useElapsed";
import type { Job, JobStage } from "@/lib/api";
import { humanDuration, stopwatch } from "@/lib/format";
import { stageHeadline, stepStates } from "@/lib/stages";
import { Alert } from "./Alert";
import { ClockIcon, SpinnerIcon } from "./Icons";
import { ProgressBar } from "./ProgressBar";
import { StepList } from "./StepList";

export function ProcessingView({
  job,
  lastActiveStage,
  pollError,
  onRetry,
  onReset,
}: {
  job: Job;
  lastActiveStage: JobStage | null;
  pollError: string | null;
  onRetry: () => void;
  onReset: () => void;
}) {
  const failed = job.status === "failed" || job.stage === "failed";
  const finished = job.status === "done";
  const running = !failed && !finished && pollError === null;

  const elapsed = useElapsed(job.created_at, running);
  const states = stepStates(job, lastActiveStage);

  return (
    <div className="anim-view py-14 lg:py-20">
      <div className="grid gap-12 lg:grid-cols-12 lg:gap-14">
        <div className="lg:col-span-7">
          <p className="eyebrow mb-4 flex items-center gap-2.5 text-fg-faint">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                failed ? "bg-danger" : "bg-flame"
              } ${running ? "anim-blink" : ""}`}
            />
            {failed ? "Job failed" : finished ? "Complete" : "Working"}
          </p>

          <h1 className="display text-[2rem] text-fg sm:text-[2.5rem]">{stageHeadline(job)}</h1>

          {job.source_title ? (
            <p className="mt-3 max-w-lg truncate text-sm text-fg-muted">{job.source_title}</p>
          ) : null}

          <div className="mt-10 max-w-lg">
            <ProgressBar
              value={job.progress}
              active={running}
              tone={failed ? "danger" : "flame"}
            />
          </div>

          <div className="mt-12">
            <StepList states={states} />
          </div>

          {finished ? (
            <p className="mt-8 flex items-center gap-2 text-sm text-fg-muted">
              <SpinnerIcon className="anim-spin h-4 w-4 text-flame" />
              Collecting your clips…
            </p>
          ) : null}

          {failed ? (
            <div className="mt-9 max-w-lg space-y-4">
              <Alert title="The pipeline stopped">
                {job.error ?? "The backend didn't say why. Check the server logs for this job id."}
              </Alert>
              <button
                type="button"
                onClick={onReset}
                className="inline-flex h-11 items-center rounded-xl bg-flame px-5 text-sm font-semibold text-[#150703] transition-colors hover:bg-flame-bright"
              >
                Start over
              </button>
            </div>
          ) : null}

          {pollError && !failed ? (
            <div className="mt-9 max-w-lg">
              <Alert
                title="Lost contact with the API"
                action={
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={onRetry}
                      className="inline-flex h-9 items-center rounded-lg border border-line bg-surface-2 px-3.5 text-sm font-medium text-fg transition-colors hover:border-flame/50"
                    >
                      Resume polling
                    </button>
                    <button
                      type="button"
                      onClick={onReset}
                      className="inline-flex h-9 items-center rounded-lg px-3 text-sm text-fg-muted transition-colors hover:text-fg"
                    >
                      Start over
                    </button>
                  </div>
                }
              >
                {pollError} The job is probably still running on the server.
              </Alert>
            </div>
          ) : null}
        </div>

        <aside className="lg:col-span-5">
          <div className="rounded-2xl border border-line bg-surface/70 p-6 lg:sticky lg:top-10">
            <div className="flex items-center gap-2 text-fg-faint">
              <ClockIcon className="h-4 w-4" />
              <span className="eyebrow">Elapsed</span>
            </div>
            <p className="numeric mt-2 text-4xl font-medium text-fg">{stopwatch(elapsed)}</p>

            <div className="rule my-6" />

            <dl className="space-y-4 text-sm">
              <Row label="Source">
                {job.duration !== null ? humanDuration(job.duration) : "measuring…"}
              </Row>
              <Row label="Clips found">
                <span className="numeric">{job.clip_count}</span>
              </Row>
              <Row label="Status">
                <span className={failed ? "text-danger" : "text-fg"}>{job.status}</span>
              </Row>
              <Row label="Job">
                <span className="numeric text-xs text-fg-muted">{job.id.slice(0, 12)}</span>
              </Row>
            </dl>

            <p className="mt-6 text-xs leading-relaxed text-fg-faint">
              Rendering is the slow part — a 60 minute source usually takes a few minutes. You can
              leave this tab open.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-fg-faint">{label}</dt>
      <dd className="text-right text-fg">{children}</dd>
    </div>
  );
}
