# Background Jobs Playbook (This Project + Reusable Patterns)

This guide explains how background jobs work in this FastAPI project, why this design was chosen, and how to reuse the same pattern for other domains (including payroll-style systems).

## 1) What You Have Right Now

This project uses a **database-backed queue** with a **scheduler-driven worker**.

- Queue storage: `AiAnalysis` table in Postgres (`prisma/schema.prisma`)
- Producer: API creates logs and enqueues analysis (`app/routers/logs.py` -> `queue_analysis_for_log`)
- Consumer: worker process runs APScheduler jobs (`app/background_jobs/worker.py` + `app/background_jobs/scheduler.py`)
- Processor: `process_analysis_for_log` does the actual work (`app/ai/analysis_service.py`)
- Retries and dead-letter behavior are built in (`retryCount`, `lastError`, `dead_letter` status)

This is a practical, low-infrastructure setup: no Redis/RabbitMQ/Kafka required.

---

## 2) End-to-End Flow

### Step A: Enqueue from API

When a user creates a log:

1. API stores the log (`db.log.create`)
2. API upserts `AiAnalysis` with `status = queued`

Code path:

- `app/routers/logs.py` (`create_log`)
- `app/ai/analysis_service.py` (`queue_analysis_for_log`)

### Step B: Worker picks queued jobs

Scheduler executes these jobs:

- Every 30s: `process_queued_analyses_job`
- Every 2m: `retry_failed_analyses_job`
- Every 5m: `mark_stuck_analyses_job`

Code path:

- `app/background_jobs/scheduler.py`
- `app/background_jobs/tasks.py`

### Step C: Process one item

`process_analysis_for_log` does:

1. Validate analysis row exists
2. Skip if already completed
3. Enforce retry limit
4. Mark `processing`
5. Load log data
6. Call AI (`generate_summary`)
7. Save result and mark `completed`
8. On error, increment retry and mark `failed` or `dead_letter`

Code path:

- `app/ai/analysis_service.py`
- `app/ai/generate_summary.py`

---

## 3) Queue State Machine

Normal path:

`queued -> processing -> completed`

Failure path:

`queued -> processing -> failed -> processing (retry) -> dead_letter`

Fields that enable this:

- `status`
- `retryCount`
- `lastError`
- `processingStartedAt`
- `updatedAt`

---

## 4) Concurrency Model (Important)

Current behavior is intentionally controlled:

- Batch size is limited by `AI_ANALYSIS_BATCH_SIZE` (default `5`)
- Each batch is processed sequentially (`for ... await ...`)
- Job-level locks prevent overlapping runs of the same task
- Scheduler `max_instances=1` also limits overlap per job

Effect:

- Stable and predictable
- Lower throughput under heavy bursts
- Better cost/rate-limit control for AI calls

---

## 5) Why This Approach Is Good

Use this setup when you want:

- Simple operations and low infrastructure overhead
- Reliability and recoverability (retry + dead-letter)
- Eventual consistency (results can arrive later)
- Cost control via polling + batching
- Easy debugging through database state

Good examples:

- Learning journal analysis
- Internal async enrichments
- Non-urgent notifications/report generation
- Small-to-medium workloads

---

## 6) Limits of This Approach

You should avoid this exact pattern for:

- Real-time workloads needing very low latency
- Very high throughput bursts with strict SLAs
- Critical money movement operations requiring stricter guarantees

For those cases, use stronger patterns (message broker, worker pools, idempotency keys, transactional outbox, workflow engine).

---

## 7) How to Run for Local Testing

1. Install dependencies:

```bash
uv sync
```

2. Configure `.env`:

- `DATABASE_URL`
- `OPENAI_API_KEY`

3. Apply schema and generate Prisma client:

```bash
uv run prisma migrate deploy
uv run prisma generate
```

4. Run API (terminal 1):

```bash
uv run uvicorn app.main:app --reload
```

5. Run worker (terminal 2):

```bash
uv run python -m app.background_jobs.worker
```

Notes:

- Background logs will appear periodically even when you do nothing because cron jobs are ticking.
- `RUN_SCHEDULER_IN_API=true` is optional for local-only single-process testing.

---

## 8) Tuning Knobs

Tune behavior with environment variables:

- `AI_ANALYSIS_BATCH_SIZE` (default `5`)
- `AI_ANALYSIS_MAX_RETRIES` (default `3`)
- `AI_ANALYSIS_PROCESSING_TIMEOUT_MINUTES` (default `15`)
- `RUN_SCHEDULER_IN_API` (default `false`)
- `SCHEDULER_TIMEZONE` (default `UTC`)

Practical tuning strategy:

1. Start conservative (`batch=5`)
2. Measure queue delay and error rates
3. Increase batch or concurrency gradually
4. Watch DB load, API latency, AI rate limits, and cost

---

## 9) Upgrade Path: Faster Throughput

If backlog becomes large, evolve in this order:

1. **Parallelize within batch safely**
   - Use `asyncio.Semaphore(N)` + `asyncio.gather`
   - Keep hard cap on concurrent AI calls
2. **Continuous polling worker**
   - Fetch next batch immediately if previous batch was full
   - Sleep briefly only when queue is empty
3. **Multi-worker scaling**
   - Introduce row-level locking / claim mechanism to avoid duplicate work
4. **Message broker**
   - Move to Celery/RQ/Arq/Kafka/RabbitMQ when scale/latency requires it

---

## 10) Reusable Job Types You Can Build

You can keep this same queue pattern for many jobs:

- Document parsing (extract text from uploads)
- Email generation and sending
- Data sync to third-party systems
- Fraud or anomaly scoring
- Report generation (daily/weekly)
- Content moderation pipelines

General job schema idea:

- `id`
- `job_type`
- `payload` (JSON)
- `status`
- `retry_count`
- `last_error`
- `scheduled_at`
- `processing_started_at`
- `created_at`, `updated_at`

---

## 11) Payroll Automation Mapping

Where this pattern fits in payroll:

- Attendance anomaly detection
- Missing document checks
- Payslip explanation generation
- Post-run reconciliation summaries
- Retryable sync to HR/BI systems

Where to use stricter architecture instead:

- Final salary disbursement trigger
- Ledger-critical write steps
- Deadline-critical cutoff execution

For critical payroll flows, add:

- Idempotency keys
- Transactional boundaries and row locks
- Strong audit trail
- Manual approval gates
- Dedicated alerting and SLO monitoring

---

## 12) Production Checklist

- Worker process supervised (systemd, Docker restart policy, Kubernetes)
- Health check and startup/shutdown logging
- Alerting on `failed`/`dead_letter` growth
- Metrics: queue depth, processing time, retry rate, completion rate
- Structured logs with job id, log id, and attempt number
- Cleanup/retention policy for old completed jobs
- Replay tooling for dead-letter items

---

## 13) Mental Model to Remember

Think of background jobs as 4 parts:

1. **Producer**: puts work in queue
2. **Queue**: stores state safely
3. **Worker**: picks and executes jobs
4. **Recovery**: retries, timeouts, dead-letter, monitoring

If these 4 are designed well, the system stays reliable even when external services fail.
