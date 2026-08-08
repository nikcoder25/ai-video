"use client";

import { useState } from "react";
import { deleteJob, messageFor, type Clip, type Job } from "@/lib/api";
import { humanDuration } from "@/lib/format";
import { ClipCard } from "./ClipCard";
import { ArrowRightIcon, FilmIcon, TrashIcon } from "./Icons";

export function ResultsView({
  job,
  clips,
  onReset,
}: {
  job: Job;
  clips: Clip[];
  onReset: () => void;
}) {
  const best = clips[0];
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async () => {
    if (!confirming) {
      // Two-step: first click arms, second click deletes. Cheaper than a
      // modal and still impossible to trigger by accident.
      setConfirming(true);
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteJob(job.id);
      onReset();
    } catch (caught) {
      setDeleteError(messageFor(caught));
      setDeleting(false);
      setConfirming(false);
    }
  };

  return (
    <div className="anim-view py-12 lg:py-16">
      <header className="flex flex-col gap-6 border-b border-line-soft pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="eyebrow mb-3 flex items-center gap-2.5 text-fg-faint">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-flame" />
            {clips.length} {clips.length === 1 ? "clip" : "clips"} ready
          </p>

          <h1 className="display text-[2rem] text-fg sm:text-[2.5rem]">
            {clips.length === 1 ? "One cut made it." : `${clips.length} cuts made it.`}
          </h1>

          <p className="mt-3 max-w-xl truncate text-sm text-fg-muted">
            {job.source_title ?? "Your video"}
            {job.duration !== null ? ` · ${humanDuration(job.duration)} source` : ""}
            {best ? ` · top hook ${best.hook_score}/10` : ""}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={handleDelete}
              onBlur={() => setConfirming(false)}
              disabled={deleting}
              aria-label={confirming ? "Confirm delete" : "Delete this job and its clips"}
              className={`inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-medium transition-all duration-200 disabled:opacity-50 ${
                confirming
                  ? "border-red-500/60 bg-red-500/10 text-red-300 hover:bg-red-500/20"
                  : "border-line bg-surface-2 text-fg-muted hover:border-line hover:text-fg"
              }`}
            >
              <TrashIcon className="h-4 w-4" />
              {deleting ? "Deleting…" : confirming ? "Really delete?" : "Delete job"}
            </button>

            <button
              type="button"
              onClick={onReset}
              className="group inline-flex h-11 items-center gap-2 rounded-xl border border-line bg-surface-2 px-5 text-sm font-medium text-fg transition-all duration-200 hover:border-flame/50 hover:bg-surface-3"
            >
              Start another
              <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </button>
          </div>

          {deleteError ? <p className="text-xs text-red-400">{deleteError}</p> : null}
        </div>
      </header>

      <p className="eyebrow mt-8 mb-6 text-fg-faint">Sorted by hook score</p>

      <div className="grid grid-cols-1 gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {clips.map((clip, index) => (
          <ClipCard key={clip.id} clip={clip} position={index} />
        ))}
      </div>
    </div>
  );
}

export function EmptyResults({ job, onReset }: { job: Job; onReset: () => void }) {
  return (
    <div className="anim-view py-20 lg:py-28">
      <div className="max-w-xl">
        <div className="mb-7 flex h-12 w-12 items-center justify-center rounded-xl border border-line bg-surface-2 text-fg-faint">
          <FilmIcon className="h-5 w-5" />
        </div>

        <h1 className="display text-[2rem] text-fg sm:text-[2.5rem]">
          Nothing cleared the bar.
        </h1>

        <p className="mt-4 leading-relaxed text-fg-muted">
          The pipeline finished{job.duration !== null ? ` on ${humanDuration(job.duration)} of source` : ""},
          but no segment scored high enough to be worth cutting. That usually means the audio was
          quiet or unstructured — long silences, music beds, or overlapping speakers.
        </p>

        <p className="mt-3 text-sm leading-relaxed text-fg-faint">
          Try a video with clear single-speaker talking, or a longer source with more to choose
          from.
        </p>

        <button
          type="button"
          onClick={onReset}
          className="group mt-8 inline-flex h-11 items-center gap-2 rounded-xl bg-flame px-5 text-sm font-semibold text-[#150703] transition-colors duration-200 hover:bg-flame-bright"
        >
          Try another video
          <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
        </button>
      </div>
    </div>
  );
}
