import json
import logging
import re
from pathlib import Path

from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

# a phrase followed by more than max_phrase_repeats copies of itself
REPEATED_PHRASE = re.compile(
    rf"\b(.{{2,}}?)(?:[\s,.!?]+\1\b){{{settings.max_phrase_repeats},}}", re.IGNORECASE
)


def transcribe(audio: Path, work: Path) -> list[dict]:
    """Segments [{start, end, text}], cached in transcript.json because Whisper is the slow step."""
    transcript = work / "transcript.json"
    if transcript.exists():
        return json.loads(transcript.read_text(encoding="utf-8"))

    model = WhisperModel(
        settings.whisper_model,
        device="cpu",
        compute_type=settings.whisper_compute_type,
        download_root=str(settings.models_dir),
    )
    # feeding earlier text back in makes Whisper loop on noisy kids' audio
    raw_segments, _ = model.transcribe(str(audio), vad_filter=True, condition_on_previous_text=False)
    segments = strip_repeats(
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in raw_segments
    )

    part = work / "transcript.part.json"
    part.write_text(json.dumps(segments, ensure_ascii=False, indent=0), encoding="utf-8")
    part.replace(transcript)
    logger.info("transcribed %s: %d segments", work.name, len(segments))
    return segments


def strip_repeats(segments) -> list[dict]:
    """Remove Whisper loops: a phrase repeated inside a segment, or one segment repeated many times."""
    kept = []
    run = 0
    for segment in segments:
        text = REPEATED_PHRASE.sub(r"\1", segment["text"])
        if not text:
            continue
        same_as_last = kept and _normalise(text) == _normalise(kept[-1]["text"])
        run = run + 1 if same_as_last else 1
        if run > settings.max_phrase_repeats:
            continue
        kept.append({**segment, "text": text})
    return kept


def _normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text).strip().lower()
