from app.jobs.rq_compat import apply_windows_rq_patch
from dotenv import load_dotenv
from redis import Redis
import os

load_dotenv()

apply_windows_rq_patch()

from rq import Queue

redis_url = os.getenv("REDIS_URL")

if redis_url:
    r = Redis.from_url(redis_url)
else:
    r = Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        username=os.getenv("REDIS_USERNAME") or None,
        password=os.getenv("REDIS_PASSWORD") or None,
    )

email_queue = Queue("email", connection=r)
