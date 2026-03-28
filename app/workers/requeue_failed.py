from app.jobs.queue import redis_conn, email_queue
from app.jobs.rq_compat import apply_windows_rq_patch

apply_windows_rq_patch()

from rq.job import Job
from rq.registry import FailedJobRegistry


def requeue_failed_jobs(limit: int = 10):
    registry = FailedJobRegistry(queue=email_queue)
    job_ids = registry.get_job_ids()[:limit]

    for job_id in job_ids:
        try:
            job = Job.fetch(job_id, connection=redis_conn)
            job.requeue()
            print(f"Requeued job {job_id}")

        except Exception as e:
            print(f"Failed to requeue job {job_id}: {e}")
    return len(job_ids)


if __name__ == "__main__":
    count = requeue_failed_jobs()
    print(f"Requeued {count} failed email jobs")
