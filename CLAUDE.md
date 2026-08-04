# ClipViral

AI tool: long video in, viral 9:16 clips out.

## Rules

- Python 3.11, FastAPI, type hints everywhere
- All ffmpeg calls via subprocess with explicit args, log the command
- Never load full video into memory
- Clip selection lives ONLY in `pipeline/select.py`
- Test pipeline via `cli.py` before touching API
- Timestamps always in seconds (float), never strings

## Pipeline order

```
download → transcribe → select → render → upload
```

Each stage is a pure-ish function taking and returning dataclasses from
`backend/schemas.py`. Stages never reach into each other; `pipeline/run.py`
is the only place that wires them together.

## Quality bars

- Clips: 20-58s, never cut mid-sentence
- Captions: word-level sync, max 3 words per line
- Crop: face centered, smoothed, no jitter

## Running it

```bash
cd backend
pip install -r requirements.txt
python cli.py "https://youtube.com/watch?v=..."      # → work/<job>/candidates.json
python cli.py "..." --render                          # also renders mp4s
MOCK=1 python cli.py "anything"                       # no API keys, synthetic data
```

`MOCK=1` swaps Deepgram and Claude for deterministic fixtures and generates a
synthetic source video with ffmpeg. The whole chain runs offline — use it for
tests and for verifying wiring changes.

## API contract

Backend runs on `:8000`, frontend proxies to it. Both sides code against this.

| Route | Request | Response |
|---|---|---|
| `POST /jobs` | `{"youtube_url": "..."}` JSON, or multipart `file=@video.mp4` | `Job` |
| `GET /jobs/{id}` | — | `Job` |
| `GET /jobs/{id}/clips` | — | `Clip[]` |
| `GET /jobs` | `?limit=20` | `Job[]` |
| `GET /files/{job_id}/{name}` | — | streams the mp4 (local storage only) |
| `GET /health` | — | `{"status": "ok"}` |

```jsonc
// Job
{
  "id": "8f3c...",                 // uuid4 hex
  "status": "running",             // queued | running | done | failed
  "stage": "transcribing",         // queued|downloading|transcribing|selecting|rendering|uploading|done|failed
  "progress": 0.45,                // 0.0-1.0, monotonic
  "source_title": "Podcast ep 12",
  "source_url": "https://...",     // null for uploads
  "duration": 3612.0,              // seconds, null until probed
  "clip_count": 0,
  "error": null,                   // string when status=failed
  "created_at": "2026-08-04T16:00:00Z",
  "updated_at": "2026-08-04T16:04:00Z"
}

// Clip
{
  "id": "0c1a...",
  "job_id": "8f3c...",
  "title": "The 3am rule that changed his life",
  "hook_score": 9,                 // 1-10
  "reason": "Opens on a question, pays off at 0:41",
  "start": 812.5,                  // seconds into source
  "end": 856.0,
  "duration": 43.5,
  "url": "/files/8f3c.../clip-01.mp4",  // or presigned R2 URL
  "size_bytes": 8123456,
  "width": 1080,
  "height": 1920,
  "index": 1
}
```

Stage → progress mapping is fixed in `pipeline/run.py::STAGE_PROGRESS` so the
frontend can render a step list without guessing.

## Layout

| Path | Role |
|---|---|
| `backend/cli.py` | Terminal entry point, the thing you test with |
| `backend/pipeline/download.py` | yt-dlp → source video + 16kHz mono wav |
| `backend/pipeline/transcribe.py` | Deepgram nova-2 → word timestamps |
| `backend/pipeline/select.py` | Claude → clip candidates (the whole business) |
| `backend/pipeline/captions.py` | Word timings → ASS subtitle file |
| `backend/pipeline/crop.py` | Face track → smoothed 9:16 crop path |
| `backend/pipeline/render.py` | ffmpeg cut + crop + burn + loudnorm |
| `backend/pipeline/ffmpeg.py` | subprocess wrapper, logs every command |
| `backend/pipeline/run.py` | Wires the stages, owns progress reporting |
| `backend/main.py` | FastAPI app |
| `backend/models.py` | SQLAlchemy job/clip tables |
| `backend/storage.py` | Local disk or Cloudflare R2 |
| `frontend/` | Next.js app router, dark theme |

## Gotchas

- Cut clips with **re-encode, not stream copy** — stream copy snaps to
  keyframes and drifts the caption sync by up to a second.
- `-ss` goes **before** `-i` for a fast seek, but then `-ss` again after `-i`
  for frame accuracy. `pipeline/render.py` does both; don't "simplify" it.
- Deepgram returns words with punctuation attached when `punctuate=true`;
  caption line-breaking depends on that punctuation, so keep it on.
- The ASS `\k` karaoke tag is per-centisecond, not per-second. `captions.py`
  converts once, at the boundary.
