# ClipViral

Long video in, viral 9:16 clips out. Paste a YouTube URL or upload a file; the
pipeline finds the moments worth posting, reframes them vertically, burns
word-synced captions, and hands back downloadable MP4s.

```
YouTube URL / upload
   │  yt-dlp  ──────────────── source.mp4 + 16kHz mono wav
   ▼
Deepgram nova-2 ───────────── word-level timestamps + speakers
   ▼
Claude ────────────────────── 8-12 clip candidates, scored 1-10
   │                            snapped to sentence boundaries
   ▼
MediaPipe / OpenCV ────────── face track, smoothed 9:16 crop path
   ▼
ffmpeg ────────────────────── cut · crop · burn captions · -14 LUFS
   ▼
clip-01.mp4 … clip-NN.mp4     1080x1920, under 50 MB each
```

## Quick start

```bash
cp .env.example .env          # add DEEPGRAM_API_KEY and ANTHROPIC_API_KEY

cd backend
pip install -r requirements.txt
python cli.py "https://youtube.com/watch?v=..." --render
```

Clips land in `work/<job-id>/clips/`, with `candidates.json` next to them.

### No API keys? Run the whole thing anyway

```bash
MOCK=1 python cli.py "anything" --render
```

`MOCK=1` synthesises a source video with ffmpeg, uses a fixture transcript and
fixture candidates, and runs every real ffmpeg path — cut, crop, caption burn,
loudness, encode. It verifies the machinery. It tells you **nothing** about
whether the clip picks are good.

### Run the web app

```bash
cd backend && uvicorn main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:3000.

## Do this before trusting it

The selection prompt is the entire business. Everything else is plumbing that
can be fixed in an afternoon; a prompt that picks boring moments cannot.

Run the gate:

```bash
python cli.py "<real podcast episode>"     # no --render, candidates only
```

The CLI prints every pick with a jump link straight to that timestamp:

```
  [ 9/10]      13:32-14:16  (44.0s)  The 3am rule that changed his life
           Opens on a question, pays off at 0:41
           watch: https://www.youtube.com/watch?v=XXXX&t=812s
```

Open each link. Watch the actual moment. **Do this on three different
episodes.** If fewer than 60% of the picks are genuinely postable, do not build
anything else — change the prompt in `backend/pipeline/select.py` and run it
again. Nothing downstream can rescue a bad pick.

Only the prompt and the rubric in `select.py` should change during this loop.
If you find yourself editing the renderer to compensate, the picks are wrong.

## API

Backend on `:8000`. Full request/response shapes are in
[CLAUDE.md](CLAUDE.md#api-contract).

| Route | What |
|---|---|
| `POST /jobs` | `{"youtube_url": "..."}` or multipart `file=@video.mp4` |
| `GET /jobs/{id}` | Status, stage, progress 0-1, error |
| `GET /jobs/{id}/clips` | Rendered clips with download URLs |
| `GET /jobs?limit=20` | Recent jobs |
| `DELETE /jobs/{id}` | Remove a job, its stored clips, and its work dir (409 while running) |
| `GET /files/{job}/{name}` | Stream a clip (local storage only) |
| `GET /health` | Liveness |

Jobs run in FastAPI `BackgroundTasks` with a one-at-a-time semaphore around
rendering. That is the deliberate Phase 1 shortcut — swap in Celery + Redis
when concurrent users actually show up, not before. Jobs left `running` by a
restart are marked failed at boot rather than stranding the UI.

## Deploy

```bash
cp .env.example .env          # fill in keys, set STORAGE_BACKEND=r2
docker compose up -d --build
```

Caddy fronts both services on `:80`/`:443`, proxying `/api/*` to the backend
and everything else to Next.js. Set `SITE_ADDRESS=clips.example.com` for
automatic HTTPS.

Rendering is CPU-bound and single-threaded per job; a 4-core Hetzner box
(~€8/mo) handles roughly a 40-second clip per 15-20 seconds of wall time at
1080x1920.

### Storage

`STORAGE_BACKEND=local` keeps clips on disk and serves them from `/files`.
Set `STORAGE_BACKEND=r2` plus the `R2_*` variables to upload to Cloudflare R2
instead; URLs become presigned (7 days) unless you set `R2_PUBLIC_BASE_URL`.

## Running costs

| Item | Cost |
|---|---|
| Hetzner CPU VPS | ~$8/mo |
| Deepgram nova-2 | ~$0.25 per hour of audio |
| Claude (selection) | ~$0.05 per video |
| Cloudflare R2 | ~free at this scale |

## Tuning

Everything worth changing is an env var (see `.env.example`):

- `CLIP_MIN_SEC` / `CLIP_MAX_SEC` — length window, default 20-58s
- `MIN_HOOK_SCORE` — only render candidates at or above this, default 6
- `TARGET_CLIP_COUNT` — how many candidates to ask for, default 10
- `SELECT_MODEL` — defaults to `claude-sonnet-5`
- `MAX_CLIP_MB` — hard size budget; the encoder's bitrate cap is derived from it

## Tests

```bash
cd backend && pytest
```

85 tests covering the logic that is easy to get subtly wrong: boundary
snapping, caption timing and escaping, crop smoothing, bitrate budgeting, and
the API's validation and error paths. They do not need API keys or a GPU.

## Layout

See the table in [CLAUDE.md](CLAUDE.md#layout) — it is kept current because
that file is what future sessions read first.
