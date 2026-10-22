import os
import time

from app.config import settings
from scripts.cleanup import delete_expired

DAY = 86400


def test_cleanup_deletes_only_what_was_unused_for_the_retention_period(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    now = time.time()
    old_video, new_video = settings.uploads_dir / "old.mp4", settings.uploads_dir / "new.mp4"
    unreviewed_video = settings.uploads_dir / "unreviewed.mp4"
    old_work, used_work = settings.work_dir / "old", settings.work_dir / "used"
    for folder in (old_work, used_work):
        folder.mkdir(parents=True)
    settings.uploads_dir.mkdir(exist_ok=True)
    transcripts = (old_work / "transcript.json", used_work / "transcript.json")
    for path in (old_video, new_video, unreviewed_video, *transcripts):
        path.write_text("x")
        os.utime(path, (now - 40 * DAY, now - 40 * DAY))
    for path in (old_work, used_work):
        os.utime(path, (now - 40 * DAY, now - 40 * DAY))
    # a recent re-run wrote new facts into an old work folder, and one video arrived yesterday
    (used_work / "facts.abc.json").write_text("{}")
    os.utime(new_video, (now - DAY, now - DAY))

    # a 40-day-old video whose evaluation QA has not reviewed yet stays for the report's player
    keep = {"unreviewed"}

    assert sorted(p.name for p in delete_expired(now, dry_run=True, keep=keep)) == ["old", "old.mp4"]
    assert old_video.exists()

    delete_expired(now, dry_run=False, keep=keep)

    assert not old_video.exists() and not old_work.exists()
    assert new_video.exists() and used_work.exists() and unreviewed_video.exists()
