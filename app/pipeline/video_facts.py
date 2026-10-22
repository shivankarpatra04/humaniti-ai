import logging
import statistics
from pathlib import Path

import cv2
import numpy as np

from app.config import settings
from app.pipeline import name_cards
from app.pipeline.logo import logo_score, thumbnail

logger = logging.getLogger(__name__)

FACES = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def video_facts(video: Path, frames: list[Path], tutor: str, class_start: float, duration: float) -> dict:
    name_cards.check_tesseract()
    class_end = duration - settings.class_end_ignore_s
    hits, participants, logo_seconds, class_frames, views = _scan(frames, tutor, class_start, class_end)
    # the 15 s grid only says "off around here"; re-sampling every 2 s measures how long
    tutor_off = name_cards.tutor_off_seconds(video, frames[0].parent, tutor, hits, duration)
    step = settings.camera_off_step_s
    tutor_facts = _tutor_summary(views)
    logo_in_class = [s for s in logo_seconds if class_start <= s < class_end]
    bg_pct = 100 * len(logo_in_class) / class_frames if class_frames else 0.0
    present = bg_pct >= settings.logo_present_pct
    off_in_class = [s for s in tutor_off if class_start <= s < class_end]
    off_s = len(off_in_class) * step
    logger.info("video facts: logo %.0f%%, %d tutor name cards", bg_pct, len(tutor_off))

    return {
        "bg_8x8_pct": round(bg_pct, 1),
        "bg_8x8_present": present,
        "bg_8x8_first_seen": mmss(logo_seconds[0]) if logo_seconds else None,
        "tutor_camera_off_during_class_s": off_s,
        "tutor_camera_off_during_class": _ranges(off_in_class, step),
        # a few seconds off is a glitch or a quick fix; only a real stretch counts as teaching with camera off
        "tutor_camera_off_while_teaching": off_s > settings.camera_off_min_s + settings.camera_off_band_s,
        "tutor_camera_off_uncertain": abs(off_s - settings.camera_off_min_s) <= settings.camera_off_band_s,
        "tutor_camera_off_before_class_min": round(step * sum(s < class_start for s in tutor_off) / 60, 1),
        # the tutor can only be judged on frames showing their background; without it all is unknown
        **(tutor_facts if present else dict.fromkeys(tutor_facts)),
        "participants_seen_on_name_cards": sorted(participants),
    }


def _scan(frames: list[Path], tutor: str, class_start: float, class_end: float) -> tuple:
    """Look at every frame once: tutor name card, other name card, logo (then the tutor) or none."""
    tutor_off, participants, logo_seconds, class_frames, views = [], set(), [], 0, []
    for frame in frames:
        second = int(frame.stem)
        image = cv2.imread(str(frame))
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if name_cards.is_name_card(grey):
            name = name_cards.read_name_card(grey)
            if name_cards.is_tutor(name, tutor):
                tutor_off.append(second)
            elif name:
                participants.add(name)
            continue
        if name_cards.shows_tutor_off(grey, tutor):
            tutor_off.append(second)
            continue
        score, scale = logo_score(grey)
        in_class = class_start <= second < class_end
        class_frames += in_class
        if score < settings.logo_threshold:
            continue
        logo_seconds.append(second)
        if in_class:
            view = _tutor_video(image, scale)
            views.append((second, _face_brightness(view), _tutor_region_brightness(view)))
    return tutor_off, participants, logo_seconds, class_frames, views


def _tutor_summary(views: list[tuple[int, float | None, float | None]]) -> dict:
    """Lighting comes from the face when one is found, otherwise from the tutor's body."""
    faces = [face for _, face, _ in views if face is not None]
    bodies = [body for _, _, body in views if body is not None]
    face_brightness = statistics.median(faces) if faces else None
    body_brightness = statistics.median(bodies) if bodies else None
    out_of_frame = [second for second, _, body in views if body is None]
    frames = max(len(views), 1)
    lighting_ok = lighting_uncertain = None
    measured = None
    if faces:
        measured = face_brightness, settings.lighting_min_brightness
    elif bodies:
        measured = body_brightness, settings.tutor_region_min_brightness
    if measured:
        brightness, threshold = measured
        lighting_ok = brightness >= threshold
        lighting_uncertain = abs(brightness - threshold) <= settings.lighting_band
    return {
        "tutor_present_pct": round(100 * len(bodies) / frames, 1),
        "tutor_out_of_frame_intervals": _ranges(
            out_of_frame, settings.frame_interval_s, settings.out_of_frame_min_s
        ),
        "tutor_face_visible_pct": round(100 * len(faces) / frames, 1),
        "tutor_face_brightness": face_brightness and round(face_brightness),
        "tutor_region_brightness": body_brightness and round(body_brightness),
        "lighting_ok": lighting_ok,
        "lighting_uncertain": lighting_uncertain,
    }


def _tutor_video(image: np.ndarray, scale: float) -> np.ndarray:
    """The tutor's camera image: the whole frame, or the thumbnail enlarged for the detectors."""
    if scale > settings.logo_full_frame_scale:
        return image
    upscale = settings.thumbnail_upscale
    return cv2.resize(thumbnail(image), None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)


def _face_brightness(view: np.ndarray) -> float | None:
    """Mean grey of the largest face, or None when no face is found."""
    grey = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    faces = FACES.detectMultiScale(
        grey, minNeighbors=settings.face_min_neighbors, minSize=(settings.face_min_size,) * 2
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda face: face[2] * face[3])
    return float(grey[y : y + h, x : x + w].mean())


def _tutor_region_brightness(view: np.ndarray) -> float | None:
    """Mean grey of the tutor's skin and clothes where they sit; None if nobody is there."""
    h, w = view.shape[:2]
    x0, y0, x1, y1 = settings.tutor_region_box
    region = view[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]
    # the 8x8 background, logo and Zoom labels are all colourless, while skin and clothes are not, even in
    # poor light; grey levels alone fail because the logo has mid-grey parts and a dark tutor is near black
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    person = (hsv[..., 1] >= settings.tutor_min_saturation) & (hsv[..., 2] >= settings.tutor_min_value)
    # opening removes JPEG colour fringes along the edges of the white logo
    kernel = np.ones((settings.tutor_open_px,) * 2, np.uint8)
    person = cv2.morphologyEx(person.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
    if person.mean() * 100 < settings.tutor_present_min_pct:
        return None
    return float(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)[person].mean())


def _ranges(seconds: list[int], step: int, min_s: int = 0) -> list[str]:
    """Seconds sampled every step as 'mm:ss-mm:ss' ranges lasting at least min_s."""
    ranges = []
    for second in seconds:
        if ranges and second - ranges[-1][1] <= step:
            ranges[-1][1] = second
        else:
            ranges.append([second, second])
    ranges = [(start, end + step) for start, end in ranges]
    return [f"{mmss(start)}-{mmss(end)}" for start, end in ranges if end - start >= min_s]
