import difflib
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from app.config import settings
from app.pipeline.ingest import extract_frames_at
from app.pipeline.logo import thumbnail


def check_tesseract() -> None:
    """Without OCR every camera-off frame would look like an unknown name, so refuse to run instead."""
    if shutil.which(settings.tesseract_cmd) is None:
        raise RuntimeError(f"{settings.tesseract_cmd!r} not found: install tesseract or set TESSERACT_CMD")


def is_name_card(grey: np.ndarray, dark_pct: float = settings.name_card_dark_pct) -> bool:
    return (grey < settings.name_card_dark_level).mean() * 100 >= dark_pct


def read_name_card(grey: np.ndarray, upscale: int = settings.ocr_upscale) -> str:
    h, w = grey.shape
    x0, y0, x1, y1 = settings.name_card_box
    centre = grey[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]
    # tesseract reads dark text on light background, and small Zoom text needs upscaling
    upscaled = cv2.resize(255 - centre, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    png = cv2.imencode(".png", upscaled)[1].tobytes()
    proc = subprocess.run(
        [settings.tesseract_cmd, "stdin", "stdout", "--psm", "6"], input=png, capture_output=True
    )
    if proc.returncode:
        raise RuntimeError(f"tesseract failed: {proc.stderr.decode(errors='replace').strip()[-300:]}")
    return " ".join(proc.stdout.decode(errors="replace").split())


def is_tutor(name: str, tutor: str) -> bool:
    ratio = difflib.SequenceMatcher(None, name.lower(), tutor.lower()).ratio()
    return ratio >= settings.name_match_ratio


def shows_tutor_off(grey: np.ndarray, tutor: str) -> bool:
    """The tutor's camera-off card: full screen, or a dark tile in the thumbnail while a screen is shared."""
    if is_name_card(grey):
        return is_tutor(read_name_card(grey), tutor)
    # the tile is small and a full-screen 8x8 logo leaves this corner black too, so the name match decides
    tile = thumbnail(grey)
    if not is_name_card(tile, settings.thumbnail_dark_pct):
        return False
    return is_tutor(read_name_card(tile, settings.thumbnail_upscale), tutor)


def tutor_off_seconds(
    video: Path, frames_dir: Path, tutor: str, hits: list[int], duration: float
) -> list[int]:
    """Seconds on a camera_off_step_s grid that show the tutor's name card, re-sampled around each hit."""
    window, step = settings.camera_off_window_s, settings.camera_off_step_s
    # one shared grid, so overlapping windows of neighbouring hits never count a second twice
    near_hits = {s for hit in hits for s in range(hit - window, hit + window + 1)}
    seconds = sorted(s for s in near_hits if s % step == 0 and 0 <= s < duration - 1)
    off = []
    for second, frame in zip(seconds, extract_frames_at(video, frames_dir, seconds), strict=True):
        grey = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
        if shows_tutor_off(grey, tutor):
            off.append(second)
    return off
