/** Client-side validation for the two ways a job can start. */

export const ACCEPTED_EXTENSIONS = ["mp4", "mov", "mkv", "webm"] as const;

/** Matches the `accept` attribute on the file input. */
export const ACCEPT_ATTRIBUTE = ".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm";

export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
export const MAX_UPLOAD_LABEL = "2 GB";

const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtu.be",
  "www.youtu.be",
]);

/**
 * Accepts the shapes people actually paste, with or without a scheme.
 * Returns a normalised absolute URL, or null when it isn't a YouTube video.
 */
export function normalizeYouTubeUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) return null;

  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;

  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return null;
  }

  const host = url.hostname.toLowerCase();
  if (!YOUTUBE_HOSTS.has(host)) return null;

  if (host.endsWith("youtu.be")) {
    return url.pathname.replace(/^\/+/, "").length > 0 ? url.toString() : null;
  }

  const path = url.pathname;
  if (path === "/watch") {
    return url.searchParams.get("v") ? url.toString() : null;
  }
  if (/^\/(shorts|live|embed|v)\/[^/]+/.test(path)) {
    return url.toString();
  }
  return null;
}

export function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index + 1).toLowerCase();
}

/** Returns an error message, or null when the file is acceptable. */
export function validateVideoFile(file: File): string | null {
  const extension = fileExtension(file.name);
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(extension)) {
    return `${file.name.slice(0, 48)} isn't a supported format. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size === 0) {
    return "That file is empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is larger than the ${MAX_UPLOAD_LABEL} upload limit. Paste a YouTube link instead, or trim it first.`;
  }
  return null;
}
