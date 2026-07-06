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
// works offline). To use exact Poppins, drop a Poppins woff2 into public/ and
// register it via @font-face / staticFile; the stack picks it up first.
const poppins = 'Poppins, "Arial Black", "Helvetica Neue", system-ui, sans-serif';

const isVideo = (src: string) => /\.(mp4|mov|webm|m4v)$/i.test(src);

/** One shot: crop-zoom to hide watermarks + a per-segment punch-in + shake. */
const Shot: React.FC<{ segment: Segment; index: number }> = ({ segment, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const segFrames = Math.max(1, Math.round(segment.duration * fps));

  // Base crop-zoom (1.06x) hides any edge watermark; punch-in ramps across shot.
  const punch = interpolate(frame, [0, segFrames], [0, segment.punchIn], {
    extrapolateRight: "clamp",
  });
  const scale = 1.06 + punch;

  // 2px handheld shake — deterministic per-segment sine so renders are stable.
  const phase = index * 1.7;
  const shakeX = Math.sin(frame / 6 + phase) * 2;
  const shakeY = Math.cos(frame / 7 + phase) * 2;

  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: `scale(${scale}) translate(${shakeX}px, ${shakeY}px)`,
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {segment.clip && isVideo(segment.clip) ? (
        <OffthreadVideo src={resolveSrc(segment.clip)} muted style={style} />
      ) : segment.clip ? (
        <Img src={resolveSrc(segment.clip)} style={style} />
      ) : (
        <AbsoluteFill style={{ backgroundColor: "#111" }} />
      )}
    </AbsoluteFill>
  );
};

/** Word-by-word captions with a pop on the active word. */
const Captions: React.FC<{
  words: WordTiming[];
  style: UGCAdProps["captionStyle"];
}> = ({ words, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const activeIdx = words.findIndex((w) => t >= w.start && t < w.end);
  if (activeIdx < 0) return null;

  // Show a small window around the active word (a caption "line").
  const from = Math.max(0, activeIdx - 2);
  const to = Math.min(words.length, activeIdx + 3);
  const window = words.slice(from, to);

  const active = words[activeIdx];
  const pop = spring({
    frame: Math.round((t - active.start) * fps),
    fps,
    config: { damping: 12, stiffness: 200, mass: 0.5 },
    durationInFrames: 8,
  });
  const activeScale = interpolate(pop, [0, 1], [0.8, 1.12]);

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
          lineHeight: 1.15,
          textTransform: "uppercase",
          textAlign: "center",
        }}
      >
        {window.map((w, i) => {
          const isActive = from + i === activeIdx;
          return (
            <span
              key={`${from + i}-${w.word}`}
              style={{
                color: isActive ? style.activeColor : style.baseColor,
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
}) => {
  const { fps, durationInFrames } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
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
      <Captions words={voiceover.words} style={captionStyle} />

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
