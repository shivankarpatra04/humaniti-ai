import subprocess
import wave
from datetime import date

import cv2
import pytest

from app.config import settings
from app.pipeline.ingest import extract_audio, extract_frames, parse_file_name, probe
from app.pipeline.transcribe import strip_repeats


@pytest.mark.parametrize(
    "name, expected",
    [
        ("B435_Intermediate_Part__-_2026-08-28_average_.mp4", ("B435", "Intermediate", date(2026, 8, 28))),
        ("B392 Beginner Part  - 2026-09-02( quality issue ).mp4", ("B392", "Beginner", date(2026, 9, 2))),
        ("b472 intermediate Part  - 2026-08-24( excelent ).mp4", ("B472", "Intermediate", date(2026, 8, 24))),
        ("zoom_recording.mp4", (None, None, None)),
    ],
)
def test_parse_file_name(name, expected):
    parsed = parse_file_name(name)
    assert (parsed["batch_id"], parsed["level"], parsed["class_date"]) == expected


def test_strip_repeats_collapses_whisper_loops():
    segments = [{"start": 0, "end": 2, "text": "Sam, try the next puzzle."}]
    segments += [{"start": i, "end": i + 1, "text": "Thank you."} for i in range(2, 10)]
    segments += [{"start": 10, "end": 15, "text": "okay okay okay okay okay okay okay so the knight"}]
    segments += [{"start": 15, "end": 16, "text": "yes yes yes"}]

    kept = strip_repeats(segments)

    assert [s["text"] for s in kept].count("Thank you.") == settings.max_phrase_repeats
    assert kept[-2] == {"start": 10, "end": 15, "text": "okay so the knight"}
    assert kept[-1]["text"] == "yes yes yes"


@pytest.fixture
def video(tmp_path):
    """A 40 s 1080p clip with a stereo 48 kHz tone, like the Zoom recordings."""
    path = tmp_path / "class.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=5:duration=40",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=40", "-ac", "2", str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_extracts_audio_and_frames_once(video, tmp_path):
    work = tmp_path / "work"
    duration, has_audio = probe(video)
    audio = extract_audio(video, work)
    frames = extract_frames(video, work, duration)

    assert duration == pytest.approx(40, abs=0.5) and has_audio
    with wave.open(str(audio)) as wav:
        assert (wav.getframerate(), wav.getnchannels()) == (settings.audio_sample_rate, 1)
    assert [f.name for f in frames] == ["00000.jpg", "00015.jpg", "00030.jpg"]
    assert cv2.imread(str(frames[1])).shape[1] == settings.frame_width
    assert not list(work.rglob("*.part.*"))

    mtimes = [p.stat().st_mtime_ns for p in [audio, *frames]]
    extract_audio(video, work)
    extract_frames(video, work, duration)
    assert [p.stat().st_mtime_ns for p in [audio, *frames]] == mtimes
