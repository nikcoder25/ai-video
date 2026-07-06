import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { config } from "../config";
import { log } from "../logger";
import type { UGCAdProps } from "../types";

const here = path.dirname(fileURLToPath(import.meta.url));
const ENTRY = path.join(here, "..", "remotion", "index.ts");

// Point Remotion at an existing Chromium instead of downloading one
// (set REMOTION_CHROME_PATH to a chrome / headless_shell binary).
const browserExecutable = process.env.REMOTION_CHROME_PATH || null;

/**
 * Bundle the Remotion project once. Reuse the returned serveUrl across all
 * ads in a job — bundling is the slow part.
 */
export async function bundleOnce(): Promise<string> {
  log.step("Bundle Remotion project");
  // bundle() snapshots the public dir into the served output — every asset
  // referenced via staticFile must already exist under config.publicDir here.
  const serveUrl = await bundle({
    entryPoint: ENTRY,
    publicDir: config.publicDir,
  });
  log.ok("bundled");
  return serveUrl;
}

/** Render one ad to `outPath` (mp4/h264). */
export async function renderAd(
  serveUrl: string,
  props: UGCAdProps,
  outPath: string,
): Promise<void> {
  const composition = await selectComposition({
    serveUrl,
    id: "UGCAd",
    inputProps: props,
    browserExecutable,
  });

  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation: outPath,
    inputProps: props,
    browserExecutable,
    // Slightly higher CRF-equivalent quality for social.
    crf: 20,
    onProgress: ({ progress }) => {
      if (progress > 0 && Math.round(progress * 20) % 5 === 0) {
        process.stdout.write(`\r  rendering ${(progress * 100).toFixed(0)}%   `);
      }
    },
  });
  process.stdout.write("\r");
  log.ok(`rendered → ${outPath}`);
}
