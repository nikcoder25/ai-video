"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { resolveClipUrl, type Clip } from "@/lib/api";
import { downloadClip } from "@/lib/download";
import { fileSize, humanDuration, timecode } from "@/lib/format";
import { HookScoreBadge, HookScoreMeter } from "./HookScore";
import { DownloadIcon, PauseIcon, PlayIcon, SoundOffIcon, SoundOnIcon, SpinnerIcon } from "./Icons";

export function ClipCard({ clip, position }: { clip: Clip; position: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [started, setStarted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  // Keep the DOM property in sync — React only sets `muted` on first render.
  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  const toggle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      setStarted(true);
      void video.play().catch(() => setFailed(true));
    } else {
      video.pause();
    }
  }, []);

  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      await downloadClip(clip);
    } finally {
      setSaving(false);
    }
  }

  // `#t=0.1` nudges browsers into rendering a real first frame as the poster.
  const src = `${resolveClipUrl(clip.url)}#t=0.1`;

  return (
    <article
      className="anim-card group flex flex-col"
      style={{ animationDelay: `${Math.min(position, 11) * 55}ms` }}
    >
      <div className="relative aspect-[9/16] w-full overflow-hidden rounded-xl border border-line bg-black transition-colors duration-300 group-hover:border-line/70">
        <video
          ref={videoRef}
          src={src}
          preload="metadata"
          muted
          playsInline
          controls={started}
          controlsList="nodownload"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />

        {/* Play / pause affordance — hidden once native controls take over. */}
        {!started ? (
          <button
            type="button"
            onClick={toggle}
            aria-label={`Play ${clip.title}`}
            className="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-black/55 via-transparent to-black/25 transition-colors duration-300 hover:from-black/45"
          >
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-canvas/75 text-fg backdrop-blur-sm transition-transform duration-300 group-hover:scale-105">
              <PlayIcon className="ml-0.5 h-5 w-5" />
            </span>
          </button>
        ) : (
          <button
            type="button"
            onClick={toggle}
            aria-label={playing ? "Pause" : "Play"}
            className="absolute top-3 right-12 z-10 rounded-lg bg-canvas/70 p-1.5 text-fg opacity-0 backdrop-blur-sm transition-opacity duration-200 group-hover:opacity-100 focus-visible:opacity-100"
          >
            {playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4" />}
          </button>
        )}

        <div className="pointer-events-none absolute top-3 left-3 z-10">
          <HookScoreBadge score={clip.hook_score} />
        </div>

        <button
          type="button"
          onClick={() => setMuted((value) => !value)}
          aria-label={muted ? "Unmute" : "Mute"}
          className="absolute top-3 right-3 z-10 rounded-lg bg-canvas/70 p-1.5 text-fg backdrop-blur-sm transition-colors duration-200 hover:bg-canvas"
        >
          {muted ? <SoundOffIcon className="h-4 w-4" /> : <SoundOnIcon className="h-4 w-4" />}
        </button>

        {!started ? (
          <div className="pointer-events-none absolute right-3 bottom-3 left-3 flex items-center justify-between">
            <span className="numeric rounded-md bg-canvas/75 px-1.5 py-0.5 text-[0.7rem] text-fg backdrop-blur-sm">
              {humanDuration(clip.duration)}
            </span>
            <span className="numeric rounded-md bg-canvas/75 px-1.5 py-0.5 text-[0.7rem] text-fg-muted backdrop-blur-sm">
              {clip.width}×{clip.height}
            </span>
          </div>
        ) : null}

        {failed ? (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-canvas/90 px-4 text-center">
            <p className="text-xs leading-relaxed text-fg-muted">
              This clip wouldn&apos;t load from the API.
            </p>
          </div>
        ) : null}
      </div>

      <div className="flex flex-1 flex-col pt-4">
        <div className="mb-2.5 flex items-center gap-3">
          <HookScoreMeter score={clip.hook_score} />
          <span className="numeric text-[0.7rem] text-fg-faint">
            {timecode(clip.start)} <span className="text-line">→</span> {timecode(clip.end)}
          </span>
        </div>

        <h3 className="text-[0.95rem] leading-snug font-semibold tracking-tight text-balance text-fg">
          {clip.title}
        </h3>

        <p className="mt-2 flex-1 text-[0.825rem] leading-relaxed text-fg-muted">{clip.reason}</p>

        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="numeric text-[0.7rem] text-fg-faint">
            {humanDuration(clip.duration)} · {fileSize(clip.size_bytes)}
          </span>

          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-3 text-[0.8rem] font-medium text-fg transition-all duration-200 hover:border-flame/50 hover:bg-surface-3 active:scale-[0.98] disabled:opacity-60"
          >
            {saving ? (
              <SpinnerIcon className="anim-spin h-4 w-4" />
            ) : (
              <DownloadIcon className="h-4 w-4" />
            )}
            {saving ? "Saving" : "Download"}
          </button>
        </div>
      </div>
    </article>
  );
}
