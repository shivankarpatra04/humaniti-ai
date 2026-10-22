import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import BinaryIO

import yt_dlp

from app.config import settings
from app.core.hashing import sha256_file

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm"}
FFMPEG = ["ffmpeg", "-nostdin", "-y", "-v", "error"]


def parse_file_name(name: str) -> dict:
    """Batch, level and class date from names like 'B435 Intermediate Part  - 2026-08-28(average).mp4'."""
    batch = re.search(r"(?<![a-z0-9])b\d+", name, re.IGNORECASE)
    level = re.search(r"beginner|intermediate|advanced", name, re.IGNORECASE)
    class_date = re.search(r"\d{4}-\d{2}-\d{2}", name)
    return {
        "batch_id": batch and batch.group().upper(),
        "level": level and level.group().title(),
        "class_date": class_date and date.fromisoformat(class_date.group()),
    }


def save_upload(stream: BinaryIO, file_name: str) -> tuple[Path, str]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"unsupported file type {suffix!r}, expected mp4, mkv or webm")
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=settings.uploads_dir, suffix=".part", delete=False) as part:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            part.write(chunk)
    return _keep(Path(part.name), digest.hexdigest(), suffix)


def download_link(url: str) -> tuple[Path, str]:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.uploads_dir) as download_dir:
        options = {
            "outtmpl": f"{download_dir}/video.%(ext)s",
            "format": settings.download_format,
            "merge_output_format": "mp4",
            "quiet": True,
            "noprogress": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        video = Path(info["requested_downloads"][0]["filepath"])
        return _keep(video, sha256_file(video), video.suffix)


def _keep(video: Path, sha256: str, suffix: str) -> tuple[Path, str]:
    """Videos are stored under their hash, so an identical re-upload reuses the stored file."""
    path = settings.uploads_dir / f"{sha256}{suffix}"
    if path.exists():
        video.unlink()
        # a fresh modification time keeps a video that is still in use away from scripts/cleanup.py
        path.touch()
    else:
        video.replace(path)
    return path, sha256


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def probe(video: Path) -> tuple[float, bool]:
    """Duration in seconds and whether the file has an audio stream."""
    entries = ["-show_entries", "format=duration:stream=codec_type", "-of", "json"]
    info = json.loads(_run(["ffprobe", "-v", "error", *entries, str(video)]))
    has_audio = any(stream["codec_type"] == "audio" for stream in info["streams"])
    return float(info["format"]["duration"]), has_audio


def extract_audio(video: Path, work: Path) -> Path:
    audio = work / "audio.wav"
    if audio.exists():
        return audio
    work.mkdir(parents=True, exist_ok=True)
    # written under another name first, so a killed job never leaves a half file that looks finished
    part = work / "audio.part.wav"
    mono = ["-vn", "-ac", "1", "-ar", str(settings.audio_sample_rate)]
    _run([*FFMPEG, "-i", str(video), *mono, str(part)])
    part.replace(audio)
    logger.info("extracted audio for %s", work.name)
    return audio


def remove_media(work: Path) -> None:
    """After a saved evaluation only the transcript and facts are kept; they are the slow steps."""
    shutil.rmtree(work / "frames", ignore_errors=True)
    (work / "audio.wav").unlink(missing_ok=True)


def extract_frames(video: Path, work: Path, duration: float) -> list[Path]:
    """One frame every frame_interval_s seconds, named by its second in the video (00915.jpg)."""
    frames = extract_frames_at(video, work / "frames", range(0, int(duration), settings.frame_interval_s))
    logger.info("extracted %d frames for %s", len(frames), work.name)
    return frames


def extract_frames_at(video: Path, frames_dir: Path, seconds) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(settings.ffmpeg_workers) as pool:
        return list(pool.map(lambda second: _extract_frame(video, frames_dir, second), seconds))


def _extract_frame(video: Path, frames_dir: Path, second: int) -> Path:
    frame = frames_dir / f"{second:05d}.jpg"
    if frame.exists():
        return frame
    part = frames_dir / f"{second:05d}.part.jpg"
    # -ss before -i seeks to the nearest keyframe instead of decoding from the start
    scale = f"scale={settings.frame_width}:-1"
    jpeg = ["-frames:v", "1", "-vf", scale, "-q:v", str(settings.frame_jpeg_quality)]
    _run([*FFMPEG, "-ss", str(second), "-i", str(video), *jpeg, str(part)])
    part.replace(frame)
    return frame
