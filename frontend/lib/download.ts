import { resolveClipUrl, type Clip } from "./api";
import { slugify } from "./format";

export function clipFilename(clip: Clip): string {
  const index = clip.index.toString().padStart(2, "0");
  return `clipviral-${index}-${slugify(clip.title)}.mp4`;
}

function triggerDownload(href: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/**
 * Saves the mp4. The `download` attribute is ignored for cross-origin hrefs
 * (e.g. presigned R2), so we pull the bytes into a blob first and fall back to
 * a plain navigation if that is blocked by CORS.
 */
export async function downloadClip(clip: Clip): Promise<void> {
  const href = resolveClipUrl(clip.url);
  const filename = clipFilename(clip);

  try {
    const response = await fetch(href);
    if (!response.ok) throw new Error(`status ${response.status}`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    triggerDownload(objectUrl, filename);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  } catch {
    triggerDownload(href, filename);
  }
}
