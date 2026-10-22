"""Delete uploaded videos and work folders unused for RETENTION_DAYS; evaluations stay in the database.

A video whose evaluation is still running or waiting for QA review is kept however old it is, because the
report plays it. A stored result is still returned for a deleted video; re-running a failed evaluation, or
evaluating it under a new rubric, needs the file uploaded again.

    python -m scripts.cleanup [--dry-run]
"""

import argparse
import shutil
import time
from pathlib import Path

from app.config import settings
from app.db.database import SessionLocal
from app.db.reviews import awaiting_review


def last_used(path: Path) -> float:
    """Newest modification time of a file, or of a folder and everything in it."""
    paths = [path, *path.rglob("*")] if path.is_dir() else [path]
    return max(p.stat().st_mtime for p in paths)


def size_mb(path: Path) -> float:
    paths = path.rglob("*") if path.is_dir() else [path]
    return sum(p.stat().st_size for p in paths if p.is_file()) / 1e6


def delete_expired(now: float, dry_run: bool, keep: set[str]) -> list[Path]:
    """`keep` holds hashes of videos still waiting for review; uploads and work folders are named by hash."""
    cutoff = now - settings.retention_days * 86400
    candidates = [*settings.uploads_dir.glob("*"), *settings.work_dir.glob("*")]
    expired = [p for p in candidates if p.name.split(".")[0] not in keep and last_used(p) < cutoff]
    for path in expired:
        print(f"{'would delete' if dry_run else 'deleting'} {path} ({size_mb(path):.0f} MB)")
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return expired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    dry_run = parser.parse_args().dry_run
    with SessionLocal() as session:
        keep = awaiting_review(session)
    expired = delete_expired(time.time(), dry_run, keep)
    action = "would be deleted" if dry_run else "deleted"
    print(
        f"{len(expired)} uploads and work folders unused for {settings.retention_days} days {action}; "
        f"{len(keep)} videos kept until reviewed"
    )


if __name__ == "__main__":
    main()
