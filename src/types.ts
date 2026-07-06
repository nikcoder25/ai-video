/**
 * Shared prop shapes. Imported by both the pipeline (which produces them)
 * and the Remotion composition (which consumes them). Keep this file free of
 * Node/React imports so both sides can use it.
 */

/** A single word with its spoken start/end time, in seconds. */
export interface WordTiming {
  word: string;
  start: number;
  end: number;
}

/** One shot in the timeline. `clip` is a still image or video file. */
export interface Segment {
  /** Absolute path or URL to an image (.jpg/.png/.webp) or video (.mp4/.mov). */
  clip: string;
  /** Start time of this segment in the final timeline, in seconds. */
  start: number;
  /** Duration of this segment, in seconds. */
  duration: number;
  /** Extra zoom applied across the segment for a punch-in feel (e.g. 0.08 = +8%). */
  punchIn: number;
}

export interface VoiceOver {
  /** Absolute path to the rendered voiceover audio (mp3). Empty in MOCK mode. */
  src: string;
  words: WordTiming[];
  /** Total voiceover length in seconds. */
  duration: number;
}

export interface Music {
  src: string;
  bpm: number;
}

export interface CaptionStyle {
  fontFamily: string;
  activeColor: string;
  baseColor: string;
}

/**
 * Full input to the <UGCAd> composition — one of these renders one ad.
 * Declared as a `type` (not `interface`) so it satisfies Remotion's
 * `Record<string, unknown>` prop constraint.
 */
/** Optional end-card shown over the last ~1.6s. */
export interface CTACard {
  title: string;
  price: string | null;
  line: string;
}

export type UGCAdProps = {
  fps: number;
  width: number;
  height: number;
  /** Big attention-grabbing line shown in the first ~1.2s. */
  hook: string;
  segments: Segment[];
  voiceover: VoiceOver;
  music: Music | null;
  captionStyle: CaptionStyle;
  /** Product end-card (title + price + CTA line). Omit to disable. */
  cta?: CTACard | null;
};
