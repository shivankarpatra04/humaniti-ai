# Project: Humaniti AI — Class Recording Quality Analyzer

Build **Humaniti AI**, a working Python application that evaluates recorded online classes and rates the tutor's class quality. Work in phases, run and verify each phase before moving to the next, and keep the code clean and modular.

## Decisions (agreed 2026-10-22, override anything below)
1. **ASR:** faster-whisper only. No sherpa-onnx, no `ASR_BACKEND` setting.
2. **History rule:** "same issue" = the same rubric criterion was `not_met` in ≥ 2 earlier *finished* evaluations of this tutor. Code counts it and passes `{criterion: count}` to Claude as a fact.
3. **Tests use SQLite.** JSON columns are `JSON().with_variant(JSONB, "postgresql")`. The Alembic migration is verified on Supabase separately.
4. **LLM cost:** Haiku 5.5 = $0.10 / 1M input, $0.50 / 1M output tokens (prompts ≤ 100k tokens). Expected ≈ ₹0.2 per video; target **≤ ₹0.5**. Log actual tokens and cost per evaluation.
5. **File names:** batch, level and date are parsed loosely from both styles (`B435_Intermediate_Part__-_2026-08-28_average_.mp4` and `B435 Intermediate Part  - 2026-08-28(average).mp4`). The label is read from the file name **only** in `scripts/evaluate_folder.py`, never in the app.
6. **Tutor name** is a required form field, normalised (case and whitespace) before lookup/storage.
7. **`bg_8x8_pct`** uses only non-name-card frames **after class start**.
8. **Label rules** are applied top-down, first match wins (Known quality issues → Weak → Average → Good → Excellent). Claude must return `rule_applied`.
9. **Pitch sampling** uses a fixed random seed (0).
10. **Cleanup:** after a successful save, delete `frames/` and `audio.wav`; keep `transcript.json`.
11. **Video-facts modules:** `pipeline/logo.py` (8×8 detection), `pipeline/name_cards.py` (camera-off OCR), `pipeline/video_facts.py` (combines them + face/lighting). `db/crud.py` may go up to ~200 lines. No new folders.
12. **Extra packages:** runtime `fastapi`, `uvicorn`, `streamlit`, `python-multipart`, `psycopg[binary]`, `alembic`; dev (`requirements-dev.txt`) `pytest`, `fakeredis`, `ruff`.
13. **Python 3.12** everywhere (`python:3.12-slim`, local venv).
14. **Git:** repo initialised; `samples/`, `data/`, `models/`, `.env`, `*.mp4` in `.gitignore` and `.dockerignore`. Commit at the end of every phase.
15. **No `storage.py`:** uploads are saved directly to `data/uploads/`.
16. The 8×8 logo templates are in `app/assets/`. The 5 labelled samples in `samples/` are for Phase 8 calibration only and are never committed.
17. **Tutor presence and lighting (Phase 4):** on logo frames, the lower-centre of the tutor's video (x 25–75 %, y 35–100 %, full frame or thumbnail) is checked for non-black, non-logo-white pixels. Facts: `tutor_present_pct`, `tutor_region_brightness`. `lighting_ok` uses face brightness when a face is found, otherwise the region brightness. Pitch variation uses `librosa.pyin` (voiced frames only) instead of `yin`; speech ratio, long silences and pitch clips come from the Silero VAD bundled with faster-whisper.
18. **Known-issues rule (for `rubric.md`, Phase 5):** "face not visible" means the tutor is absent or turned away (low `tutor_present_pct`), not a dark or cropped face. A dark or cropped face with the tutor present is a lighting / camera-position issue, an Average-level soft gap (as in the B435 28/08 Tutor B435-b feedback).
19. **Tutor absence (facts payload):** code computes `tutor_absent = tutor_present_pct < 10` (null when the background is absent); only `tutor_absent` feeds the Known-issues rule. Code also passes `tutor_out_of_frame_intervals`: merged mm:ss ranges of in-class logo frames with no tutor, at least 1 min long. Claude reports these as a camera-position / lighting soft gap, as in the B435 28/08 Tutor B435-b feedback. The presence detection itself uses colour saturation (an empty 8×8 background is colourless; skin and clothes are not), not grey levels.
20. **Gap-based label rules (Phase 5, replaces the label rules above and decision 8's order):** only `not_met` verdicts are gaps; `partly` is a suggestion and never moves the label. Process gaps: `rapport` (no rapport/intro before revision or teaching), `new_joiner_intro`, `camera_on` (camera off while teaching), `conclusion`. Soft gaps: `homework`, `energy` (low energy / not pleasant), `lighting` (lighting or camera position, incl. `tutor_out_of_frame_intervals`), `clarity`. Top-down, first match wins: K1 no 8×8 background; K2 `tutor_absent` and a process gap; K3 a `not_met` criterion repeated in ≥ 2 earlier evaluations; W1 ≥ 2 process gaps; A1 ≥ 2 gaps of either kind; G1 exactly 1 gap; E1 no gaps. Reason: in all 10 QA examples every Weak or Known class has 2+ process gaps, and B435 28/08 (no rapport, QA: Average) shows one process gap alone is not Weak. Code recomputes the label from Claude's verdicts (`decide_label`); on a mismatch it retries once, then uses the code's label and logs it. The criterion `camera_face` is renamed `camera_on` (camera off while teaching only); face visibility is the `tutor_absent` fact; camera position belongs to `lighting`. `individual_attention`, `bg_8x8` and `extras` are reported but never gaps.
21. **Camera-off and class-start measurement (Phase 5):** (a) every tutor camera-off seen on the 15 s grid is re-sampled every 2 s within ±15 s; `tutor_camera_off_during_class_s` is the measured total and `tutor_camera_off_while_teaching` is true at ≥ 30 s (`camera_off_min_s`); only then is `camera_on` `not_met`. (b) A camera-off during screen share is also detected: top-right thumbnail ≥ 90 % dark → OCR upscaled 4× → fuzzy tutor-name match → same re-sampling. None of the 5 samples contains such a tile (checked by eye on B482; B392's dark thumbnails are its space background), so it is covered by a synthetic test only. (c) `class_start` = first speech after the last silence ≥ 60 s that starts within the first 12 min, else the steady-talk rule. Silences come from the VAD speech chunks, not Whisper segments: Whisper stretched one stray word in B482 over the whole 04:24–06:50 silence. B482 class start moves from 04:11 to 06:50; its in-class camera-off is 14 s, so B482 is rated **Average (QA: Weak)**. Accepted, not tuned to this one video. (d) Haiku 5.5 verdicts vary run to run (no temperature control): over 4 runs per sample, `new_joiner_intro`, `energy`, `clarity` and `individual_attention` flip between neighbouring verdicts; B435 28/08 came out Weak 3 of 4 times (QA: Average) and B472 Excellent 3 of 4 (QA: Excellent). Majority agreement 3/5. Open for Phase 8.
22. **Stabler transcript verdicts (Phase 5):** `new_joiner_intro` gets the verdict `not_applicable` (counts as met, allowed for this criterion only); it is the default unless the transcript clearly shows a student attending for the first time ("first class", "new student", "welcome <name>", the tutor asking a student's name or age). For `rapport`, `new_joiner_intro` and `conclusion`, `not_met` needs an mm:ss timestamp and a short transcript quote in double quotes; otherwise the reply is retried once with the reason, and if it still lacks them that criterion becomes `partly` (logged), after which the label is recomputed by code. B482 Average (QA: Weak) is accepted, so the target is 4/5. Majority vote over several runs stays an option for Phase 8.
23. **Queue + API (Phase 6):** RQ needs `fork`, so Redis and the worker run in Docker Compose on Windows; the API runs locally or in Docker (compose publishes Redis on 6379). `POST /evaluations` is one multipart form with `tutor_name` and either `file` or `url` (plus `batch_id`, `class_date`, `level`, read from the file name for uploads when missing). Links: `source_url` is stored; a link already evaluated under the current rubric and model is returned without downloading. Otherwise the worker downloads and hashes it, and when that hash was evaluated before it copies the stored result (no LLM call, `cache_key` left empty, counted once in tutor history). `cache_key`, `video_sha256` and `video_path` are therefore nullable (migration 0002). `retry_count` stores the LLM retries per evaluation. Stages: `queued`, `downloading`, `extracting`, `transcribing`, `video_facts`, `audio_metrics`, `llm`, `saving`, `done` / `failed`; the error reads `Failed while <stage>: <reason>`. Bad link, no audio stream, video > 3 h (`max_video_s`) and Anthropic errors fail with a clear reason; re-submitting a failed file or link re-queues the same evaluation and reuses audio, frames and transcript. `video_path` is stored relative and POSIX-style so a local API and the dockerised worker agree. The final "reply still invalid" error no longer includes the validation detail, which can quote the transcript.
24. **API key and duplicate submits:** every route except `/health` needs the header `X-API-Key` equal to `API_KEY` from `.env` (constant-time compare); a missing or wrong key gives 401. The frontend gets only `API_URL` and `API_KEY` from its environment (compose passes `API_KEY` by variable substitution, not the whole `.env`). Two identical submits at once: when the insert hits the unique `cache_key`, or the new unique (`source_url`, `rubric_version`, `llm_model`) constraint (migration 0003), the API rolls back and returns the evaluation inserted first instead of a 500.
25. **Frontend (Phase 7):** `frontend/streamlit_app.py` (pages, API calls, polling every 5 s with an st.fragment) and `frontend/report.py` (the QA-style report and its Markdown export), both copied into the small frontend image. The frontend re-implements the three file-name regexes to pre-fill batch, date and level, because it must not import `app`. The report shows the summary, ✅ strengths and ❌ issues from Claude, suggestions from `partly`/`not_met` criteria, the criteria and key-facts tables (`participants_seen_on_name_cards` is left out because it lists student names), cost and tokens, JSON and Markdown downloads, and the transcript in a collapsed expander loaded from the new `GET /evaluations/{id}/transcript`. Tutor history marks criteria repeated as `not_met`.
26. **Evidence for a missing step (Phase 8, requested as "decision 25"; 25 was already the frontend):** the evidence rule pushed Haiku from `not_met` to `partly` on steps that are absent, because an absence cannot be quoted (B482 went to Good). The prompt now carries a "Class opening" block (the first 5 transcript lines from `class_start`) and a "Class closing" block (the last 5 lines). For `rapport`, valid `not_met` evidence is the first teaching line after class start with its timestamp, e.g. 06:51 "what are we doing in the last class". For `conclusion`, `not_met` means the class ends without a close (no goodbye, recap or next class), quoted from the closing lines; a goodbye and next class without a recap is `partly`. A first wording that made "no recap" alone `not_met` turned B472 (QA Excellent) into Good and was narrowed before the final passes.
27. **Adaptive majority vote (Phase 8):** Claude rates each class once. The label is on a boundary when one transcript-judged counted verdict (`rapport`, `new_joiner_intro`, `conclusion`, `homework`, `energy`, `clarity`) that is `partly` or `not_met` crossing the gap line would change the label; `met` verdicts never became `not_met` in any calibration run, and `camera_on` / `lighting` follow measured facts. On a boundary Claude rates it again; when the first two runs have the same `not_met` set a third run cannot change the label and is skipped, otherwise a third run is made. Each verdict is taken by majority (three different verdicts give `partly`), the text comes from the run closest to the majority, and code recomputes the label (`rule_applied` ends in "(vote of N runs)"). The class message is a cached block, so extra runs and retries read it at a tenth of the price. `runs_used` is stored per evaluation (migration 0004).
28. **Tutor names and calibration (Phase 8):** tutors keep the display name as first typed ("Tutor B482") and are matched on `name_key` (whitespace collapsed, case-folded; migration 0004). The facts are cached next to `transcript.json` and kept after cleanup, so a re-run only pays for the LLM (see decision 29 for the file name). `scripts/evaluate_folder.py` evaluates a folder without the database or tutor history, reads the QA label from the file name ("weeK" counts as Weak) and the tutor from `<folder>/tutors.json`, and saves verdicts to `data/calibration/`.
29. **Facts cache and retention:** the facts cache is `facts.<hash>.json`, where the hash covers every setting with a video-fact or audio prefix (`logo_`, `name_card_`, `camera_off_`, `tutor_`, `class_start_`, `pitch_`, ... in `config.FACT_PREFIXES`; not `tesseract_cmd`, which is a path). Changing a threshold measures the facts again, and the outdated file is removed when the new one is written. `RETENTION_DAYS` (default 30) drives `scripts/cleanup.py`, which deletes uploads and work folders whose newest file is older than that; evaluation rows stay. Uploading a video that is already stored refreshes its modification time.
30. **Logo scale floor (measurement bug, requested as "decision 29"; 29 was already the facts cache):** when the tutor shares a whole desktop the active-speaker thumbnail is smaller, and the logo sits at scale ~0.113 (B552, B558), below the old floor of 0.13, so both read as "no background" (K1). `logo_scale_min` is now 0.06. Checked on every 15 s frame of all 10 videos: B392 (no background, many shared boards) still has 0 matches, the samples gain no match below 0.13, and the 246 new small-scale matches (B516, B552, B558) are all the tutor's own logo thumbnail. One exception: a student's webcam tile in B491 at 43:45 scores exactly 0.75 (1 of 216 frames, no effect). No lichess or chesskid board matched.
31. **Uncertainty bands (requested as "decision 30"):** a measurement too close to its threshold to call counts as `partly`, never a gap. Lighting is uncertain when the brightness that decided `lighting_ok` (the face when one is found, otherwise the tutor region) is within ±5 (`lighting_band`) of its threshold; out-of-frame intervals still make `lighting` `not_met`. Camera-off is uncertain at 20–40 s (`camera_off_min_s` 30 ± `camera_off_band_s` 10); `tutor_camera_off_while_teaching` is now true only above 40 s. New facts `lighting_uncertain` and `tutor_camera_off_uncertain`; the rubric says `partly`, and code caps the verdict at `partly` on every run before the vote. No other rubric or threshold change: QA is not consistent on homework (B435-a Good vs B491 Excellent with the same gap), so individual labels are not chased.
32. **Rubric frozen, QA review mode (Phase 9):** the rubric is frozen at `e26e47f3` (`3c996a5f` after the example quotes were replaced with invented ones; same rules, samples still 4/5); no more label-chasing on samples or holdout. The criterion table shows the system is reliable on background, homework and individual attention and unreliable on rapport, new joiners and energy, which decide most labels, so the app is a QA assistant instead of an auto-labeller. Reports split criteria into **Measured** (`bg_8x8`, `camera_on`, `lighting`, `homework`, `individual_attention`) and **Needs QA check** (`rapport`, `new_joiner_intro`, `energy`, `conclusion`, `clarity`, plus `extras`, which is also judged from the transcript). The label is a **suggested label** with a confidence: high when no "Needs QA check" verdict, flipped on its own between gap and no gap, changes the label (K1 always; K2 with two process gaps; an Average resting on two measured gaps), otherwise low with the deciding criteria named. The report embeds the recording (`GET /evaluations/{id}/video`, served by the API to the frontend) and every evidence timestamp starts it there. QA reviews with `POST /evaluations/{id}/review`: `qa_label`, `qa_overrides` (only verdicts that differ from the system's are kept), `qa_comment`, `reviewer`, `reviewed_at` (migration 0005). Tutor history, and with it the repeated-issue rule K3, use the QA label and overrides when present; per video the reviewed evaluation counts, otherwise the newest. The Agreement page shows label and per-criterion agreement on reviewed evaluations by review week. Retention cleanup keeps every video whose evaluation is running or awaiting review.
33. **Honest agreement, streamed video, IST (Phase 9 fixes):** (1) The review form gives each "Needs QA check" criterion a *checked* tick, stored as `qa_checked` (migration 0006); choosing a verdict for one also checks it. Criterion agreement counts only checked criteria (agrees = checked and not overridden), so an unchecked criterion no longer counts as agreed; measured criteria have no tick and are left out. The Agreement page shows the number of checked criteria next to every agreement figure (overall, per criterion, per week, per review). (2) The browser streams the recording straight from the API: `GET /evaluations/{id}/video-url` (API key) returns `{url, expires}`, a link to `/evaluations/{id}/video?expires=…&token=…` where the token is an HMAC-SHA256 of the id and expiry keyed with `API_KEY`, valid 10 minutes (`video_url_ttl_s`). The video route accepts only that token (403 otherwise), not the API key, and answers Range requests with 206. Links point at `PUBLIC_API_URL` (default `http://localhost:8000`), the address browsers reach the API at. The frontend keeps a link until 2 minutes before it expires and no longer holds videos in memory. (3) Dates and times are shown in IST (Asia/Kolkata, fixed +05:30 since it has no daylight saving): the API returns `created_at`, `finished_at` and `reviewed_at` with a +05:30 offset, review weeks are IST weeks, and api and worker logs run with `TZ=Asia/Kolkata`. Times are still stored in UTC.

## Results (Phase 8, rubric 91957f7d, claude-haiku-5-5, 3 passes over samples/)

| video | QA label | pass 1 | pass 2 | pass 3 | runs per pass |
|---|---|---|---|---|---|
| B392 02/09 | Known quality issues | Known | Known | Known | 1, 1, 1 |
| B435 25/07 | Good | Good | Good | Good | 2, 2, 2 |
| B435 28/08 | Average | Average | Average | Average | 1, 3, 1 |
| B472 24/08 | Excellent | Excellent | Excellent | Excellent | 2, 2, 2 |
| B482 02/09 | Weak | Average | Average | Average | 2, 2, 2 |

- **Accuracy:** 4/5 in every pass. B482 is Average (QA: Weak), accepted in decision 21: its in-class camera-off is 14 s, below the 30 s rule, so it has one process gap (rapport) plus homework.
- **Stability:** no video changed label across the 3 passes. Verdicts that still vary without moving a label: `clarity` (B392, B435 28/08, B472), `individual_attention` (B435 25/07, never a gap) and `rapport` on B435 28/08 (resolved by the vote).
- **Cost:** $0.0616 for 15 evaluations, $0.0041 (≈ ₹0.36) per video on average, below the ₹0.5 target; 26 runs in total (1.7 per video) and 6 retries. A pass over the 5 samples takes about 3 minutes once transcripts and facts are cached; the first run of a 45-minute class takes about 11 minutes, mostly Whisper on CPU.
- **Caveat:** the rubric was written while looking at these 5 videos, so this is training accuracy. Judge further changes on holdout videos (see README, Calibration).

### Holdout (rubric e26e47f3, facts 517ad6b4, one pass each)

The 5 holdout videos (B441, B491, B516, B552, B558) were never used to write the rubric. Samples stay at 4/5 (same labels as above). Holdout: 1/5 before decisions 30-31 (B552 and B558 read as K1), 1/5 after, with different errors:

| video | QA | ours | cause |
|---|---|---|---|
| B441 | Known | Known | `tutor_absent` (present 0 %) and rapport not_met: K2 |
| B491 | Excellent | Average | camera off 196 s in the first 15 min (frames confirm the tutor's name card) and no homework; QA wrote "can share HWs" and still rated Excellent |
| B516 | Average | Excellent | face brightness 71, inside the lighting band, so lighting is partly; QA's only criticism, "clarity issues while keeping the background", is a visual artifact no fact measures (clarity partly) |
| B552 | Good | Average | rapport not_met (QA praised "good intro") and lighting not_met (face 65 and one out-of-frame minute; QA did not mention it) |
| B558 | Weak | Good | only homework not_met; QA's process gaps (intro, conclusion, new joiners) came out met, partly and not_applicable |

Cost: ₹0.51 (samples) and ₹0.47 (holdout) per video.

### Criterion-level agreement with QA (10 videos)

QA comments mapped to criteria (praised vs criticised) against our final verdicts; `partly` against a QA comment counts as "partly", unmentioned criteria are not scored. B441's "can't see his face" is compared with `tutor_absent`.

| criterion | QA comments | agree | partly | disagree | reliable? |
|---|---|---|---|---|---|
| background | 8 | 8 | 0 | 0 | yes (measured) |
| homework | 6 | 6 | 0 | 0 | yes, but QA does not always count it |
| individual attention | 6 | 5 | 1 | 0 | yes |
| rapport | 6 | 4 | 0 | 2 | mostly (B552 praised, B558 criticised: both wrong) |
| energy / pleasantness | 5 | 1 | 4 | 0 | direction right, but Haiku stops at partly where QA counts a gap |
| new joiners | 3 | 0 | 2 | 1 | no |
| camera | 2 | 1 | 0 | 1 | B482: 14 s off is below the rule, QA counted it |
| lighting | 1 | 1 | 0 | 0 | too few comments |
| conclusion | 1 | 0 | 1 | 0 | too few comments |
| clarity | 1 | 0 | 1 | 0 | too few comments; QA meant video clarity |

Measured criteria (background, homework, individual attention) are reliable. The process criteria that decide Weak (rapport, new joiners, conclusion) and the energy judgement are where the system and QA disagree, which explains the holdout labels: the label rules are only as good as these verdicts.

## Domain context (verified on real recordings)
- Recordings are online **chess classes for kids** by "Eight Times Eight", 30–90 minutes, one tutor + a small group of students, recorded in **Zoom "active speaker" view**.
- The recording always shows whoever is speaking:
  - tutor webcam (full screen),
  - a student webcam,
  - the tutor's shared screen (lichess / chesskid boards) with the active speaker as a **small thumbnail in the top-right corner** (approx. x 83–100%, y 0–17% of the frame),
  - a **black "name card"** (participant name in white text, centre of frame) when that speaker's camera is OFF.
- **"8×8 background" = the tutor's branded "Eight Times Eight" virtual background**: black background with a large white "8✕8" logo and the text "Eight Times Eight / NEVER GIVE UP". It is NOT a generic chessboard pattern. Lichess boards in screen share must NOT count as the background.
- The first 1–3 minutes are often a waiting room (name cards, silence) before the class starts; this must not count as "camera off".
- Classes include rapport building, revision, puzzle solving (tutor gives puzzles to students one by one: "this one goes to <name>"), teaching, practice games, homework (HW) and closing.
- The evaluation is about the **tutor's teaching behaviour and class process**, not chess content.

## What the app must do
1. Accept a class recording: **file upload** (mp4, mkv, webm) or a **link** (YouTube, Google Drive, direct URL via yt-dlp).
2. Accept metadata: Batch ID (e.g. B491), class date, tutor name, level (Beginner/Intermediate/Advanced). Pre-fill from file names like `B435_Intermediate_Part__-_2026-08-28_average_.mp4`.
3. Classify quality as **Excellent, Good, Average, Weak, or Known quality issues**.
4. Explain the assessment with **specific observations backed by timestamps or numbers**, never generic statements.
5. Save every evaluation in **Supabase Postgres**, keep tutor history, and use it for the "Known quality issues" decision.
6. Never pay twice for the same video: identical re-uploads return the stored result instantly.

## Architecture (follow exactly)
```
Upload ─► sha256(video) ─► cache_key in DB? ──Yes──► Backend API ─► Frontend
                                │
                                No
                                ▼
                     Redis queue (RQ job)  ◄── status: pending / processing / done / failed (+ stage text)
                                ▼
                 Worker: ffmpeg → Whisper (timestamped transcript)
                         + OpenCV/OCR video facts (8×8 background, tutor camera-off, face, lighting)
                         + audio metrics (energy, pace, silences)
                                ▼
                 DB: fetch this tutor's previous evaluations (history)
                                ▼
                 Claude Haiku 5.5 (transcript + facts + history + rubric) → label + reasons + evidence
                                ▼
                 DB: save cache_key + label + reasons + evidence + facts + cost
                                ▼
                        Backend API ─► Frontend (polls status)
```
- `cache_key = sha256(video)[:32] + ":" + RUBRIC_VERSION + ":" + LLM_MODEL` — changing the rubric or model triggers a fresh evaluation.
- Compute the hash **before** any processing (Whisper is the expensive step, not the LLM).
- Cache intermediate artefacts per video hash in `data/work/<hash>/` (audio.wav, frames/, transcript.json) so a failed job can be retried without re-transcribing.

## Video facts — computed by code, passed to the LLM as ground truth
Sample one frame every 15 s with fast keyframe seeks (`ffmpeg -ss T -i video -frames:v 1 -vf scale=640:-1`), not an fps filter (20× faster on 1080p).

| Fact | Method |
|---|---|
| `bg_8x8_pct`, `bg_8x8_present`, `bg_8x8_first_seen` | OpenCV multi-scale `matchTemplate` (TM_CCOEFF_NORMED) against the two **"8" glyphs of the logo** (`app/assets/logo_left8.png`, `logo_right8.png`, provided). Scales 1.0→0.13 so it also matches inside the top-right thumbnail. Threshold **0.75**. Present if ≥ 20 % of non-name-card frames match (logo is only visible while the tutor is the active speaker). Do NOT use the checker "✕" part of the logo as a template — it false-matches lichess boards. |
| `tutor_camera_off_during_class_min` + timestamps | Frames that are ≥ 97 % dark = name card → OCR the centre with **tesseract** (`--psm 6`, inverted, 3× upscale) → fuzzy-match against tutor name. Count only after class start (see below) and before the last minute. Report pre-class camera-off separately. |
| `tutor_face_visible_pct`, `tutor_face_brightness`, `lighting_ok` | On frames where the logo matched: if logo matched at scale ≥ 0.5 use the full frame, else crop the top-right thumbnail and upscale 4×; OpenCV Haar frontal face; brightness = mean grey of face box. `lighting_ok` = median ≥ 70. If background is absent → these are `null` (unknown). |
| `participants_seen_on_name_cards` | OCR names from non-tutor name cards (helps detect new joiners). |
| `class_start` | First moment with ≥ 4 transcript segments inside 60 s. |

Calibration on the 5 sample videos (use as regression tests):
- Logo score: frames with the logo 0.90–1.00, frames without ≤ 0.62.
- B392 Tutor B392: logo 0 % (space/earth virtual background) → "no background".
- B435 Tutor B435-b (28/08): logo ~72 %, face very dark / often out of frame → lighting issue.
- B435 Tutor B435-a (25/07): logo ~26 %, face clear, good lighting.
- B472 Tutor B472: logo ~44 %, students frequently become the active speaker (high participation), plays a ChessKid topic video.
- B482 Tutor B482: tutor name card for the first ~2 min, logo first seen at ~09:00.

## Audio metrics
`librosa` + `pyloudnorm`: integrated loudness (LUFS), speech ratio, words per minute, long silences (> 60 s), pitch variation (semitone SD via `librosa.yin` on ~40 random 4-s speech clips) and energy variation (RMS CV). Low pitch variation = flat / low-energy voice.

## Transcription
- `faster-whisper` (`small.en`, int8, CPU, `vad_filter=True`), output `[{start, end, text}]`.
- Expect noisy ASR (Indian-English kids, some Malayalam/Hindi phrases, Whisper repetition loops). Strip segments that repeat the same phrase > 5 times.

## LLM evaluation — Claude decides the label
- Model: **Claude Haiku 5.5** (`claude-haiku-5-5`), set in config. Use the `anthropic` SDK, temperature 0.
- **One call per video.** Send the **full** timestamped transcript (`[mm:ss] text`; a 60-min class ≈ 10k tokens) — do not chunk.
- Put the fixed part (role, rubric, decision rules, reference feedback, output schema) first in a **system block with `cache_control`** (prompt caching); the per-video part (facts JSON, tutor history, transcript) goes in the user message.
- Output JSON validated with `pydantic`; on validation failure retry once with the error appended.
- Record input/output tokens and cost per evaluation in the DB.
- The LLM must treat the video facts as ground truth and must not contradict them.

### Rubric (criteria the LLM must judge, each with verdict met / partly / not_met + timestamp + evidence + suggestion)
| # | Criterion | Evidence source |
|---|---|---|
| 1 | 8×8 background kept | fact `bg_8x8_present` |
| 2 | Tutor camera on + face visible | facts camera-off + face visible % |
| 3 | Lighting | fact `lighting_ok` |
| 4 | Intro & rapport building before revision/teaching | transcript first ~10 min |
| 5 | New joiners given time for self-introduction | transcript + `participants_seen_on_name_cards` |
| 6 | Individual attention — considers everyone, calls students by name, asks each one | transcript (whole class) |
| 7 | Homework given | transcript (mostly last ~10 min) |
| 8 | Proper conclusion / recap | transcript last ~10 min |
| 9 | Energetic, pleasant, happy interaction with kids | transcript tone + pitch/energy metrics |
| 10 | Clarity (audio + explanation) | loudness/silences + transcript |
| 11 | Extras (topic videos, interactive activities) | transcript |

### Label decision rules (write these into the system prompt; the LLM applies them and must name the rule it used)
- **Known quality issues** if ANY: no 8×8 background; background kept but tutor face not visible AND no rapport; or tutor history shows the same issue in ≥ 2 previous evaluations.
- **Weak** if a class-process step is missing: no rapport (goes straight to revision), new joiners not given self-intro time, tutor camera off while teaching, or both intro and conclusion missing.
- **Average**: process steps done, but 2+ soft gaps (low energy / not pleasant, poor lighting, clarity issues, no HW).
- **Good**: process steps done, at most one soft gap (e.g. no HW, or "needs more pleasant interaction").
- **Excellent**: rapport + everyone considered individually + HW given + pleasant/energetic; extras are a plus.
- Output also a one-line QA-style summary like the reference feedback.

### Output schema
```json
{
  "label": "Excellent|Good|Average|Weak|Known quality issues",
  "rule_applied": "string",
  "summary": "QA-style one-liner",
  "criteria": [
    {"criterion": "rapport", "verdict": "met|partly|not_met", "timestamp": "mm:ss",
     "evidence": "concrete quote or fact", "suggestion": "string"}
  ],
  "strengths": ["..."],
  "issues": ["..."]
}
```

### Reference feedback (few-shot, include verbatim in the system prompt)
```
Excellent:
1. B491 (29/06/2026) Tutor B491 — good one-to-one interaction, background was there, asked questions by calling individually, can play topic related videos and share HWs
2. B472 (24/08/2026) Tutor B472 — good rapport building, consider everyone in the class, individually asking questions, given HWs

Good:
1. B552 (02/09/2026) Tutor B552 — good intro and introduction, fixed 8*8 background, given HWs, need more pleasant interaction
2. B435 (25/07/2026) Tutor B435-a — good introduction, consider everyone in class, individually asking questions with everyone, should give HWs

Average:
1. B516 (03/09/2026) Tutor B516 — kept 8*8 background, individually considering each and every one in class in the beginning and during puzzle solving time also, given HWs, some clarity issues were there while keeping the background
2. B435 (28/08/2026) Tutor B435-b — background was there, one-to-one consideration was there, individually ask questions, need more energetic communication and more pleasant interaction, should give HWs, can sit in space where have light

Weak:
1. B558 (05/09/2026) Tutor B558 — kept background, need a better intro and conclusion, should give time for the new joiners for self-introduction, need more energetic and pleasant interaction
2. B482 (02/09/2026) Tutor B482 — kept background, ask questions individually, directly go to revision of previous class without proper rapport building, should give time for new joiners for self-introduction, sometimes tutor's camera was turned off while teaching

Known quality issues:
1. B392 (02/09/2026) Tutor B392 — interaction was there, but no background, need a better happy interaction with the kids, informed about the quality issues several times
2. B441 (26/09/2026) Tutor B441 — kept background but can't see his face, directly entered into class without proper rapport building, need a good happier communication
```

## Database — Supabase Postgres
- Use **SQLAlchemy 2.x + psycopg 3** with `DATABASE_URL` from `.env`, and **Alembic** for migrations (no `create_all` in production).
- Use the Supabase **Session pooler** connection string (port 5432, works on IPv4 networks). If the Transaction pooler (port 6543) is used, disable prepared statements (`prepare_threshold=None` in psycopg connect args).
- Tables:
  - `tutors` (id, name unique, created_at)
  - `evaluations` (id, cache_key unique, video_sha256, video_path, tutor_id FK, batch_id, class_date, level, status, stage, error, label, rule_applied, summary, result JSONB, facts JSONB, input_tokens, output_tokens, llm_cost_usd, rubric_version, llm_model, created_at, finished_at)
  - indexes on `cache_key`, `video_sha256`, `(tutor_id, class_date)`.
- Enable **Row Level Security** on both tables with no public policies (only the backend connects, with the DB password); never expose the connection string or service key to the frontend.
- `tutor_history(tutor_id)` returns previous finished evaluations (date, batch, label, not_met criteria) for the LLM prompt.
- Videos stay on local disk (`data/uploads/`).

## Tech stack
- Python 3.12. Use the name "Humaniti AI" for the FastAPI title, Streamlit page title/header, docker-compose project name (`humaniti-ai`) and README.
- **FastAPI** backend: `POST /evaluations` (multipart upload or JSON link + metadata) → returns existing result on cache hit or `{id, status: pending}`; `GET /evaluations/{id}` → status, stage, result; `GET /tutors/{name}/history`; `GET /health`.
- **Redis + RQ** job queue, `worker.py` entry point, job timeout 3 h, stage updates written to DB.
- **Streamlit** frontend: upload/link + metadata form, polls status with a progress/stage display, QA-style report, tutor history page.
- `ffmpeg`, `yt-dlp`, `faster-whisper`, `opencv-python-headless` (4.x, ships Haar cascades), `tesseract` (system package), `librosa`, `pyloudnorm`, `anthropic`, `pydantic` / `pydantic-settings`, `sqlalchemy`, `psycopg[binary]`, `alembic`, `rq`, `redis`.
- `docker-compose.yml` with redis, api, worker, frontend (Postgres is Supabase, not local).
- Do NOT use: mediapipe, pyannote, vision-LLM calls, rule-based transcript scoring.

## Folder structure
```
humaniti-ai/
├── README.md
├── requirements.txt
├── requirements-dev.txt    # pytest, fakeredis, ruff
├── pyproject.toml          # ruff + pytest settings
├── .env.example            # DATABASE_URL (Supabase), REDIS_URL, ANTHROPIC_API_KEY, LLM_MODEL, WHISPER_MODEL
├── docker-compose.yml      # redis + api + worker + frontend
├── Dockerfile              # includes ffmpeg + tesseract
├── alembic.ini
├── migrations/             # Alembic versions
├── app/
│   ├── config.py           # pydantic-settings: thresholds, model, paths
│   ├── api/
│   │   ├── main.py
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── core/
│   │   └── hashing.py      # sha256 + cache_key
│   ├── db/
│   │   ├── database.py     # engine/session for Supabase Postgres
│   │   ├── models.py       # Tutor, Evaluation
│   │   └── crud.py         # find_by_key, create, set_stage, save_result, save_error, tutor_history
│   ├── queue/
│   │   ├── connection.py   # Redis + RQ queue
│   │   └── tasks.py        # evaluate_job(evaluation_id) – runs the worker flow
│   ├── pipeline/
│   │   ├── ingest.py       # save upload / yt-dlp / ffmpeg audio + frames
│   │   ├── transcribe.py   # faster-whisper → segments
│   │   ├── logo.py         # 8×8 logo template matching
│   │   ├── name_cards.py   # name-card OCR, camera-off
│   │   ├── video_facts.py  # combines logo + name cards, face, lighting
│   │   ├── audio_metrics.py
│   │   └── facts.py        # assemble facts JSON for the LLM
│   ├── llm/
│   │   ├── client.py       # Anthropic call, prompt caching, retry, token/cost tracking
│   │   ├── prompt.py       # builds system + user messages, RUBRIC_VERSION = hash of rubric.md
│   │   ├── schemas.py      # pydantic output models
│   │   └── prompts/rubric.md
│   └── assets/
│       ├── logo_left8.png
│       └── logo_right8.png
├── worker.py
├── frontend/streamlit_app.py
├── scripts/evaluate_folder.py   # batch run; reads human label from file name; prints confusion matrix
├── tests/
│   ├── test_hashing.py
│   ├── test_video_facts.py      # logo / name-card detection on sample frames
│   ├── test_llm_schema.py       # schema validation + retry with a mocked client
│   └── test_api.py              # cache hit / miss flow with fakeredis + test DB
├── data/                        # gitignored: uploads/, work/<hash>/
└── models/                      # gitignored: Whisper model cache
```

## Report output
QA style, for example:
```
B482 | 02/09/2026 | Tutor B482 → WEAK   (rule: no rapport before revision)

✅ 8×8 background kept (21 % of frames, first seen 09:00)
❌ Camera off at class start (00:00–02:05 name card "Tutor B482")
❌ Went straight to revision at 02:20 without rapport building
❌ No self-intro time for new joiners (two joined ~04:00)
✅ Puzzles given to students individually by name (student A, student B …)

Suggestions: …
```
Also show: criteria table with verdicts, key facts/metrics table, expandable transcript, tutor history, LLM cost. Allow download as JSON and Markdown.

## Build phases (verify each before continuing)
1. **Setup:** skeleton, requirements, config, `.env.example`, Dockerfile, docker-compose, README (ffmpeg + tesseract install, Supabase setup). Check ffmpeg/tesseract are available.
2. **Database:** SQLAlchemy models, Alembic initial migration, connect to Supabase, RLS enabled, CRUD functions + tests.
3. **Ingest + transcription:** upload/link → hash → audio + frames → transcript, cached per hash.
4. **Video facts + audio metrics:** implement and test against the calibration numbers above.
5. **LLM evaluation:** prompt with caching, pydantic schema, retry, cost tracking; test with a mocked client.
6. **Queue + API:** RQ worker, FastAPI routes, cache hit/miss flow, status/stage updates.
7. **Frontend:** Streamlit upload, status polling, report, tutor history.
8. **Calibration + polish:** `scripts/evaluate_folder.py` on the 5 labelled videos (expected labels are in the file names), confusion matrix, error handling (bad link, no audio, very long file), README usage.

## Constraints
- Runs locally on a CPU laptop; a 60-min class should finish in ~10–15 min with progress shown.
- Never hardcode keys or the DB URL; never send the DB URL or Anthropic key to the frontend.
- Recordings are of children: do not log transcript text at INFO level; keep raw videos out of git.
- Target LLM cost ≤ ₹0.5 per video (expected ≈ ₹0.2; Haiku 5.5, one call, prompt caching).
