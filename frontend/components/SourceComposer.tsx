"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createJobFromFile, createJobFromUrl, messageFor, type Job } from "@/lib/api";
import { fileSize, percent } from "@/lib/format";
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_EXTENSIONS,
  MAX_UPLOAD_LABEL,
  normalizeYouTubeUrl,
  validateVideoFile,
} from "@/lib/source";
import { Alert } from "./Alert";
import { ArrowRightIcon, CloseIcon, FilmIcon, LinkIcon, SpinnerIcon, UploadIcon } from "./Icons";

type Submission =
  | { kind: "idle" }
  | { kind: "url" }
  | { kind: "file"; fraction: number | null };

export function SourceComposer({ onCreated }: { onCreated: (job: Job) => void }) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submission, setSubmission] = useState<Submission>({ kind: "idle" });

  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const dragDepth = useRef(0);

  const busy = submission.kind !== "idle";

  useEffect(() => () => abortRef.current?.abort(), []);

  const acceptFile = useCallback((candidate: File) => {
    const problem = validateVideoFile(candidate);
    if (problem) {
      setError(problem);
      setFile(null);
      return;
    }
    setError(null);
    setUrl("");
    setFile(candidate);
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLFormElement>) => {
      event.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      if (busy) return;
      const dropped = event.dataTransfer.files?.[0];
      if (dropped) acceptFile(dropped);
    },
    [acceptFile, busy],
  );

  const onDragEnter = useCallback(
    (event: React.DragEvent<HTMLFormElement>) => {
      if (busy) return;
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      dragDepth.current += 1;
      setDragging(true);
    },
    [busy],
  );

  const onDragLeave = useCallback(() => {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      if (file) {
        setError(null);
        setSubmission({ kind: "file", fraction: 0 });
        const job = await createJobFromFile(file, {
          signal: controller.signal,
          onProgress: (fraction) => setSubmission({ kind: "file", fraction }),
        });
        onCreated(job);
        return;
      }

      const normalized = normalizeYouTubeUrl(url);
      if (!normalized) {
        setError(
          url.trim().length === 0
            ? "Paste a YouTube link, or drop a video file below."
            : "That doesn't look like a YouTube video link. Try a youtube.com/watch, /shorts or youtu.be URL.",
        );
        return;
      }

      setError(null);
      setSubmission({ kind: "url" });
      const job = await createJobFromUrl(normalized, controller.signal);
      onCreated(job);
    } catch (caught) {
      setError(messageFor(caught));
      setSubmission({ kind: "idle" });
    }
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={submit}
        onDrop={onDrop}
        onDragOver={(event) => event.preventDefault()}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        className={`relative rounded-2xl border bg-surface/85 p-2 transition-colors duration-200 ${
          dragging ? "border-flame/70" : "border-line hover:border-line/80"
        }`}
      >
        {/* URL row */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <LinkIcon className="pointer-events-none absolute top-1/2 left-3.5 h-[18px] w-[18px] -translate-y-1/2 text-fg-faint" />
            <input
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={url}
              disabled={busy || file !== null}
              onChange={(event) => {
                setUrl(event.target.value);
                if (error) setError(null);
              }}
              placeholder="Paste a YouTube link"
              aria-label="YouTube video URL"
              className="h-12 w-full rounded-xl bg-surface-2/70 pr-4 pl-11 text-[0.95rem] text-fg placeholder:text-fg-faint focus:outline-none disabled:opacity-40 sm:bg-transparent"
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            className="group inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-flame px-5 text-[0.95rem] font-semibold text-[#150703] transition-all duration-200 hover:bg-flame-bright active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? (
              <SpinnerIcon className="anim-spin h-[18px] w-[18px]" />
            ) : (
              <>
                {file ? "Generate clips" : "Find clips"}
                <ArrowRightIcon className="h-[18px] w-[18px] transition-transform duration-200 group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </div>

        {/* File row */}
        <div className="mt-2">
          {file ? (
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-2/60 px-3.5 py-3">
              <FilmIcon className="h-[18px] w-[18px] shrink-0 text-flame" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-fg">{file.name}</p>
                <p className="numeric text-xs text-fg-faint">{fileSize(file.size)}</p>
              </div>
              {!busy ? (
                <button
                  type="button"
                  onClick={() => setFile(null)}
                  className="rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-surface-3 hover:text-fg"
                  aria-label="Remove file"
                >
                  <CloseIcon className="h-4 w-4" />
                </button>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
              className="flex w-full items-center gap-3 rounded-xl border border-dashed border-line px-3.5 py-3.5 text-left transition-colors duration-200 hover:border-flame/45 hover:bg-surface-2/50 disabled:opacity-50"
            >
              <UploadIcon className="h-[18px] w-[18px] shrink-0 text-fg-faint" />
              <span className="min-w-0 flex-1 text-sm text-fg-muted">
                Drop a video file here, or{" "}
                <span className="font-medium text-fg underline decoration-line underline-offset-4">
                  browse
                </span>
              </span>
              <span className="hidden shrink-0 text-xs text-fg-faint sm:block">
                {ACCEPTED_EXTENSIONS.join(" · ")} up to {MAX_UPLOAD_LABEL}
              </span>
            </button>
          )}
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          className="sr-only"
          tabIndex={-1}
          onChange={(event) => {
            const chosen = event.target.files?.[0];
            if (chosen) acceptFile(chosen);
            event.target.value = "";
          }}
        />

        {dragging ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border-2 border-dashed border-flame/70 bg-canvas/85">
            <span className="text-sm font-medium text-flame">Drop to upload</span>
          </div>
        ) : null}
      </form>

      {busy ? <SubmitProgress submission={submission} /> : null}
      {error ? <Alert>{error}</Alert> : null}
    </div>
  );
}

function SubmitProgress({ submission }: { submission: Submission }) {
  if (submission.kind === "url") {
    return (
      <p className="numeric px-1 text-xs text-fg-muted">
        <span className="anim-blink">Creating job…</span>
      </p>
    );
  }
  if (submission.kind !== "file") return null;

  const determinate = submission.fraction !== null;
  const value = determinate ? percent(submission.fraction ?? 0) : null;

  return (
    <div className="px-1">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-xs text-fg-muted">
          {determinate ? "Uploading" : "Uploading — size unknown"}
        </span>
        <span className="numeric text-xs text-fg">
          {determinate ? `${value}%` : <span className="anim-blink">in progress</span>}
        </span>
      </div>
      <div className="relative h-1 overflow-hidden rounded-full bg-surface-3">
        {determinate ? (
          <div
            className="h-full rounded-full bg-flame transition-[width] duration-200 ease-out"
            style={{ width: `${value}%` }}
          />
        ) : (
          <div className="anim-sheen absolute inset-y-0 w-1/3 rounded-full bg-flame/70" />
        )}
      </div>
    </div>
  );
}
