import "dotenv/config";
import path from "node:path";

export const config = {
  /** Remotion serves this dir; all render assets are staged under it. */
  publicDir: path.resolve("public"),
  anthropicApiKey: process.env.ANTHROPIC_API_KEY ?? "",
  elevenApiKey: process.env.ELEVENLABS_API_KEY ?? "",
  // Default voice = ElevenLabs "Sarah" (warm, natural, good for UGC).
  elevenVoiceId: process.env.ELEVENLABS_VOICE_ID ?? "EXAVITQu4vr4xnSDxMaL",
  elevenModel: process.env.ELEVENLABS_MODEL ?? "eleven_turbo_v2_5",
  scriptModel: process.env.SCRIPT_MODEL ?? "claude-opus-4-8",
  /** With MOCK=1 the pipeline runs with canned scripts + synthetic timings. */
  mock: process.env.MOCK === "1",

  // Vertical short-form format.
  fps: 30,
  width: 1080,
  height: 1920,

  // Edit rhythm.
  minSegment: 1.5,
  maxSegment: 2.0,
  defaultBpm: 120,
} as const;

export type AppConfig = typeof config;
