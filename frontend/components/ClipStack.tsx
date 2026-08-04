/**
 * Decorative fan of 9:16 frames for the hero. Abstract on purpose — no fake
 * copy, no fake thumbnails, just the shape of the output.
 */

const FRAMES = [
  {
    score: 7,
    side: "left" as const,
    rotate: -8,
    x: -72,
    y: 26,
    z: 10,
    scale: 0.86,
    tone: "var(--color-heat-hot)",
  },
  {
    score: 8,
    side: "right" as const,
    rotate: 7,
    x: 76,
    y: 34,
    z: 10,
    scale: 0.82,
    tone: "var(--color-heat-warm)",
  },
  {
    score: 9,
    side: "left" as const,
    rotate: -1.5,
    x: 0,
    y: 0,
    z: 30,
    scale: 1,
    tone: "var(--color-heat-blazing)",
  },
];

/** Audio waveform motif — fixed heights so server and client agree. */
const WAVE = [
  0.3, 0.55, 0.4, 0.8, 0.62, 0.95, 0.7, 0.45, 0.85, 0.5, 0.35, 0.68, 0.9, 0.52, 0.4, 0.75, 0.58,
  0.33,
];

export function ClipStack() {
  return (
    <div aria-hidden="true" className="relative h-[24rem] w-full select-none">
      {FRAMES.map((frame) => {
        const front = frame.z === 30;
        return (
          // Outer element owns the fan transform; the entrance animation lives
          // on the inner one so its `transform: none` keyframe can't clobber it.
          <div
            key={frame.score}
            className="absolute top-0 left-1/2 aspect-[9/16] h-full origin-bottom"
            style={{
              transform: `translateX(calc(-50% + ${frame.x}px)) translateY(${frame.y}px) rotate(${frame.rotate}deg) scale(${frame.scale})`,
              zIndex: frame.z,
            }}
          >
            <div
              className="anim-card relative h-full w-full overflow-hidden rounded-2xl border border-white/10 bg-surface-2 shadow-[0_36px_70px_-24px_rgba(0,0,0,0.9)]"
              style={{ animationDelay: `${frame.z * 6}ms` }}
            >
              <div className="absolute inset-0 bg-[radial-gradient(120%_55%_at_50%_16%,rgba(255,106,43,0.18),transparent_64%)]" />
              <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/75 to-transparent" />

              {/* audio waveform motif */}
              <div className="absolute inset-x-6 top-[38%] flex h-10 items-center justify-between gap-[3px]">
                {WAVE.map((height, index) => (
                  <span
                    key={index}
                    className="w-[2px] flex-1 rounded-full bg-white/22"
                    style={{ height: `${height * 100}%` }}
                  />
                ))}
              </div>

              {/* hook score chip, pinned to the frame's outer edge so the fan
                  never buries it */}
              <div
                className={`absolute top-3 flex h-7 w-7 items-center justify-center rounded-lg text-[0.8rem] font-semibold ${
                  frame.side === "left" ? "left-3" : "right-3"
                }`}
                style={{
                  backgroundColor: frame.tone,
                  color: "#150703",
                  boxShadow: front ? `0 0 26px -4px ${frame.tone}` : "none",
                }}
              >
                {frame.score}
              </div>

              {/* caption motif: max 3 words per line, per the render spec */}
              <div className="absolute inset-x-0 bottom-8 flex flex-col items-center gap-2">
                <div className="h-2.5 w-1/2 rounded-full bg-white/90" />
                <div className="h-2.5 w-2/3 rounded-full bg-white/30" />
              </div>

              {/* 9:16 safe-area guides, front frame only */}
              {front ? (
                <>
                  <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-white/8" />
                  <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/8" />
                </>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
