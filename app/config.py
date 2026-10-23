import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# settings that change what the video facts and audio metrics measure; the facts cache is keyed by their hash
FACT_PREFIXES = (
    "audio_",
    "frame_",
    "logo_",
    "thumbnail_",
    "name_card_",
    "ocr_",
    "name_match_",
    "camera_off_",
    "face_",
    "lighting_",
    "tutor_",
    "out_of_frame_",
    "class_start_",
    "class_end_",
    "long_silence_",
    "pitch_",
)
# QA works in India; Asia/Kolkata has no daylight saving, so a fixed offset needs no tz database
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def to_ist(moment: datetime) -> datetime:
    """Times are stored in UTC; SQLite (the tests) returns them without the offset."""
    return moment.replace(tzinfo=moment.tzinfo or UTC).astimezone(IST)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr so the DB password and API key never show up in logs or reprs
    database_url: SecretStr
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: SecretStr
    # shared secret between the frontend and the API, sent as the X-API-Key header
    api_key: SecretStr
    # where the reviewer's browser reaches the API; the report's player streams the recording from it
    public_api_url: str = "http://localhost:8000"
    # signed video links stop working after this, so a link copied out of the page soon becomes useless
    video_url_ttl_s: int = 600
    llm_model: str = "claude-haiku-5-5"
    llm_input_usd_per_mtok: float = 0.10
    llm_output_usd_per_mtok: float = 0.50
    llm_cache_write_factor: float = 1.25
    llm_cache_read_factor: float = 0.1
    llm_effort: str = "medium"
    # thinking counts toward max_tokens, so leave room beyond the ~2k-token JSON
    llm_max_tokens: int = 16000
    whisper_model: str = "small.en"
    whisper_compute_type: str = "int8"
    job_timeout_s: int = 3 * 3600
    # classes run 30-90 minutes; anything much longer is a wrong file and would block the worker for hours
    max_video_s: int = 3 * 3600
    # same as Streamlit's --server.maxUploadSize; a 90-minute 720p recording is well under it
    max_upload_mb: int = 1024
    # more runs only when one verdict flipping between gap and no gap would change the label
    vote_runs: int = 3
    # only for cost reports
    inr_per_usd: float = 88.0

    data_dir: Path = Path("data")
    # uploads and work folders unused for this long are deleted by scripts/cleanup.py; the DB rows stay
    retention_days: int = 30
    models_dir: Path = Path("models")
    assets_dir: Path = Path(__file__).parent / "assets"

    # frames are only 640 px wide, so 720p is enough and downloads far less
    download_format: str = "bv*[height<=720]+ba/b[height<=720]/b"
    # Whisper works on 16 kHz mono; librosa and pyloudnorm read the same file
    audio_sample_rate: int = 16000
    frame_interval_s: int = 15
    frame_width: int = 640
    frame_jpeg_quality: int = 4
    # each frame is one short ffmpeg seek, so a few in parallel keep the CPU busy
    ffmpeg_workers: int = 4

    logo_threshold: float = 0.75
    logo_scale_max: float = 1.0
    # the thumbnail shrinks when the tutor shares a whole desktop; B552 and B558 show the logo at ~0.11
    logo_scale_min: float = 0.06
    # a match stays above the threshold within about 7% of the true scale, so 4% steps cannot miss it
    logo_scale_step: float = 1.04
    # logo only shows while the tutor is the active speaker, so 20% of frames already means "kept"
    logo_present_pct: float = 20.0
    # below this scale the logo can only be inside the active-speaker thumbnail, so only that box is searched
    logo_full_frame_scale: float = 0.3
    # the full-frame glyphs are large, so matching at half size finds them just as well and 4x faster
    logo_search_downscale: float = 0.5
    thumbnail_box: tuple[float, float, float, float] = (0.83, 0.0, 1.0, 0.17)
    thumbnail_upscale: int = 4

    # Windows installs Tesseract outside PATH; set TESSERACT_CMD to the full path of tesseract.exe there
    tesseract_cmd: str = "tesseract"
    # Zoom's name card is grey ~28 with a white name; dark screen shares sit around 40-50
    name_card_dark_level: int = 40
    name_card_dark_pct: float = 97.0
    name_card_box: tuple[float, float, float, float] = (0.2, 0.35, 0.8, 0.65)
    ocr_upscale: int = 3
    name_match_ratio: float = 0.7
    # name cards seen on the 15 s grid are re-sampled every 2 s within 15 s to measure the real off time
    camera_off_step_s: int = 2
    camera_off_window_s: int = 15
    camera_off_min_s: int = 30
    # within this many seconds of camera_off_min_s the total is too close to call: partly, never a gap
    camera_off_band_s: int = 10
    # a camera-off tile fills the whole thumbnail; the tutor's 8x8 thumbnail is ~60-70 % dark
    thumbnail_dark_pct: float = 90.0

    face_min_neighbors: int = 5
    face_min_size: int = 30
    lighting_min_brightness: float = 70.0
    # within this of the face or region threshold the lighting is too close to call: partly, never a gap
    lighting_band: float = 5.0
    # where the tutor sits in their own camera image
    tutor_region_box: tuple[float, float, float, float] = (0.25, 0.35, 0.75, 1.0)
    # an empty 8x8 background has under 0.5% pixels this colourful, a seated tutor 10-30%
    tutor_min_saturation: int = 50
    tutor_min_value: int = 20
    tutor_open_px: int = 5
    tutor_present_min_pct: float = 5.0
    tutor_absent_below_pct: float = 10.0
    # shorter gaps are the tutor leaning out for a moment, not a camera-position problem
    out_of_frame_min_s: int = 60
    # skin of a well-lit tutor measures ~95, of the dark B435 28/08 tutor 20-40
    tutor_region_min_brightness: float = 60.0

    # a silence this long in the first 12 minutes means the class started after it
    class_start_silence_s: int = 60
    class_start_search_s: int = 720
    class_start_segments: int = 4
    class_start_window_s: int = 60
    class_end_ignore_s: int = 60

    long_silence_s: int = 60
    pitch_clips: int = 40
    pitch_clip_s: int = 4
    pitch_seed: int = 0
    pitch_fmin_hz: float = 65.0
    pitch_fmax_hz: float = 500.0
    # whisper loops on noisy audio and repeats one phrase many times
    max_phrase_repeats: int = 5

    history_repeat_min: int = 2
    # lines after class_start and before the end, quoted as evidence for rapport and conclusion
    opening_lines: int = 5

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def facts_version(self) -> str:
        values = self.model_dump()
        thresholds = {name: value for name, value in values.items() if name.startswith(FACT_PREFIXES)}
        return hashlib.sha256(json.dumps(thresholds, sort_keys=True).encode()).hexdigest()[:8]


settings = Settings()
