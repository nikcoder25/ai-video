# UGC Ad Factory

Takes a **product URL (or title + photos)** and outputs **3 expert-grade 9:16
UGC ads**. Phase 1 = the render pipeline; Phase 2 = the job API around it.

```
product URL
   │  scrape (title, price, images)
   ▼
Claude ── 3 hooks + scripts (structured output)
   ▼
ElevenLabs ── voiceover + word-level timestamps
   ▼
beat-snap cuts ── segments every 1.5–2s on word boundaries, snapped to BPM
   ▼
props.json per ad
   ▼
Remotion ── crop-zoom · punch-in · handheld shake · word-pop captions
            hook card · music duck+fade · grain + vignette
   ▼
out/ad-1.mp4  out/ad-2.mp4  out/ad-3.mp4
```

## Quick start

```bash
npm install
cp .env.example .env        # add ANTHROPIC_API_KEY and ELEVENLABS_API_KEY
npm run job -- "https://your-store.com/products/neck-fan"
```

Add music + BPM for beat-matched cuts, or bring your own footage:

```bash
npm run job -- "https://store.com/p/x" --music public/track.mp3 --bpm 128
npm run job -- "https://store.com/p/x" --photos clip1.mp4,clip2.mp4,clip3.jpg
```

Outputs land in `out/`: `ad-N.mp4`, `ad-N.props.json`, and downloaded `assets/`.

## Try it with no API keys

`MOCK=1` runs the whole chain with canned scripts and synthetic word timings,
writing the `props.json` for each ad (skips audio/render). Good for verifying
the scrape → script → beat-snap logic:

```bash
MOCK=1 npm run job -- "https://your-store.com/products/neck-fan"
```

## Run as a service (Phase 2 backend)

```bash
npm run serve                # API on :8787, queue worker in-process
```

| Route | What |
|---|---|
| `POST /jobs` | Submit `{"url": "..."}` or `{"title": "...", "photos": ["/abs/p1.jpg", ...]}` (optional `description`, `price`, `music`, `bpm`, `render:false`) |
| `GET /jobs` | Recent jobs |
| `GET /jobs/:id` | Status + `results[].video` download links |
| `GET /jobs/:id/files/:name` | Stream a finished MP4 / props JSON |
| `GET /health` | Liveness |

Jobs persist in SQLite (`data/jobs.db`, Node's built-in driver — no native
deps); stale `running` jobs re-queue on boot. Renders run one-at-a-time
(CPU-bound). Finished files live on disk and are served by the API; set
`SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (+ optional `SUPABASE_BUCKET`) to
upload artifacts to Supabase Storage instead.

## Preview / tune the template

```bash
npm run studio       # opens Remotion Studio on the UGCAd composition
```

The composition consumes the shape in [`src/types.ts`](src/types.ts). ElevenLabs
word timestamps flow straight into `voiceover.words`.

## Layout

| Path | Role |
|------|------|
|  `src/worker.ts` | CLI orchestrator (the pipeline) |
| `src/pipeline/scrape.ts` | Product URL → title/price/images |
| `src/pipeline/script.ts` | Claude → 3 hook+script variants |
| `src/pipeline/voice.ts` | ElevenLabs → audio + word timings |
| `src/pipeline/beats.ts` | Beat grid + cut-boundary logic |
| `src/pipeline/props.ts` | Assemble `UGCAdProps` per ad |
| `src/pipeline/render.ts` | Bundle once, render each ad |
| `src/remotion/UGCAd.tsx` | The expert-edit template |
| `src/pipeline/run.ts` | Reusable `runJob()` (CLI + queue both call it) |
| `src/server/index.ts` | Fastify REST API |
| `src/server/queue.ts` | In-process queue worker |
| `src/server/db.ts` | SQLite job store (`node:sqlite`) |
| `src/storage/index.ts` | Local / Supabase storage adapter |

## Config

Env vars (see `.env.example`): `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`, `SCRIPT_MODEL` (default `claude-opus-4-8`), `MOCK`.
Format/rhythm constants live in `src/config.ts`.

**Rendering / Chromium:** Remotion downloads a headless Chromium on first
render. On a locked-down VPS (or to reuse an installed browser) set
`REMOTION_CHROME_PATH` to a `chrome-headless-shell` binary and it's used
instead of downloading. Job assets are staged under `public/jobs/<id>/` so
Remotion can serve them; clips may also be plain `http(s)` URLs.

## Next (Phase 2+)

- Swap `./out` writes for Supabase storage; add a job queue (Upstash).
- Dashboard: submit job, status, download, credits.
- Human QC approve/reject screen before delivery.
- Template #2 and #3.
