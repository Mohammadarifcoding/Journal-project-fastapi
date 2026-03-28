# Redis Email Queue Guide (No Job Loss Version)

This guide is for implementing a production-style email background job flow with FastAPI + Redis + RQ.

Your feedback is correct:

- duplicate-safe: yes
- deadlock-safe: yes
- job-loss-safe: not yet

This document fixes that gap with a **transactional outbox + relay worker** pattern.

---

## 1) Problem You Are Solving

If your API does this:

1. create user in DB
2. enqueue email to Redis

then job loss is possible when:

- user commit succeeds
- process crashes before enqueue
- Redis is temporarily unavailable

Result: user is created but no email job exists in queue.

---

## 2) Correct Architecture (No Job Loss)

Use this flow:

1. API transaction writes user + outbox row in same DB transaction.
2. API optionally tries immediate dispatch to Redis.
3. Separate relay worker continuously dispatches pending outbox rows to Redis.
4. RQ worker executes email jobs.

This guarantees no silent job loss because pending jobs remain durable in DB until dispatched.

```text
Client -> FastAPI -> DB Transaction
                 -> User row + Job(outbox:PENDING)
                         |
                         v
                  Outbox Relay Worker
                  claim lock -> enqueue to Redis -> mark COMPLETED
                         |
                         v
                      Redis Queue
                         |
                         v
                      RQ Worker
                         |
                         v
                      Send Email
```

---

## 3) Data Model for Durable Outbox

You already have a `Job` model in `prisma/schema.prisma`. Use it for outbox dispatch tracking.

Recommended meaning for statuses:

- `PENDING`: created, not yet dispatched to Redis
- `PROCESSING`: relay worker claimed lock
- `COMPLETED`: successfully dispatched to Redis
- `FAILED`: dispatch failed (retry scheduled or exhausted)

Important fields for no-loss + locking:

- `payload` (contains `user_id`, `email`, template)
- `retryCount`, `maxRetries`
- `scheduledAt` (next retry time)
- `lockedBy`, `lockedAt`

---

## 4) Step-by-Step Implementation

## Step A: Queue Connection (`app/jobs/queue.py`)

Use one central queue module.

```python
import os

from redis import Redis
from rq import Queue


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_redis_connection() -> Redis:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return Redis.from_url(redis_url)

    return Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        username=os.getenv("REDIS_USERNAME") or None,
        password=os.getenv("REDIS_PASSWORD") or None,
        db=int(os.getenv("REDIS_DB", "0")),
        ssl=_env_bool("REDIS_SSL", False),
    )


redis_conn = build_redis_connection()
email_queue = Queue("email", connection=redis_conn, default_timeout=120)
```

---

## Step B: RQ Email Job (`app/jobs/email_jobs.py`)

Keep your existing idempotency + lock strategy.

```python
import asyncio
import logging
import os

from rq import get_current_job

from app.email.email import send_registration_email
from app.jobs.queue import redis_conn

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = max(30, int(os.getenv("EMAIL_LOCK_TTL_SECONDS", "120")))
IDEMPOTENCY_TTL_SECONDS = int(
    os.getenv("EMAIL_IDEMPOTENCY_TTL_SECONDS", str(60 * 60 * 24 * 365))
)


def send_registration_email_job(user_id: str, email: str) -> dict[str, str]:
    job = get_current_job()
    job_id = job.id if job else "unknown"

    sent_key = f"idem:email:registration:{user_id}"
    if redis_conn.get(sent_key):
        return {"status": "skipped", "reason": "already_sent", "job_id": job_id}

    lock_key = f"lock:email:registration:{user_id}"
    lock = redis_conn.lock(lock_key, timeout=LOCK_TTL_SECONDS, blocking_timeout=1)
    if not lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "locked", "job_id": job_id}

    try:
        asyncio.run(send_registration_email(email))
        redis_conn.set(sent_key, "1", ex=IDEMPOTENCY_TTL_SECONDS)
        return {"status": "sent", "job_id": job_id}
    finally:
        if lock.owned():
            lock.release()
```

---

## Step C: Outbox Service (`app/jobs/outbox.py`)

This is the key no-loss layer.

```python
import logging
import os
import socket
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool
from rq import Retry

from app.db import db
from app.jobs.queue import email_queue

logger = logging.getLogger(__name__)

DISPATCH_BATCH_SIZE = max(1, int(os.getenv("EMAIL_OUTBOX_BATCH_SIZE", "20")))
DISPATCH_LOCK_TIMEOUT_SECONDS = max(
    30, int(os.getenv("EMAIL_OUTBOX_LOCK_TIMEOUT_SECONDS", "120"))
)
DEFAULT_MAX_DISPATCH_RETRIES = max(
    1, int(os.getenv("EMAIL_OUTBOX_MAX_RETRIES", "10"))
)
RETRY_INTERVALS_SECONDS = [10, 30, 120, 300, 600]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _backoff_seconds(attempt: int) -> int:
    base = 2 ** max(0, attempt - 1)
    return min(600, base)


def _worker_id(prefix: str) -> str:
    return f"{prefix}:{socket.gethostname()}:{uuid4().hex[:8]}"


async def create_registration_outbox_job(tx, user_id: str, email: str) -> str:
    job = await tx.job.create(
        data={
            "type": "EMAIL",
            "status": "PENDING",
            "payload": {
                "kind": "registration_email",
                "user_id": user_id,
                "email": email,
            },
            "retryCount": 0,
            "maxRetries": DEFAULT_MAX_DISPATCH_RETRIES,
            "scheduledAt": _utcnow(),
            "priority": 0,
        }
    )
    return job.id


async def _enqueue_to_redis(job_id: str, user_id: str, email: str) -> str:
    redis_job_id = f"email:outbox:{job_id}"
    try:
        job = await run_in_threadpool(
            email_queue.enqueue,
            "app.jobs.email_jobs.send_registration_email_job",
            user_id,
            email,
            job_id=redis_job_id,
            retry=Retry(max=len(RETRY_INTERVALS_SECONDS), interval=RETRY_INTERVALS_SECONDS),
            job_timeout=120,
            ttl=3600,
            result_ttl=86400,
            failure_ttl=604800,
        )
        return job.id
    except ValueError:
        # Same deterministic job already queued/executed
        return redis_job_id


async def dispatch_outbox_job(job_id: str, source: str = "api") -> bool:
    now = _utcnow()
    stale_cutoff = now - timedelta(seconds=DISPATCH_LOCK_TIMEOUT_SECONDS)
    worker_id = _worker_id(source)

    claimed = await db.job.update_many(
        where={
            "id": job_id,
            "type": "EMAIL",
            "status": {"in": ["PENDING", "FAILED", "PROCESSING"]},
            "AND": [
                {"OR": [{"scheduledAt": None}, {"scheduledAt": {"lte": now}}]},
                {"OR": [{"lockedAt": None}, {"lockedAt": {"lt": stale_cutoff}}]},
            ],
        },
        data={
            "status": "PROCESSING",
            "lockedBy": worker_id,
            "lockedAt": now,
        },
    )

    if claimed != 1:
        return False

    job = await db.job.find_unique(where={"id": job_id})
    if not job:
        return False

    payload = job.payload if isinstance(job.payload, dict) else {}
    user_id = str(payload.get("user_id", "")).strip()
    email = str(payload.get("email", "")).strip()
    if not user_id or not email:
        await db.job.update(
            where={"id": job_id},
            data={
                "status": "FAILED",
                "retryCount": (job.retryCount or 0) + 1,
                "lastError": "Invalid outbox payload",
                "scheduledAt": None,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        return False

    try:
        redis_job_id = await _enqueue_to_redis(job.id, user_id, email)
        await db.job.update(
            where={"id": job.id},
            data={
                "status": "COMPLETED",
                "result": {
                    "redis_job_id": redis_job_id,
                    "dispatched_at": now.isoformat(),
                    "source": source,
                },
                "lastError": None,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        return True
    except Exception as exc:
        next_retry = (job.retryCount or 0) + 1
        max_retries = job.maxRetries or DEFAULT_MAX_DISPATCH_RETRIES
        has_attempts_left = next_retry < max_retries
        next_run = now + timedelta(seconds=_backoff_seconds(next_retry)) if has_attempts_left else None

        await db.job.update(
            where={"id": job.id},
            data={
                "status": "FAILED",
                "retryCount": next_retry,
                "lastError": str(exc)[:500] or "Dispatch failed",
                "scheduledAt": next_run,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        logger.exception("Outbox dispatch failed job_id=%s source=%s", job.id, source)
        return False


async def dispatch_pending_outbox_jobs(source: str = "relay") -> int:
    now = _utcnow()
    stale_cutoff = now - timedelta(seconds=DISPATCH_LOCK_TIMEOUT_SECONDS)

    pending_jobs = await db.job.find_many(
        where={
            "type": "EMAIL",
            "OR": [
                {
                    "status": {"in": ["PENDING", "FAILED"]},
                    "OR": [{"scheduledAt": None}, {"scheduledAt": {"lte": now}}],
                },
                {
                    "status": "PROCESSING",
                    "lockedAt": {"lt": stale_cutoff},
                },
            ],
        },
        order={"createdAt": "asc"},
        take=DISPATCH_BATCH_SIZE,
    )

    dispatched = 0
    for item in pending_jobs:
        if await dispatch_outbox_job(item.id, source=source):
            dispatched += 1

    return dispatched
```

---

## Step D: Register Route Uses Transaction + Outbox

Update `app/routers/users.py` so user creation and outbox row are in the same transaction.

```python
from app.jobs.outbox import create_registration_outbox_job, dispatch_outbox_job


@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest):
    existing_user = await db.user.find_unique(where={"email": data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(data.password)

    async with db.tx() as tx:
        user = await tx.user.create(
            data={"email": data.email, "password": hashed_password, "name": data.name}
        )
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token({"sub": str(user.id)})

        await tx.user.update(
            where={"email": data.email},
            data={"refreshToken": refresh_token},
        )

        outbox_job_id = await create_registration_outbox_job(
            tx,
            user_id=str(user.id),
            email=user.email,
        )

    # Best-effort immediate dispatch (non-blocking fallback exists via relay)
    immediate_dispatch = await dispatch_outbox_job(outbox_job_id, source="api:register")

    return {
        "message": "User created successfully",
        "data": {"id": user.id, "email": user.email, "name": user.name},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "background": {
            "registration_email": "queued" if immediate_dispatch else "pending_dispatch",
            "outbox_job_id": outbox_job_id,
        },
    }
```

Why this fixes job loss:

- user and outbox job are atomic (same transaction)
- if Redis enqueue fails now, outbox row remains
- relay worker will retry until dispatched or exhausted

---

## Step E: Relay Worker (`app/workers/outbox_relay.py`)

This worker makes no-loss behavior active.

```python
import asyncio
import logging
import os

from app.db import db
from app.jobs.outbox import dispatch_pending_outbox_jobs


async def run() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    poll_seconds = float(os.getenv("EMAIL_OUTBOX_POLL_SECONDS", "2"))

    await db.connect()
    logger.info("Outbox relay started")
    try:
        while True:
            dispatched = await dispatch_pending_outbox_jobs(source="relay")
            if dispatched:
                logger.info("Outbox relay dispatched %s jobs", dispatched)
            await asyncio.sleep(poll_seconds)
    finally:
        await db.disconnect()
        logger.info("Outbox relay stopped")


if __name__ == "__main__":
    asyncio.run(run())
```

---

## Step F: RQ Worker (`app/workers/rq_worker.py`)

```python
import logging
import os

from rq import Worker

from app.jobs.queue import redis_conn


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    queue_names = [
        q.strip() for q in os.getenv("RQ_QUEUES", "email").split(",") if q.strip()
    ]

    worker = Worker(queues=queue_names, connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
```

---

## 5) Run Commands (3 Processes)

Terminal 1 (API):

```bash
uv run uvicorn app.main:app --reload
```

Terminal 2 (Outbox relay worker):

```bash
uv run python -m app.workers.outbox_relay
```

Terminal 3 (RQ worker):

```bash
uv run python -m app.workers.rq_worker
```

---

## 6) What Happens When (Operational Behavior)

### Redis is down during register

- user + outbox row still committed
- immediate dispatch fails
- status remains `PENDING`/`FAILED`
- relay retries later when Redis is back

### API crashes after DB commit

- outbox row still exists
- relay will pick it and enqueue later
- no email job loss

### Relay crashes after claiming lock

- row is `PROCESSING` with `lockedAt`
- after lock timeout, next relay run reclaims stale lock
- dispatch continues

### Duplicate requests/retries happen

- deterministic Redis job id reduces duplicate enqueues
- Redis idempotency key prevents duplicate email sends
- lock avoids concurrent duplicate sends

### Dispatch retries exhausted

- job remains `FAILED`
- inspect `lastError`
- replay manually by setting `status=PENDING`, `scheduledAt=now`, lock fields null

---

## 7) Manual Replay SQL (If Needed)

Replay one failed outbox job:

```sql
UPDATE "Job"
SET "status" = 'PENDING',
    "scheduledAt" = NOW(),
    "lockedBy" = NULL,
    "lockedAt" = NULL,
    "lastError" = NULL
WHERE "id" = '<job_id>'
  AND "type" = 'EMAIL';
```

Replay all failed email outbox jobs with retries left:

```sql
UPDATE "Job"
SET "status" = 'PENDING',
    "scheduledAt" = NOW(),
    "lockedBy" = NULL,
    "lockedAt" = NULL,
    "lastError" = NULL
WHERE "type" = 'EMAIL'
  AND "status" = 'FAILED'
  AND "retryCount" < "maxRetries";
```

---

## 8) Verification Checklist (No-Loss Proof)

1. Start API + relay + RQ worker.
2. Register a user and confirm outbox row created.
3. Stop Redis, register another user.
4. Confirm outbox row exists and is not lost.
5. Start Redis.
6. Confirm relay dispatches pending row to Redis.
7. Confirm RQ worker sends email.

If this passes, your system is now:

- duplicate-safe
- deadlock-safe
- job-loss-safe

---

## 9) Recommended Env Vars

```env
REDIS_URL=redis://default:password@host:port/0

RQ_QUEUES=email
EMAIL_JOB_TIMEOUT_SECONDS=120
EMAIL_LOCK_TTL_SECONDS=120
EMAIL_IDEMPOTENCY_TTL_SECONDS=31536000

EMAIL_OUTBOX_BATCH_SIZE=20
EMAIL_OUTBOX_POLL_SECONDS=2
EMAIL_OUTBOX_LOCK_TIMEOUT_SECONDS=120
EMAIL_OUTBOX_MAX_RETRIES=10
```

---

## 10) Production Notes

- Keep relay worker and RQ worker as separate processes.
- Add metrics for outbox pending count and oldest pending age.
- Alert when failed outbox jobs increase.
- Keep replay tooling available to operators.
- For critical domains, keep audit trail for replay actions.
