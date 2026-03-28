from app.jobs.rq_compat import apply_windows_rq_patch
from dotenv import load_dotenv
from redis import Redis
import os

load_dotenv()

apply_windows_rq_patch()

from rq import Queue


def build_redis_connection() -> Redis:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return Redis.from_url(redis_url)

    return Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        username=os.getenv("REDIS_USERNAME") or None,
        password=os.getenv("REDIS_PASSWORD") or None,
    )


redis_conn = build_redis_connection()

email_queue = Queue(
    "email",
    connection=redis_conn,
    default_timeout=120,
)
