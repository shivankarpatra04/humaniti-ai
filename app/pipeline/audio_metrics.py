import logging
import random
import statistics
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm
from faster_whisper.vad import VadOptions, get_speech_timestamps

from app.config import settings
from app.pipeline.video_facts import mmss

logger = logging.getLogger(__name__)

Speech = list[tuple[float, float]]


def load_speech(audio: Path) -> tuple[np.ndarray, int, Speech]:
    """Samples, rate and (start, end) speech chunks; Whisper segments stretch over pauses, VAD does not."""
    samples, rate = librosa.load(str(audio), sr=None)
    chunks = get_speech_timestamps(samples, VadOptions())
    speech = [(chunk["start"] / rate, chunk["end"] / rate) for chunk in chunks]
    return samples, rate, speech


def audio_metrics(
    samples: np.ndarray, rate: int, speech: Speech, segments: list[dict], class_start: float
) -> dict:
    class_s = len(samples) / rate - class_start
    speech = [(start, end) for start, end in speech if start >= class_start]
    speech_s = sum(end - start for start, end in speech)
    words = sum(len(s["text"].split()) for s in segments if s["start"] >= class_start)
    gaps = [(end, next_start) for (_, end), (next_start, _) in zip(speech, speech[1:], strict=False)]
    clips = _speech_clips(samples, rate, speech)
    logger.info("audio metrics: %d speech chunks, %d clips", len(speech), len(clips))

    return {
        "loudness_lufs": round(float(pyloudnorm.Meter(rate).integrated_loudness(samples)), 1),
        "speech_ratio": round(speech_s / class_s, 2) if class_s > 0 else 0.0,
        "words_per_min": round(60 * words / speech_s) if speech_s else 0,
        "long_silences": [f"{mmss(a)}-{mmss(b)}" for a, b in gaps if b - a > settings.long_silence_s],
        "pitch_variation_semitones": _pitch_variation(clips, rate),
        "energy_variation_cv": _energy_variation(clips),
    }


def _speech_clips(samples: np.ndarray, rate: int, speech: list[tuple[float, float]]) -> list[np.ndarray]:
    """Up to pitch_clips random clips of pitch_clip_s seconds from inside speech, the same on every run."""
    clip_s = settings.pitch_clip_s
    long_enough = [(start, end) for start, end in speech if end - start >= clip_s]
    rng = random.Random(settings.pitch_seed)
    clips = []
    for start, end in rng.sample(long_enough, min(settings.pitch_clips, len(long_enough))):
        clip_start = rng.uniform(start, end - clip_s)
        clips.append(samples[int(clip_start * rate) : int((clip_start + clip_s) * rate)])
    return clips


def _pitch_variation(clips: list[np.ndarray], rate: int) -> float | None:
    """Median per-clip pitch SD in semitones; low means a flat voice."""
    spreads = []
    for clip in clips:
        # pyin, not yin: yin gives a pitch for pauses and noise too, which inflates the spread
        f0, voiced, _ = librosa.pyin(clip, fmin=settings.pitch_fmin_hz, fmax=settings.pitch_fmax_hz, sr=rate)
        f0 = f0[voiced]
        if len(f0) > 1:
            spreads.append(float(np.std(12 * np.log2(f0 / np.median(f0)))))
    return round(statistics.median(spreads), 2) if spreads else None


def _energy_variation(clips: list[np.ndarray]) -> float | None:
    if not clips:
        return None
    rms = np.concatenate([librosa.feature.rms(y=clip)[0] for clip in clips])
    return round(float(rms.std() / rms.mean()), 2) if rms.mean() > 0 else None
