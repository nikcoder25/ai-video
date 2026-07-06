import { copyFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { config } from "../config";
import { log } from "../logger";
import { scrapeProduct, type Product } from "./scrape";
import { generateScripts } from "./script";
import { synthesizeVoice } from "./voice";
import { buildProps } from "./props";
import { bundleOnce, renderAd } from "./render";
import type { Music, UGCAdProps } from "../types";

/**
 * A job can come from a product URL (scraped) or from direct user input
 * (title + uploaded photos) — the SaaS dashboard uses the second shape.
 */
export interface JobInput {
  /** Product page to scrape. Optional when title+photos are given directly. */
  url?: string;
  /** Direct product info (skips scraping when title is present). */
  title?: string;
  description?: string;
  price?: string;
  /** Local media files (images/videos) to use as clips. */
  photos?: string[];
  /** Local music file + BPM for beat-matched cuts. */
  music?: string;
  bpm?: number;
  /** Skip the MP4 render (props JSON only). */
  render?: boolean;
}

export interface AdResult {
  index: number;
  hook: string;
  propsPath: string;
  videoPath: string | null;
}

export interface JobResult {
  jobId: string;
  productTitle: string;
  ads: AdResult[];
}

export type ProgressFn = (stage: string, detail?: string) => void;

/**
 * Run the full pipeline for one job:
 * product -> 3 scripts -> voiceovers -> beat-snapped props -> 3 renders.
 * Writes outputs to `jobDir`; stages servable assets under public/jobs/<id>/.
 */
export async function runJob(
  jobId: string,
  input: JobInput,
  jobDir: string,
  onProgress: ProgressFn = () => {},
): Promise<JobResult> {
  const stageDir = path.join(config.publicDir, "jobs", jobId);
  await mkdir(jobDir, { recursive: true });
  await mkdir(stageDir, { recursive: true });

  const toPublic = (abs: string) =>
    path.relative(config.publicDir, abs).split(path.sep).join("/");

  // 1. Product context: scrape the URL, or use direct input.
  let product: Product;
  if (input.title) {
    onProgress("product", "using provided details");
    product = {
      title: input.title,
      description: input.description ?? "",
      price: input.price ?? null,
      imageUrls: [],
      images: [],
    };
  } else if (input.url) {
    onProgress("scraping", input.url);
    product = await scrapeProduct(input.url, stageDir);
  } else {
    throw new Error("Job needs either `url` or `title` (+ photos)");
  }

  // Clips: provided photos (copied into public) or scraped product images.
  let clips: string[];
  if (input.photos && input.photos.length > 0) {
    clips = [];
    for (let i = 0; i < input.photos.length; i++) {
      const src = input.photos[i];
      const dest = path.join(stageDir, `photo-${i + 1}${path.extname(src)}`);
      await copyFile(src, dest);
      clips.push(toPublic(dest));
    }
  } else if (product.images.length > 0) {
    clips = product.images.map(toPublic);
  } else {
    throw new Error("No clips: provide photos or a scrapeable product URL");
  }

  // 2. Scripts.
  onProgress("scripting");
  const variants = await generateScripts(product);

  // Music (optional): stage into public so Remotion can serve it.
  let music: Music | null = null;
  if (input.music) {
    const dest = path.join(stageDir, `music${path.extname(input.music)}`);
    await copyFile(input.music, dest);
    music = { src: toPublic(dest), bpm: input.bpm ?? config.defaultBpm };
  }

  // 3-5. Stage every asset (voice -> props) BEFORE bundling: bundle()
  // snapshots the public dir, so all staticFile assets must exist first.
  const ads: { index: number; hook: string; props: UGCAdProps; propsPath: string }[] = [];
  for (let i = 0; i < variants.length; i++) {
    const v = variants[i];
    onProgress("voicing", `ad ${i + 1}/${variants.length}: "${v.hook}"`);
    log.step(`Ad ${i + 1}/${variants.length}: "${v.hook}"`);

    const audioAbs = path.join(stageDir, `vo-${i + 1}.mp3`);
    const voice = await synthesizeVoice(`${v.hook}. ${v.script}`, audioAbs);
    const voiceForProps = { ...voice, src: voice.src ? toPublic(audioAbs) : "" };

    const props = buildProps({
      hook: v.hook,
      clips,
      voice: voiceForProps,
      music,
      cta: { title: product.title, price: product.price },
    });

    const propsPath = path.join(jobDir, `ad-${i + 1}.props.json`);
    await writeFile(propsPath, JSON.stringify(props, null, 2));
    log.ok(`props → ${propsPath}`);
    ads.push({ index: i + 1, hook: v.hook, props, propsPath });
  }

  // 6. Bundle once, render each ad.
  const results: AdResult[] = ads.map((a) => ({
    index: a.index,
    hook: a.hook,
    propsPath: a.propsPath,
    videoPath: null,
  }));

  if (input.render !== false) {
    onProgress("bundling");
    const serveUrl = await bundleOnce();
    for (let i = 0; i < ads.length; i++) {
      onProgress("rendering", `ad ${ads[i].index}/${ads.length}`);
      log.step(`Render ad ${ads[i].index}: "${ads[i].hook}"`);
      const outPath = path.join(jobDir, `ad-${ads[i].index}.mp4`);
      await renderAd(serveUrl, ads[i].props, outPath);
      results[i].videoPath = outPath;
    }
  }

  return { jobId, productTitle: product.title, ads: results };
}
