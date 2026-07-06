import type { WordTiming } from "../types";

/** Absolute beat times (seconds) for a given BPM across `duration`. */
export function beatGrid(bpm: number, duration: number, offset = 0): number[] {
  const period = 60 / bpm;
  const beats: number[] = [];
  for (let t = offset; t <= duration + 1e-6; t += period) beats.push(t);
  return beats;
}

/** Nearest beat to `t`, within `tolerance` seconds; else `t` unchanged. */
export function snapToBeat(t: number, beats: number[], tolerance = 0.18): number {
  let best = t;
  let bestDist = tolerance;
  for (const b of beats) {
    const d = Math.abs(b - t);
    if (d < bestDist) {
      bestDist = d;
      best = b;
    }
  }
  return best;
}

/**
 * Produce cut boundaries every `min`..`max` seconds, landing on word
 * boundaries (never mid-word) and snapped to the musical beat grid.
 * Returns sorted boundary times in [0, duration].
 */
export function cutBoundaries(
  words: WordTiming[],
  duration: number,
  opts: { min: number; max: number; beats: number[] },
): number[] {
  const { min, max, beats } = opts;
  const boundaries: number[] = [0];
  let last = 0;

  for (const w of words) {
    const since = w.end - last;
    if (since >= min) {
      // Prefer a beat within reach; otherwise cut at this word boundary.
      const snapped = snapToBeat(w.end, beats);
      const chosen = snapped > last + 0.4 ? snapped : w.end;
      boundaries.push(chosen);
      last = chosen;
    } else if (since >= max) {
      boundaries.push(w.end);
      last = w.end;
    }
  }

  if (duration - last > 0.3) boundaries.push(duration);
  else boundaries[boundaries.length - 1] = duration;

  // De-dupe and enforce monotonic spacing.
  return boundaries.filter((t, i) => i === 0 || t - boundaries[i - 1] > 0.25);
}
