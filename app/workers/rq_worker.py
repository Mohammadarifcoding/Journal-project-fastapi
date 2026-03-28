import logging
import os
import sys

from app.jobs.rq_compat import apply_windows_rq_patch
from app.jobs.queue import redis_conn

apply_windows_rq_patch()

from rq import SimpleWorker, Worker


def main():
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    queue_names = ["email"]

    worker_class = SimpleWorker if sys.platform == "win32" else Worker
    worker = worker_class(queues=queue_names, connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
