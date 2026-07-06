import path from "node:path";
import { config } from "./config";
import { log } from "./logger";
import { runJob, type JobInput } from "./pipeline/run";

/**
 * CLI entrypoint: run one job from the terminal.
 *   npm run job -- <product-url> [--photos a.jpg,b.jpg] [--music track.mp3]
 *                  [--bpm 120] [--title "..."] [--out out] [--no-render]
 */
function parseArgs(argv: string[]): { input: JobInput; out: string } {
  const positional: string[] = [];
  const opts: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
      opts[key] = val;
    } else {
      positional.push(a);
    }
  }
  const url = positional[0] ?? opts.url;
  if (!url && !opts.title) {
    throw new Error(
      'Usage: npm run job -- <product-url> [--photos a.jpg,b.jpg] [--music track.mp3] [--bpm 120] [--title "..."] [--out out] [--no-render]',
    );
  }
  return {
    input: {
      url,
      title: opts.title,
      photos: opts.photos
        ? opts.photos.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined,
      music: opts.music,
      bpm: opts.bpm ? Number(opts.bpm) : undefined,
      render: opts.render !== "false" && opts["no-render"] !== "true",
    },
    out: opts.out ?? "out",
  };
}

async function main(): Promise<void> {
  const { input, out } = parseArgs(process.argv.slice(2));
  const jobId = `job-${Date.now()}`;
  const jobDir = path.resolve(out);

  log.info(`Job: ${input.url ?? input.title}`);
  log.info(`Output: ${jobDir}${config.mock ? "   (MOCK mode)" : ""}`);

  const result = await runJob(jobId, input, jobDir, (stage, detail) =>
    log.info(`[${stage}] ${detail ?? ""}`),
  );

  log.step("Done");
  for (const ad of result.ads) {
    log.ok(ad.videoPath ?? ad.propsPath);
  }
}

main().catch((err) => {
  log.error(err instanceof Error ? err.message : String(err));
  process.exitCode = 1;
});
