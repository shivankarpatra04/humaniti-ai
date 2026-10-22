import hashlib
import io

import pytest

from app.config import settings
from app.core.hashing import cache_key, sha256_file
from app.pipeline.ingest import save_upload


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)


def test_identical_uploads_share_one_file_and_hash():
    video = b"\x00\x00\x00\x18ftypmp42" * 50_000
    first, first_sha = save_upload(io.BytesIO(video), "B435 Intermediate.MP4")
    second, second_sha = save_upload(io.BytesIO(video), "copy.mp4")

    assert first_sha == second_sha == hashlib.sha256(video).hexdigest()
    assert first == second and first.name == f"{first_sha}.mp4"
    assert sha256_file(first) == first_sha
    assert [p.name for p in settings.uploads_dir.iterdir()] == [first.name]


def test_rejects_non_video_upload():
    with pytest.raises(ValueError, match="unsupported"):
        save_upload(io.BytesIO(b"x"), "notes.pdf")
    assert not settings.uploads_dir.exists()


def test_cache_key_changes_with_rubric_and_model():
    sha = hashlib.sha256(b"video").hexdigest()
    key = cache_key(sha, "r1", "claude-haiku-5-5")

    assert key == f"{sha[:32]}:r1:claude-haiku-5-5"
    assert cache_key(sha, "r2", "claude-haiku-5-5") != key
    assert cache_key(sha, "r1", "claude-sonnet-5-5") != key


def test_facts_version_follows_fact_thresholds_only(monkeypatch):
    version = settings.facts_version
    monkeypatch.setattr(settings, "llm_model", "another-model")
    monkeypatch.setattr(settings, "tesseract_cmd", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    assert settings.facts_version == version

    monkeypatch.setattr(settings, "logo_threshold", 0.8)
    assert settings.facts_version != version
