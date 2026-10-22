import cv2
import numpy as np

from app.config import settings

# only the two "8" glyphs: the checkered "x" between them also matches lichess boards
TEMPLATES = [
    cv2.imread(str(settings.assets_dir / f"logo_{side}8.png"), cv2.IMREAD_GRAYSCALE)
    for side in ("left", "right")
]


def _scales(high: float, low: float) -> np.ndarray:
    steps = int(np.log(high / low) / np.log(settings.logo_scale_step)) + 1
    return high * settings.logo_scale_step ** -np.arange(steps)


def _resized(scale: float) -> list[np.ndarray]:
    return [cv2.resize(t, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) for t in TEMPLATES]


FULL_FRAME = [
    (scale, _resized(scale * settings.logo_search_downscale))
    for scale in _scales(settings.logo_scale_max, settings.logo_full_frame_scale)
]
THUMBNAIL = [
    (scale, _resized(scale)) for scale in _scales(settings.logo_full_frame_scale, settings.logo_scale_min)
]


def thumbnail(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = settings.thumbnail_box
    return frame[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]


def logo_score(grey: np.ndarray) -> tuple[float, float]:
    """Best match of the 8x8 logo glyphs as (score, scale): scale 1.0 is full screen, ~0.17 the thumbnail."""
    down = settings.logo_search_downscale
    small = cv2.resize(grey, None, fx=down, fy=down, interpolation=cv2.INTER_AREA)
    candidates = [(small, FULL_FRAME), (thumbnail(grey), THUMBNAIL)]
    best = (-1.0, 0.0)
    for region, scaled_templates in candidates:
        for scale, templates in scaled_templates:
            for template in templates:
                if template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
                    continue
                score = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1]
                best = max(best, (score, float(scale)))
    return best
