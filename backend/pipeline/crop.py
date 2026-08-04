"""Plan the 16:9 → 9:16 crop so the speaker stays centred.

Face detection is best-effort and degrades in three steps: MediaPipe if it is
installed, else an OpenCV cascade, else a static centre crop. A missing
detector must never fail a render -- a centred clip is worse than a tracked one
and far better than no clip.

The output is a :class:`CropPlan`, not an ffmpeg string; ``render.py`` owns
turning it into filter arguments.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg

log = logging.getLogger("clipviral.crop")

SAMPLE_FPS = 2.0
SAMPLE_WIDTH = 480

# Exponential smoothing on the face track. Low alpha = heavy smoothing; the
# camera should drift, never snap.
EMA_ALPHA = 0.18
# Ignore movement smaller than this fraction of frame width. Stops the crop
# vibrating around a stationary head.
DEADZONE_FRACTION = 0.012
# If the whole smoothed track stays inside this fraction of the width, pin the
# crop. A talking head barely moves and a fixed frame beats a drifting one.
STATIC_RANGE_FRACTION = 0.08


@dataclass
class CropPlan:
    crop_w: int
    crop_h: int
    y: int
    static_x: int | None = None
    keyframes: list[tuple[float, int]] = field(default_factory=list)
    detector: str = "none"

    @property
    def is_static(self) -> bool:
        return self.static_x is not None

    def write_sendcmd(self, path: str | Path) -> Path:
        """Emit an ffmpeg sendcmd script driving the crop's x over time.

        Values are already smoothed, so stepping between them at the sample
        rate is imperceptible; interpolating would mean building a piecewise
        expression hundreds of terms long for no visible gain.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{t:.3f} crop x {x};" for t, x in self.keyframes]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out


def _load_detector():
    """Return ``(name, fn)`` where fn maps an image to a face centre-x, or None."""
    try:
        import mediapipe as mp  # type: ignore

        detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        )

        def detect_mp(image) -> float | None:
            import cv2  # type: ignore

            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = detector.process(rgb)
            if not result.detections:
                return None
            # Largest box wins: the speaker is nearer the camera than the
            # audience or a poster on the wall behind them.
            best = max(
                result.detections,
                key=lambda d: d.location_data.relative_bounding_box.width
                * d.location_data.relative_bounding_box.height,
            )
            box = best.location_data.relative_bounding_box
            return (box.xmin + box.width / 2.0) * image.shape[1]

        return "mediapipe", detect_mp
    except Exception:  # noqa: BLE001 - any import/runtime failure means fall through
        pass

    try:
        import cv2  # type: ignore

        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            return "none", None

        def detect_cv(image) -> float | None:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            if len(faces) == 0:
                return None
            x, _, w, h = max(faces, key=lambda f: f[2] * f[3])
            return float(x) + w / 2.0

        return "opencv", detect_cv
    except Exception:  # noqa: BLE001
        return "none", None


def smooth_track(
    values: list[float | None],
    *,
    fallback: float,
    alpha: float = EMA_ALPHA,
    deadzone: float = 0.0,
) -> list[float]:
    """Fill gaps, then exponentially smooth with a deadzone."""
    if not values:
        return []

    filled: list[float] = []
    last = next((v for v in values if v is not None), None)
    if last is None:
        return [fallback] * len(values)
    for v in values:
        if v is not None:
            last = v
        filled.append(last)

    out: list[float] = []
    held = filled[0]
    current = filled[0]
    for v in filled:
        current = alpha * v + (1 - alpha) * current
        if abs(current - held) >= deadzone:
            held = current
        out.append(held)
    return out


def crop_window(
    src_width: int,
    src_height: int,
    out_width: int = 1080,
    out_height: int = 1920,
) -> tuple[int, int, int, int]:
    """Largest window with the output aspect that fits the source.

    Returns ``(crop_w, crop_h, y, max_x)``. Pure geometry, no I/O, so the
    dimension rules are testable without a video file.
    """
    target_aspect = out_width / out_height

    crop_w = int(src_height * target_aspect)
    crop_h = src_height
    if crop_w > src_width:
        crop_w = src_width
        crop_h = int(src_width / target_aspect)

    # h264 with yuv420p cannot encode odd dimensions.
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    y = max(0, (src_height - crop_h) // 2)
    max_x = max(0, src_width - crop_w)
    return crop_w, crop_h, y, max_x


def plan_crop(
    video_path: str | Path,
    *,
    start: float,
    duration: float,
    src_width: int,
    src_height: int,
    out_width: int = 1080,
    out_height: int = 1920,
) -> CropPlan:
    """Work out the crop window and where it should sit over time."""
    crop_w, crop_h, y, max_x = crop_window(src_width, src_height, out_width, out_height)
    centre_x = max_x // 2

    if max_x == 0:
        # Source is already at or narrower than the target aspect.
        return CropPlan(crop_w=crop_w, crop_h=crop_h, y=y, static_x=0, detector="n/a")

    name, detect = _load_detector()
    if detect is None:
        log.warning("no face detector available, using a centred crop")
        return CropPlan(crop_w=crop_w, crop_h=crop_h, y=y, static_x=centre_x, detector="none")

    tmp_dir = Path(tempfile.mkdtemp(prefix="clipviral-faces-"))
    try:
        frames = ffmpeg.extract_frames(
            video_path,
            tmp_dir,
            start=start,
            duration=duration,
            fps=SAMPLE_FPS,
            width=SAMPLE_WIDTH,
        )
        if not frames:
            return CropPlan(crop_w=crop_w, crop_h=crop_h, y=y, static_x=centre_x, detector=name)

        import cv2  # type: ignore

        scale = src_width / SAMPLE_WIDTH
        raw: list[float | None] = []
        for frame_path in frames:
            image = cv2.imread(str(frame_path))
            if image is None:
                raw.append(None)
                continue
            try:
                cx = detect(image)
            except Exception:  # noqa: BLE001 - a bad frame must not kill the job
                cx = None
            raw.append(cx * scale if cx is not None else None)

        detected = sum(1 for v in raw if v is not None)
        log.info("%s found a face in %d/%d sampled frames", name, detected, len(raw))
        if detected == 0:
            return CropPlan(crop_w=crop_w, crop_h=crop_h, y=y, static_x=centre_x, detector=name)

        smoothed = smooth_track(
            raw,
            fallback=src_width / 2.0,
            deadzone=src_width * DEADZONE_FRACTION,
        )

        # Convert face centres to crop origins, clamped to the frame.
        xs = [int(min(max(0.0, c - crop_w / 2.0), max_x)) for c in smoothed]
        spread = max(xs) - min(xs)
        if spread <= src_width * STATIC_RANGE_FRACTION:
            median = sorted(xs)[len(xs) // 2]
            log.info("face track spread %dpx, pinning crop at x=%d", spread, median)
            return CropPlan(crop_w=crop_w, crop_h=crop_h, y=y, static_x=median, detector=name)

        keyframes = [(i / SAMPLE_FPS, x) for i, x in enumerate(xs)]
        log.info("face track spread %dpx, animating crop over %d keyframes", spread, len(keyframes))
        return CropPlan(
            crop_w=crop_w,
            crop_h=crop_h,
            y=y,
            static_x=None,
            keyframes=keyframes,
            detector=name,
        )
    except Exception:  # noqa: BLE001
        # Reframing is an enhancement. Losing it costs a centred clip; letting
        # it raise costs the clip entirely.
        log.exception("face tracking failed, falling back to a centred crop")
        return CropPlan(
            crop_w=crop_w, crop_h=crop_h, y=y, static_x=centre_x, detector=f"{name}+failed"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
