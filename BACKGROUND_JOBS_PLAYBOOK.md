# Practical Background Jobs Queue Handbook

This is an implementation-first guide for building background job systems in real applications. It is not tied to one project. If you follow this document, you can design and ship a production queue in most stacks.

## 1) What You Are Building

A complete queue system has these parts:

1. Producer: API/service that enqueues jobs.
2. Queue store or broker: where jobs wait.
3. Workers: process jobs safely.
4. Recovery: retries, timeout handling, dead-letter queue.
5. Observability: metrics, logs, alerts, replay tools.

If any part is missing, the system will fail at scale.

---

## 2) Choose the Right Queue Type

Use this decision table:

- Database queue (Postgres/MySQL): best for simple setup, moderate throughput, strong transactional needs.
- Redis queue: low latency, simple operations, good for bursty async tasks.
- RabbitMQ/SQS: durable task queues, delayed retries, good team-scale workloads.
- Kafka/PubSub stream: very high throughput, event streaming, replay-heavy architectures.
- Workflow engine (Temporal, Cadence): long-running business workflows with strict orchestration.

Start simple, but design so you can migrate later.

---

## 3) Non-Negotiable Design Rules

1. Every job must be idempotent.
2. Every external call must have timeout + retry policy.
3. Retries must use backoff (not constant hammering).
4. Jobs must have lease/heartbeat/timeout handling.
5. Failed jobs must end up in dead-letter with reason.
6. Queue depth and age must be measurable.
7. You need replay tooling before production launch.

---

## 4) Job Data Model (Database Queue)

Use this schema as baseline.

```sql
CREATE TYPE job_status AS ENUM (
  'queued',
  'processing',
  'succeeded',
  'failed',
  'dead_letter',
  'cancelled'
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  job_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  status job_status NOT NULL DEFAULT 'queued',
  priority INT NOT NULL DEFAULT 100,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 5,
  run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  lease_expires_at TIMESTAMPTZ,
  idempotency_key TEXT,
  last_error TEXT,
  correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jobs_pickup
  ON jobs(status, run_at, priority, created_at)
  WHERE status = 'queued';

CREATE UNIQUE INDEX uq_jobs_idempotency
  ON jobs(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

Why these fields matter:

- `run_at`: delayed jobs and retry backoff.
- `lease_expires_at`: worker crash recovery.
- `idempotency_key`: duplicate protection.
- `correlation_id`: trace one business request across systems.

---

## 5) Producer Pattern (API -> Queue)

Always enqueue inside a safe transaction boundary when job depends on DB writes.

### Option A: Transactional enqueue (single DB)

```python
async def create_order_and_enqueue(db, order_data):
    async with db.tx() as tx:
        order = await tx.order.create(data=order_data)
        await tx.jobs.create(
            data={
                "job_type": "send_order_email",
                "payload": {"order_id": order.id},
                "idempotency_key": f"order-email:{order.id}",
                "correlation_id": order.id,
            }
        )
    return order
```

### Option B: Transactional outbox (for external broker)

Write domain data + outbox event in same DB transaction, then separate dispatcher publishes to SQS/Rabbit/Kafka.

Use outbox when producer and queue are not the same storage.

---

## 6) Worker Claim Pattern (Safe Parallel Workers)

Multiple workers can run safely if claim is atomic.

```sql
WITH picked AS (
  SELECT id
  FROM jobs
  WHERE status = 'queued'
    AND run_at <= NOW()
  ORDER BY priority ASC, created_at ASC
  LIMIT $1
  FOR UPDATE SKIP LOCKED
)
UPDATE jobs j
SET status = 'processing',
    lease_expires_at = NOW() + INTERVAL '2 minutes',
    updated_at = NOW()
FROM picked
WHERE j.id = picked.id
RETURNING j.*;
```

This query is the core of scalable DB queues.

---

## 7) Worker Loop Template (Production-Ready)

```python
import asyncio
from datetime import datetime, timedelta

MAX_PARALLEL = 20
POLL_IDLE_SECONDS = 1.5


async def worker_loop(queue_repo, handlers, metrics, logger):
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def run_one(job):
        async with sem:
            await execute_job(job, queue_repo, handlers, metrics, logger)

    while True:
        jobs = await queue_repo.claim_ready(limit=MAX_PARALLEL)
        if not jobs:
            await asyncio.sleep(POLL_IDLE_SECONDS)
            continue

        await asyncio.gather(*(run_one(job) for job in jobs), return_exceptions=True)
```

Important:

- Use bounded concurrency (`Semaphore`).
- Keep polling short when idle.
- Claim + execute must be decoupled from enqueue throughput.

---

## 8) Execution Logic Template

```python
def retry_delay_seconds(attempt: int) -> int:
    # 1, 2, 4, 8, ... up to 5 minutes
    return min(300, 2 ** max(0, attempt - 1))


async def execute_job(job, repo, handlers, metrics, logger):
    handler = handlers[job.job_type]
    started = datetime.utcnow()
    try:
        await handler(job.payload, job.idempotency_key, job.correlation_id)
        await repo.mark_succeeded(job.id)
        metrics.inc("jobs_succeeded_total", {"type": job.job_type})
    except RetryableError as exc:
        attempts = job.attempts + 1
        if attempts >= job.max_attempts:
            await repo.mark_dead_letter(job.id, str(exc))
            metrics.inc("jobs_dead_letter_total", {"type": job.job_type})
        else:
            delay = retry_delay_seconds(attempts)
            await repo.requeue(job.id, attempts, delay, str(exc))
            metrics.inc("jobs_retried_total", {"type": job.job_type})
    except Exception as exc:
        await repo.mark_dead_letter(job.id, f"non-retryable:{exc}")
        metrics.inc("jobs_dead_letter_total", {"type": job.job_type})
    finally:
        elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        metrics.observe("job_duration_ms", elapsed_ms, {"type": job.job_type})
```

---

## 9) Idempotency: How to Actually Do It

Do not assume queue guarantees exactly-once. Most queues are at-least-once.

Practical idempotency patterns:

- Natural key upsert: `upsert by external_id`.
- Side-effect table: store `idempotency_key` + result hash.
- External API idempotency header (if supported).
- Payment/billing: write immutable ledger entries with unique constraints.

Rule: if job runs twice, final state must still be correct.

---

## 10) Retry Strategy That Works

Use error classes:

- Retryable: timeouts, 429, transient network, temporary dependency outage.
- Non-retryable: validation error, bad payload, permanent auth failure.

Backoff:

- Exponential + jitter for retryable failures.
- Cap maximum delay.
- Move to dead-letter after max attempts.

Never retry hot-loop without delay.

---

## 11) Dead-Letter and Replay Workflow

Minimum replay tooling:

1. List dead-letter by job type/date/error.
2. Inspect payload and stack/error.
3. Replay selected jobs to `queued` with attempts reset.
4. Cancel known-bad jobs permanently.

Keep an audit log of replay/cancel actions with operator identity.

---

## 12) Scheduling Models (Pick One)

- Fixed cron polling: easy, stable, slight latency.
- Continuous loop polling: better latency, still simple.
- Event-driven consumer: broker pushes immediately.

Large apps usually combine:

- Event-driven for high-priority user-facing tasks.
- Cron/periodic for sweepers and maintenance jobs.

---

## 13) Priority and Multi-Queue Strategy

For big applications, separate lanes:

- `critical`: customer-visible and SLA-sensitive.
- `default`: normal business async tasks.
- `bulk`: heavy backfills/imports/reports.

Do not let bulk jobs starve critical jobs.

Implementation options:

- Separate tables/queues.
- Single table with priority column and worker pools per lane.

---

## 14) Throughput Planning Formula

Use this to estimate worker count:

`required_concurrency ~= (incoming_jobs_per_sec * avg_job_seconds) / target_utilization`

Example:

- 50 jobs/sec incoming
- 0.4 sec average processing
- 70% target utilization

`(50 * 0.4) / 0.7 = 28.6` => start with 30 concurrent slots.

Then load-test and tune with real p95 values.

---

## 15) Observability You Must Add

Metrics:

- queue depth by status and type
- oldest queued age (queue lag)
- processing duration p50/p95/p99
- success, retry, dead-letter rates
- in-flight workers and claim rate

Structured logs for each job:

- `job_id`, `job_type`, `attempt`, `correlation_id`, `status`, `duration_ms`

Alerts:

- queue lag above threshold
- dead-letter spike
- worker heartbeat missing

---

## 16) Operational Runbook (Copy This)

When queue is growing fast:

1. Check lag and oldest queued age.
2. Check dependency health (DB, external APIs, network).
3. Check retry/dead-letter reasons.
4. Scale workers or lower per-worker concurrency if dependencies are overloaded.
5. Enable rate limiting per job type if downstream is unstable.

When many jobs are stuck in `processing`:

1. Find expired leases.
2. Move expired `processing` back to `queued` or `failed`.
3. Verify workers are renewing heartbeat/lease.

When dead-letter spikes:

1. Group by `last_error` and `job_type`.
2. Patch root cause.
3. Replay only affected safe subsets.

---

## 17) Testing Strategy (Practical)

Unit tests:

- handler idempotency
- retry classification
- backoff math

Integration tests:

- enqueue -> process -> success path
- retry then success path
- dead-letter path
- duplicate enqueue with same idempotency key

Failure tests:

- kill worker mid-job and verify lease recovery
- dependency timeout and retry behavior
- DB failover/reconnect behavior

Load tests:

- sustained steady load
- burst load
- mixed priority traffic

---

## 18) Security and Compliance

- Never put secrets in payload.
- Encrypt sensitive payload fields at rest.
- Apply least-privilege DB/broker credentials.
- Add payload retention and purge policy.
- Mask PII in logs and dead-letter views.

For payroll/finance/health domains, make replay actions auditable and approval-gated.

---

## 19) Migration Path (Small -> Big)

Use this evolution path:

1. Database queue + one worker.
2. Add retries, dead-letter, metrics, replay tools.
3. Add parallel workers + safe claim locking.
4. Split priority lanes.
5. Introduce broker for high-scale domains.
6. Add workflow engine for long business processes.

This avoids over-engineering early while keeping a clean scale path.

---

## 20) Minimal Implementation Checklist

Before production, confirm all are done:

- [ ] Job schema with status, attempts, run_at, lease, idempotency_key.
- [ ] Atomic claim query (`FOR UPDATE SKIP LOCKED` or broker equivalent).
- [ ] Bounded worker concurrency.
- [ ] Retryable vs non-retryable error classes.
- [ ] Exponential backoff + max attempts.
- [ ] Dead-letter + replay UI/CLI.
- [ ] Queue lag metrics + alerts.
- [ ] Graceful shutdown and lease recovery.
- [ ] Runbook documented and tested.

If these are in place, you have a real queue system, not just background scripts.

---

## 21) Quick Reference: Common Job Types

- Email/SMS dispatch
- Report generation
- File processing and OCR
- Search indexing
- Cache warming/invalidation
- Third-party sync
- Fraud/risk scoring
- AI summarization/classification

Each type should have separate handler, retry policy, SLA, and alert thresholds.
