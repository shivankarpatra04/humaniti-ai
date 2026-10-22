import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    with path.open("rb") as video:
        return hashlib.file_digest(video, "sha256").hexdigest()


def cache_key(video_sha256: str, rubric_version: str, llm_model: str) -> str:
    """A new rubric or model gives a new key, so the video is evaluated again."""
    return f"{video_sha256[:32]}:{rubric_version}:{llm_model}"
