import { writeFile } from "node:fs/promises";
import { config } from "../config";
import { log } from "../logger";
import type { WordTiming } from "../types";

export interface VoiceResult {
  /** Absolute path to the mp3, or "" in MOCK mode. */
  src: string;
  words: WordTiming[];
  duration: number;
}

interface ElevenAlignment {
  characters: string[];
  character_start_times_seconds: number[];
  character_end_times_seconds: number[];
}

/** Collapse per-character alignment into per-word timings. */
function wordsFromAlignment(a: ElevenAlignment): WordTiming[] {
  const words: WordTiming[] = [];
  let cur = "";
  let start = -1;
  let end = 0;
  for (let i = 0; i < a.characters.length; i++) {
    const ch = a.characters[i];
    const isBreak = ch === " " || ch === "\n" || ch === "\t";
    if (isBreak) {
      if (cur) {
        words.push({ word: cur, start: start < 0 ? end : start, end });
        cur = "";
        start = -1;
      }
    } else {
      if (start < 0) start = a.character_start_times_seconds[i];
      end = a.character_end_times_seconds[i];
      cur += ch;
    }
  }
  if (cur) words.push({ word: cur, start: start < 0 ? end : start, end });
  return words;
}

/** Synthetic timings so the pipeline is testable without ElevenLabs. */
function mockVoice(text: string): VoiceResult {
  const tokens = text.split(/\s+/).filter(Boolean);
  const perWord = 0.34;
  const words: WordTiming[] = tokens.map((word, i) => ({
    word,
    start: i * perWord,
    end: (i + 1) * perWord - 0.04,
  }));
  return { src: "", words, duration: tokens.length * perWord };
}

/**
 * Render `text` to speech with word-level timestamps.
 * Falls back to synthetic timings when MOCK=1 / no key (no audio file).
 */
export async function synthesizeVoice(text: string, outPath: string): Promise<VoiceResult> {
  log.step("Voiceover (ElevenLabs)");

  if (config.mock || !config.elevenApiKey) {
    if (!config.mock) log.warn("no ELEVENLABS_API_KEY — using synthetic timings (no audio)");
    const r = mockVoice(text);
    log.ok(`${r.words.length} words, ${r.duration.toFixed(1)}s (mock)`);
    return r;
  }

  const url = `https://api.elevenlabs.io/v1/text-to-speech/${config.elevenVoiceId}/with-timestamps`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "xi-api-key": config.elevenApiKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      text,
      model_id: config.elevenModel,
      output_format: "mp3_44100_128",
    }),
  });
  if (!res.ok) {
    throw new Error(`ElevenLabs ${res.status}: ${await res.text().catch(() => "")}`);
  }

  const data = (await res.json()) as {
    audio_base64: string;
    alignment: ElevenAlignment;
    normalized_alignment?: ElevenAlignment;
  };

  await writeFile(outPath, Buffer.from(data.audio_base64, "base64"));
  const alignment = data.normalized_alignment ?? data.alignment;
  const words = wordsFromAlignment(alignment);
  const duration = words.length ? words[words.length - 1].end : 0;
  log.ok(`${words.length} words, ${duration.toFixed(1)}s → ${outPath}`);
  return { src: outPath, words, duration };
}
