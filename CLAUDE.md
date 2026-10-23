# Humaniti AI — coding instructions

Follow these rules for every file in this project. They override default habits.

## 1. Write like a senior developer on a small team
- Code should read like it was written by one experienced person, not generated. Plain, direct, consistent.
- Name things after what they are in this domain: `tutor`, `batch_id`, `name_card`, `logo_score`, `class_start`. No `data`, `result2`, `temp`, `helper`, `manager`, `handler_util`.
- Prefer simple functions over classes. Use a class only when it holds state that several functions share (e.g. SQLAlchemy models, pydantic schemas).
- No design-pattern ceremony: no abstract base classes, factories, registries, or "provider interfaces" for a single implementation. Add an abstraction only when a second real implementation exists.
- Keep the happy path flat. Early `return` / `continue` instead of nested `if/else`.

## 2. Comments and docstrings
- Comment the **why**, never the **what**. `# logo only shows while the tutor is speaking, so 20% means present` is good. `# loop over frames` is noise.
- One-line docstring only where the function name is not enough. No Args/Returns blocks, no restating type hints.
- No banner comments (`# ===== SECTION =====`), no emoji, no "This module provides…" essays, no TODO lists left behind.
- No commented-out code.

## 3. Keep it short
- Target: each module under ~150 lines, each function under ~40 lines. If longer, it is probably doing two things.
- Don't write code "for later". No unused parameters, config keys, endpoints, or fallback branches for situations that cannot happen.
- Don't wrap one-liners in functions. Don't re-raise exceptions just to log them.
- Use the standard library and the listed packages before writing helpers. Don't reimplement what `pathlib`, `json`, `hashlib`, `subprocess`, `statistics`, `difflib` already do.
- Error handling only at boundaries: API routes, the worker job, external calls (ffmpeg, Anthropic, DB). Inside the pipeline let exceptions propagate to the job, which marks the evaluation `failed` with the message.
- Logging: one `logger = logging.getLogger(__name__)` per module, log stage changes and failures only. Never log transcript text or student names.
- Type hints on function signatures; skip them on obvious local variables.

## 4. Keep the application small
- Python 3.12 everywhere: the Docker image and the local venv (`py -3.12 -m venv .venv`; the machine default is 3.14).
- **Dependencies:** only those listed in the main prompt. Before adding any new package, ask. No pandas, numpy-heavy stacks, LangChain, LlamaIndex, Celery, or UI component libraries.
- Pin versions in `requirements.txt` with `==`. No dev tools inside the runtime requirements (put pytest etc. in `requirements-dev.txt`).
- Use `opencv-python-headless`, not `opencv-python`. Use the smallest Whisper model that is good enough (`small.en`, int8).
- Docker image: `python:3.12-slim`, install only `ffmpeg` and `tesseract-ocr` via apt with `--no-install-recommends`, clean apt lists, `pip install --no-cache-dir`. The root Dockerfile is shared by api and worker. Exception: `frontend/Dockerfile` (`python:3.12-slim`, only `frontend/requirements.txt`: streamlit + requests, no apt packages) keeps the frontend image small and free of secrets.
- Never commit videos, audio, frames, model files, `.env`, or `data/`. Keep a tight `.gitignore` and `.dockerignore`.
- Models (Whisper) download at first run into a cache volume, not into the image.
- Frames: 640 px wide JPEG, quality 4, one every 15 s. Delete `data/work/<hash>/frames/` and `audio.wav` after the evaluation is saved; keep only `transcript.json` and `facts.<hash>.json`.

## 5. Files and structure
- Stick to the folder structure in the main prompt. Do not add new top-level folders or extra layers (`services/`, `utils/`, `helpers/`, `common/`).
- No empty `__init__.py` boilerplate beyond what Python needs. No `__all__`.
- Config lives only in `app/config.py` (pydantic-settings). No magic numbers scattered in modules — thresholds come from settings. Exception: the frontend reads only `API_URL`, `API_KEY` (the shared X-API-Key secret) and `DEMO_PASSWORD` from the environment, because it must not import `app.config` (which needs the DB URL and Anthropic key).
- Prompts live in `app/llm/prompts/rubric.md`, not inside Python strings.

## 6. Tests
- Few and meaningful: hashing/cache key, logo + name-card detection on sample frames, LLM output schema with a mocked client, API cache hit/miss. No tests that only re-assert constants.
- Use plain `pytest` functions and fixtures, no test classes.

## 7. Before finishing any phase
- Run the code and the tests.
- Delete anything unused (imports, functions, files). Run `ruff check --fix` and `ruff format` (line length 110).
- Report the line count per file (`wc -l`) and the total; if a file grew past ~150 lines, simplify it before moving on.
