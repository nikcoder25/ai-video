import { config } from "../config";
import { log } from "../logger";
import type { Music, Segment, UGCAdProps, VoiceOver } from "../types";
import { beatGrid, cutBoundaries } from "./beats";
import type { VoiceResult } from "./voice";

export interface BuildPropsInput {
  hook: string;
  clips: string[];
  voice: VoiceResult;
  music: Music | null;
}

/**
 * Turn a voiceover + clip list into a fully-specified <UGCAd> prop object:
 * beat-snapped segments, round-robin clip assignment, alternating punch-ins.
 */
export function buildProps(input: BuildPropsInput): UGCAdProps {
  log.step("Build props (beat-snap cuts)");
  const { hook, clips, voice, music } = input;
  const duration = Math.max(voice.duration, 3);

  const beats = beatGrid(music?.bpm ?? config.defaultBpm, duration);
  const boundaries = cutBoundaries(voice.words, duration, {
    min: config.minSegment,
    max: config.maxSegment,
    beats,
  });

  const segments: Segment[] = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i];
    const end = boundaries[i + 1];
    segments.push({
      clip: clips[i % clips.length],
      start,
      duration: end - start,
      // Alternate punch direction feel: bigger push on odd segments.
      punchIn: i % 2 === 0 ? 0.06 : 0.1,
    });
  }

  const voiceover: VoiceOver = {
    src: voice.src,
    words: voice.words,
    duration,
  };

  log.ok(`${segments.length} segments over ${duration.toFixed(1)}s, ${clips.length} clips`);

  return {
    fps: config.fps,
    width: config.width,
    height: config.height,
    hook,
    segments,
    voiceover,
    music,
    captionStyle: {
      fontFamily: "Poppins",
      activeColor: "#FFE24B",
      baseColor: "#FFFFFF",
    },
  };
}
