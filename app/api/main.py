import logging

from fastapi import FastAPI

from app.api import reviews, video
from app.api.routes import public, router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Humaniti AI")
app.include_router(router)
app.include_router(reviews.router)
app.include_router(video.router)
app.include_router(video.signed)
app.include_router(public)
