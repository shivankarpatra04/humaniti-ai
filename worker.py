import logging

from rq import Worker

from app.queue.connection import queue, redis

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # RQ forks a work horse per job, so this runs on Linux (Docker) only, not natively on Windows
    Worker([queue], connection=redis).work()
