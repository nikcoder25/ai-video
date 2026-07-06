import * as cheerio from "cheerio";
import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import path from "node:path";
import { log } from "../logger";

export interface Product {
  title: string;
  description: string;
  price: string | null;
  /** Remote image URLs found on the page. */
  imageUrls: string[];
  /** Local paths after download. */
  images: string[];
}

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

/** Pull the first schema.org Product node out of any JSON-LD blocks. */
function readJsonLdProduct($: cheerio.CheerioAPI): Record<string, unknown> | null {
  const blocks = $('script[type="application/ld+json"]').toArray();
  for (const el of blocks) {
    const raw = $(el).text().trim();
    if (!raw) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      continue;
    }
    const nodes = Array.isArray(parsed) ? parsed : [parsed];
    for (const node of nodes) {
      if (node && typeof node === "object") {
        const type = (node as { "@type"?: unknown })["@type"];
        const isProduct = Array.isArray(type)
          ? type.includes("Product")
          : type === "Product";
        if (isProduct) return node as Record<string, unknown>;
        const graph = (node as { "@graph"?: unknown })["@graph"];
        if (Array.isArray(graph)) {
          const p = graph.find(
            (g) => g && typeof g === "object" && (g as { "@type"?: unknown })["@type"] === "Product",
          );
          if (p) return p as Record<string, unknown>;
        }
      }
    }
  }
  return null;
}

function extractPrice(
  ld: Record<string, unknown> | null,
  $: cheerio.CheerioAPI,
): string | null {
  const offers = ld?.offers as { price?: unknown; priceCurrency?: unknown } | undefined;
  if (offers?.price != null) {
    const cur = typeof offers.priceCurrency === "string" ? `${offers.priceCurrency} ` : "";
    return `${cur}${String(offers.price)}`;
  }
  const meta =
    $('meta[property="product:price:amount"]').attr("content") ??
    $('meta[property="og:price:amount"]').attr("content");
  return meta ?? null;
}

function absolutize(url: string, base: string): string | null {
  try {
    return new URL(url, base).toString();
  } catch {
    return null;
  }
}

async function download(url: string, dest: string): Promise<void> {
  const res = await fetch(url, { headers: { "user-agent": UA } });
  if (!res.ok || !res.body) throw new Error(`${res.status} for ${url}`);
  await pipeline(Readable.fromWeb(res.body as never), createWriteStream(dest));
}

/**
 * Fetch a product page and extract title, price, and image URLs, then download
 * up to `maxImages` images into `assetsDir`.
 */
export async function scrapeProduct(
  url: string,
  assetsDir: string,
  maxImages = 4,
): Promise<Product> {
  log.step("Scrape product");
  const res = await fetch(url, { headers: { "user-agent": UA } });
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  const html = await res.text();
  const $ = cheerio.load(html);
  const ld = readJsonLdProduct($);

  const title =
    (typeof ld?.name === "string" && ld.name) ||
    $('meta[property="og:title"]').attr("content") ||
    $("title").first().text().trim() ||
    "This product";

  const description =
    (typeof ld?.description === "string" && ld.description) ||
    $('meta[property="og:description"]').attr("content") ||
    $('meta[name="description"]').attr("content") ||
    "";

  const price = extractPrice(ld, $);

  // Collect candidate image URLs: JSON-LD images, og:image, then <img> tags.
  const urls = new Set<string>();
  const ldImage = ld?.image;
  if (typeof ldImage === "string") urls.add(ldImage);
  else if (Array.isArray(ldImage)) ldImage.forEach((i) => typeof i === "string" && urls.add(i));
  $('meta[property="og:image"]').each((_, el) => {
    const c = $(el).attr("content");
    if (c) urls.add(c);
  });
  $("img").each((_, el) => {
    const src = $(el).attr("src") ?? $(el).attr("data-src");
    if (src && !src.startsWith("data:")) urls.add(src);
  });

  const imageUrls = [...urls]
    .map((u) => absolutize(u, url))
    .filter((u): u is string => Boolean(u))
    .slice(0, maxImages * 2); // over-collect; some downloads may fail

  log.ok(`"${title.slice(0, 60)}"${price ? ` — ${price}` : ""}`);
  log.info(`${imageUrls.length} image candidates`);

  await mkdir(assetsDir, { recursive: true });
  const images: string[] = [];
  for (const imgUrl of imageUrls) {
    if (images.length >= maxImages) break;
    const ext = (imgUrl.split("?")[0].match(/\.(jpe?g|png|webp)$/i)?.[0] ?? ".jpg").toLowerCase();
    const dest = path.join(assetsDir, `img-${images.length + 1}${ext}`);
    try {
      await download(imgUrl, dest);
      images.push(dest);
    } catch (e) {
      log.warn(`skip image (${(e as Error).message})`);
    }
  }

  if (images.length === 0) {
    throw new Error(
      "No usable product images found. Pass --photos with your own image files instead.",
    );
  }
  log.ok(`downloaded ${images.length} images`);

  return { title, description, price, imageUrls, images };
}
