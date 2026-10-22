"""The recording for the report's player, which the browser streams from the API through a signed link."""

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.routes import SessionDep, find_evaluation, require_api_key
from app.config import settings

router = APIRouter(dependencies=[Depends(require_api_key)])
# a <video> tag cannot send the X-API-Key header, so the video itself checks the link's token instead
signed = APIRouter()


def sign(evaluation_id: int, expires: int) -> str:
    key = settings.api_key.get_secret_value().encode()
    return hmac.new(key, f"{evaluation_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def video_path(session: Session, evaluation_id: int) -> str:
    path = find_evaluation(session, evaluation_id).video_path
    if path is None or not Path(path).exists():
        raise HTTPException(404, "The video was removed by the retention cleanup after review.")
    return path


@router.get("/evaluations/{evaluation_id}/video-url")
def get_video_url(evaluation_id: int, session: SessionDep) -> dict:
    video_path(session, evaluation_id)
    expires = int(time.time()) + settings.video_url_ttl_s
    query = urlencode({"expires": expires, "token": sign(evaluation_id, expires)})
    base = settings.public_api_url.rstrip("/")
    return {"url": f"{base}/evaluations/{evaluation_id}/video?{query}", "expires": expires}


@signed.get("/evaluations/{evaluation_id}/video")
def get_video(evaluation_id: int, session: SessionDep, expires: int = 0, token: str = "") -> FileResponse:
    """FileResponse answers Range requests with 206, so the player seeks without fetching the whole file."""
    expected = sign(evaluation_id, expires)
    if expires < time.time() or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "The video link is invalid or has expired; reload the report.")
    return FileResponse(video_path(session, evaluation_id))
