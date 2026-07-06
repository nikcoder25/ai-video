import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Segment, UGCAdProps, WordTiming } from "../types";

/** URLs/data URIs pass through; everything else is a public-dir static file. */
const resolveSrc = (src: string): string =>
  /^(https?:|data:|blob:)/.test(src) ? src : staticFile(src);

// Self-contained font stack — no render-time network fetch (deterministic,
// works offline). Drop Poppins-ExtraBold.woff2 into public/fonts/ and the
// @font-face below picks it up; otherwise the system stack is used.
const poppins = 'Poppins, "Arial Black", "Helvetica Neue", system-ui, sans-serif';

const FontFace: React.FC = () => (
  <style>{`
    @font-face {
      font-family: "Poppins";
      src: url("${staticFile("fonts/Poppins-ExtraBold.woff2")}") format("woff2");
      font-weight: 700 900;
      font-display: swap;
    }
  `}</style>
);

const isVideo = (src: string) => /\.(mp4|mov|webm|m4v)$/i.test(src);

/** One shot: crop-zoom to hide watermarks + a per-segment punch-in + shake. */
const Shot: React.FC<{ segment: Segment; index: number }> = ({ segment, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const segFrames = Math.max(1, Math.round(segment.duration * fps));
  const t = Math.min(1, frame / segFrames); // 0..1 through the shot

  // Base crop-zoom (1.06x) hides any edge watermark. Ken Burns: zoom ramps
  // in (or out, reversed) across the shot with a subtle directional pan.
  const punch = segment.zoomOut
    ? segment.punchIn * (1 - t) // start tight, settle wide
    : segment.punchIn * t; // classic push-in
  // Cut-pop: land each cut slightly zoomed and settle in ~5 frames — the
  // signature "punched" feel of hand-edited UGC.
  const pop = interpolate(frame, [0, 5], [0.035, 0], { extrapolateRight: "clamp" });
  const scale = 1.06 + punch + pop;

  // Directional drift (Ken Burns pan) + 2px handheld shake. Both deterministic
  // so renders are reproducible.
  const [panX, panY] = segment.pan ?? [0, 0];
  const driftX = panX * t;
  const driftY = panY * t;
  const phase = index * 1.7;
  const shakeX = Math.sin(frame / 6 + phase) * 2;
  const shakeY = Math.cos(frame / 7 + phase) * 2;

  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: `scale(${scale}) translate(${driftX + shakeX}px, ${driftY + shakeY}px)`,
    // Phone color grade: slight saturation + contrast lift.
    filter: "saturate(1.08) contrast(1.05)",
  };

  // White-flash accent: 4-frame burst at the head of flagged cuts.
  const flashOpacity = segment.flash
    ? interpolate(frame, [0, 4], [0.55, 0], { extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {segment.clip && isVideo(segment.clip) ? (
        <OffthreadVideo src={resolveSrc(segment.clip)} muted style={style} />
      ) : segment.clip ? (
        <Img src={resolveSrc(segment.clip)} style={style} />
      ) : (
        <AbsoluteFill style={{ backgroundColor: "#111" }} />
      )}
      {flashOpacity > 0 ? (
        <AbsoluteFill style={{ backgroundColor: "#fff", opacity: flashOpacity }} />
      ) : null}
    </AbsoluteFill>
  );
};

interface CaptionGroup {
  words: WordTiming[];
  start: number;
  end: number;
}

/**
 * Chunk word timings into caption phrases: a new group on speech gaps
 * (>0.45s) or after 4 words. This is how human editors caption UGC — a
 * stable phrase on screen, one word highlighted as it's spoken.
 */
function groupWords(words: WordTiming[]): CaptionGroup[] {
  const groups: CaptionGroup[] = [];
  let cur: WordTiming[] = [];
  for (const w of words) {
    const prev = cur[cur.length - 1];
    if (cur.length >= 4 || (prev && w.start - prev.end > 0.45)) {
      groups.push({ words: cur, start: cur[0].start, end: prev.end });
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) {
    groups.push({ words: cur, start: cur[0].start, end: cur[cur.length - 1].end });
  }
  return groups;
}

/** Phrase captions: whole group visible, active word popped + highlighted. */
const Captions: React.FC<{
  words: WordTiming[];
  style: UGCAdProps["captionStyle"];
}> = ({ words, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const groups = React.useMemo(() => groupWords(words), [words]);
  // Keep the phrase up through trailing silence until the next group starts.
  const gi = groups.findIndex(
    (g, i) => t >= g.start && (i === groups.length - 1 ? t < g.end : t < groups[i + 1].start),
  );
  if (gi < 0) return null;
  const group = groups[gi];

  // Group entrance: quick rise+settle when the phrase appears.
  const groupFrame = Math.max(0, Math.round((t - group.start) * fps));
  const enter = spring({ frame: groupFrame, fps, config: { damping: 13 }, durationInFrames: 7 });

  const activeIdx = group.words.findIndex((w) => t >= w.start && t < w.end);
  const active = activeIdx >= 0 ? group.words[activeIdx] : null;
  const pop = active
    ? spring({
        frame: Math.round((t - active.start) * fps),
        fps,
        config: { damping: 12, stiffness: 200, mass: 0.5 },
        durationInFrames: 8,
      })
    : 0;
  const activeScale = interpolate(pop, [0, 1], [0.86, 1.12]);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: 360,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "0 18px",
          maxWidth: "86%",
          fontFamily: poppins,
          fontWeight: 800,
          fontSize: 68,
          lineHeight: 1.2,
          textTransform: "uppercase",
          textAlign: "center",
          opacity: enter,
          transform: `translateY(${interpolate(enter, [0, 1], [18, 0])}px)`,
        }}
      >
        {group.words.map((w, i) => {
          const isActive = i === activeIdx;
          const spoken = t >= w.start; // already-spoken words stay bright
          return (
            <span
              key={`${gi}-${i}`}
              style={{
                color: isActive ? style.activeColor : style.baseColor,
                opacity: spoken ? 1 : 0.55,
                transform: isActive ? `scale(${activeScale})` : "scale(1)",
                display: "inline-block",
                textShadow: "0 4px 18px rgba(0,0,0,0.65)",
                WebkitTextStroke: "2px rgba(0,0,0,0.35)",
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Bold hook card shown for the first ~1.2s. */
const HookCard: React.FC<{ hook: string }> = ({ hook }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const holdFrames = Math.round(1.2 * fps);
  if (frame > holdFrames) return null;

  const enter = spring({ frame, fps, config: { damping: 14 }, durationInFrames: 10 });
  const exit = interpolate(frame, [holdFrames - 8, holdFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: exit }}>
      <div
        style={{
          transform: `scale(${interpolate(enter, [0, 1], [0.8, 1])})`,
          fontFamily: poppins,
          fontWeight: 900,
          fontSize: 92,
          color: "#fff",
          textAlign: "center",
          maxWidth: "80%",
          lineHeight: 1.1,
          textShadow: "0 8px 30px rgba(0,0,0,0.7)",
          padding: "0 40px",
        }}
      >
        {hook}
      </div>
    </AbsoluteFill>
  );
};

/** Product end-card over the final ~1.6s: title, price, pulsing CTA line. */
const EndCard: React.FC<{ cta: NonNullable<UGCAdProps["cta"]> }> = ({ cta }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const holdFrames = Math.round(1.6 * fps);
  const startFrame = durationInFrames - holdFrames;
  if (frame < startFrame) return null;

  const local = frame - startFrame;
  const enter = spring({ frame: local, fps, config: { damping: 15 }, durationInFrames: 12 });
  const rise = interpolate(enter, [0, 1], [60, 0]);
  // Gentle pulse on the CTA line (two beats per second at 30fps).
  const pulse = 1 + Math.sin(local / 4.8) * 0.04;

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center" }}>
      <AbsoluteFill
        style={{
          background: "linear-gradient(to top, rgba(0,0,0,0.82) 0%, rgba(0,0,0,0) 45%)",
          opacity: enter,
        }}
      />
      <div
        style={{
          position: "relative",
          transform: `translateY(${rise}px)`,
          opacity: enter,
          textAlign: "center",
          paddingBottom: 140,
          fontFamily: poppins,
          maxWidth: "84%",
        }}
      >
        <div style={{ fontSize: 58, fontWeight: 900, color: "#fff", lineHeight: 1.12 }}>
          {cta.title}
        </div>
        {cta.price ? (
          <div style={{ fontSize: 46, fontWeight: 800, color: "#FFE24B", marginTop: 14 }}>
            {cta.price}
          </div>
        ) : null}
        <div
          style={{
            display: "inline-block",
            marginTop: 26,
            padding: "18px 44px",
            borderRadius: ansiRadius,
            background: "#FFE24B",
            color: "#111",
            fontSize: 40,
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: 1,
            transform: `scale(${pulse})`,
          }}
        >
          {cta.line}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const ansiRadius = 999;

/** Film grain + vignette so AI/still footage reads as phone-shot. */
const Realism: React.FC = () => {
  const frame = useCurrentFrame();
  const grain = `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/></filter><rect width='100%' height='100%' filter='url(#n)' opacity='0.5'/></svg>`,
  )}`;
  return (
    <>
      <AbsoluteFill
        style={{
          backgroundImage: `url("${grain}")`,
          backgroundSize: "300px 300px",
          // Nudge the grain each frame so it flickers like real sensor noise.
          backgroundPosition: `${(frame * 13) % 300}px ${(frame * 7) % 300}px`,
          opacity: 0.06,
          mixBlendMode: "overlay",
          pointerEvents: "none",
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export const UGCAd: React.FC<UGCAdProps> = ({
  hook,
  segments,
  voiceover,
  music,
  captionStyle,
  cta,
}) => {
  const { fps, durationInFrames } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <FontFace />
      {segments.map((seg, i) => (
        <Sequence
          key={i}
          from={Math.round(seg.start * fps)}
          durationInFrames={Math.max(1, Math.round(seg.duration * fps))}
        >
          <Shot segment={seg} index={i} />
        </Sequence>
      ))}

      <Realism />
      <HookCard hook={hook} />
      {/* Captions hand off to the end-card for the final 1.6s. */}
      <Sequence
        from={0}
        durationInFrames={
          cta
            ? Math.max(1, durationInFrames - Math.round(1.6 * fps))
            : durationInFrames
        }
      >
        <Captions words={voiceover.words} style={captionStyle} />
      </Sequence>
      {cta ? <EndCard cta={cta} /> : null}

      {voiceover.src ? <Audio src={resolveSrc(voiceover.src)} /> : null}
      {music?.src ? (
        <Audio
          src={resolveSrc(music.src)}
          // Duck under the voice, fade out over the last second.
          volume={(f) =>
            interpolate(
              f,
              [0, durationInFrames - fps, durationInFrames],
              [0.22, 0.22, 0],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
            )
          }
        />
      ) : null}
    </AbsoluteFill>
  );
};
