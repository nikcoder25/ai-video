import { copyFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { config } from "./config";
import { log } from "./logger";
import { scrapeProduct } from "./pipeline/scrape";
import { generateScripts } from "./pipeline/script";
import { synthesizeVoice } from "./pipeline/voice";
import { buildProps } from "./pipeline/props";
import { bundleOnce, renderAd } from "./pipeline/render";
import type { Music } from "./types";

interface Args {
  url: string;
  out: string;
  photos: string[];
  music: string | null;
  bpm: number;
  renderVideos: boolean;
}

function parseArgs(argv: string[]): Args {
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
  if (!url) {
    throw new Error(
      "Usage: npm run job -- <product-url> [--photos a.jpg,b.jpg] [--music track.mp3] [--bpm 120] [--out out] [--no-render]",
    );
  }
  return {
    url,
    out: opts.out ?? "out",
    photos: opts.photos ? opts.photos.split(",").map((s) => s.trim()).filter(Boolean) : [],
    music: opts.music ?? null,
    bpm: opts.bpm ? Number(opts.bpm) : config.defaultBpm,
    renderVideos: opts.render !== "false" && opts["no-render"] !== "true",
  };
}

/** Path relative to the Remotion public dir, as a forward-slash URL segment. */
function toPublic(abs: string): string {
  return path.relative(config.publicDir, abs).split(path.sep).join("/");
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const jobId = `job-${Date.now()}`;
  const jobDir = path.resolve(args.out);
  // Assets Remotion must serve live under public/; renders + props go to out/.
  const stageDir = path.join(config.publicDir, "jobs", jobId);
  await mkdir(jobDir, { recursive: true });
  await mkdir(stageDir, { recursive: true });

  log.info(`Job: ${args.url}`);
  log.info(`Output: ${jobDir}${config.mock ? "   (MOCK mode)" : ""}`);

  // 1. Scrape (for product context + fallback clips).
  const product = await scrapeProduct(args.url, stageDir);

  // Clips: user photos (copied into public) or scraped product images.
  let clips: string[];
  if (args.photos.length > 0) {
    clips = [];
    for (let i = 0; i < args.photos.length; i++) {
      const dest = path.join(stageDir, `photo-${i + 1}${path.extname(args.photos[i])}`);
      await copyFile(args.photos[i], dest);
      clips.push(toPublic(dest));
    }
  } else {
    clips = product.images.map(toPublic);
  }

  // 2. Scripts.
  const variants = await generateScripts(product);

  // Music (optional): stage into public so Remotion can serve it.
  let music: Music | null = null;
  if (args.music) {
    const dest = path.join(stageDir, `music${path.extname(args.music)}`);
    await copyFile(args.music, dest);
    music = { src: toPublic(dest), bpm: args.bpm };
  }

  // 3-5. Stage every asset first (voice → props). All public-dir files must
  // exist before we bundle, because bundle() snapshots the public dir.
  const ads: { index: number; hook: string; props: ReturnType<typeof buildProps> }[] = [];
  for (let i = 0; i < variants.length; i++) {
    const v = variants[i];
    log.step(`Ad ${i + 1}/${variants.length}: "${v.hook}"`);

    const audioAbs = path.join(stageDir, `vo-${i + 1}.mp3`);
    const voice = await synthesizeVoice(`${v.hook}. ${v.script}`, audioAbs);
    // Rewrite the audio path to a public-relative URL for the composition.
    const voiceForProps = { ...voice, src: voice.src ? toPublic(audioAbs) : "" };

    const props = buildProps({ hook: v.hook, clips, voice: voiceForProps, music });

    const propsPath = path.join(jobDir, `ad-${i + 1}.props.json`);
    await writeFile(propsPath, JSON.stringify(props, null, 2));
    log.ok(`props → ${propsPath}`);
    ads.push({ index: i + 1, hook: v.hook, props });
  }

  // 6. Bundle once (after all assets exist), then render each ad.
  const results: string[] = [];
  if (args.renderVideos) {
    const serveUrl = await bundleOnce();
    for (const ad of ads) {
      log.step(`Render ad ${ad.index}: "${ad.hook}"`);
      const outPath = path.join(jobDir, `ad-${ad.index}.mp4`);
      await renderAd(serveUrl, ad.props, outPath);
      results.push(outPath);
    }
  }

  log.step("Done");
  if (results.length) {
    results.forEach((r) => log.ok(r));
  } else {
    log.info("Props written. Re-run without --no-render to produce MP4s.");
  }
}

main().catch((err) => {
  log.error(err instanceof Error ? err.message : String(err));
  process.exitCode = 1;
});
