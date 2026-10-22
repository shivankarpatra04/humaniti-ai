import json
from collections.abc import Callable
from pathlib import Path

from app.config import settings
from app.pipeline import ingest
from app.pipeline.audio_metrics import audio_metrics, load_speech
from app.pipeline.transcribe import transcribe
from app.pipeline.video_facts import mmss, video_facts


def find_class_start(segments: list[dict], speech: list[tuple[float, float]]) -> float:
    """First speech after the last long silence early on, else the first burst of steady conversation."""
    # "we'll start in a minute or two" followed by silence is still the waiting room
    early_silences = [
        next_start
        for (_, end), (next_start, _) in zip(speech, speech[1:], strict=False)
        if next_start - end >= settings.class_start_silence_s and end < settings.class_start_search_s
    ]
    if early_silences:
        return early_silences[-1]
    needed = settings.class_start_segments
    for first, last in zip(segments, segments[needed - 1 :], strict=False):
        if last["start"] - first["start"] <= settings.class_start_window_s:
            return first["start"]
    return segments[0]["start"] if segments else 0.0


def prepare_class(
    video: Path, work: Path, tutor: str, set_stage: Callable[[str], None]
) -> tuple[list[dict], dict]:
    """Transcript and facts of a class, both cached in its work folder so a re-run only pays for the LLM."""
    set_stage("extracting")
    duration, has_audio = ingest.probe(video)
    if not has_audio:
        raise ValueError("the video has no audio stream, so the class cannot be evaluated")
    if duration > settings.max_video_s:
        limit = settings.max_video_s / 60
        raise ValueError(f"the video is {duration / 60:.0f} min long; the limit is {limit:.0f} min")
    # named by the threshold hash, so changing a threshold measures the facts again
    transcript, cached_facts = work / "transcript.json", work / f"facts.{settings.facts_version}.json"
    if transcript.exists() and cached_facts.exists():
        return json.loads(transcript.read_text(encoding="utf-8")), json.loads(cached_facts.read_text())

    audio = ingest.extract_audio(video, work)
    frames = ingest.extract_frames(video, work, duration)
    set_stage("transcribing")
    segments = transcribe(audio, work)
    facts = build_facts(video, frames, audio, segments, tutor, duration, set_stage)
    for outdated in work.glob("facts.*.json"):
        outdated.unlink()
    part = work / "facts.part"
    part.write_text(json.dumps(facts, indent=1))
    part.replace(cached_facts)
    return segments, facts


def build_facts(
    video: Path,
    frames: list[Path],
    audio: Path,
    segments: list[dict],
    tutor: str,
    duration: float,
    set_stage: Callable[[str], None],
) -> dict:
    """Facts the LLM must treat as ground truth."""
    set_stage("video_facts")
    # the video facts need the class start, which comes from the speech chunks
    samples, rate, speech = load_speech(audio)
    class_start = find_class_start(segments, speech)
    seen = video_facts(video, frames, tutor, class_start, duration)
    set_stage("audio_metrics")
    heard = audio_metrics(samples, rate, speech, segments, class_start)
    present_pct = seen["tutor_present_pct"]
    return {
        "duration": mmss(duration),
        "class_start": mmss(class_start),
        **seen,
        # only a tutor who is (almost) never in their own camera counts as "face not visible"
        "tutor_absent": None if present_pct is None else present_pct < settings.tutor_absent_below_pct,
        **heard,
    }
