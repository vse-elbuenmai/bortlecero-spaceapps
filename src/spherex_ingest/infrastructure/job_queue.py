"""Job dispatchers (local thread pool & Cloud Tasks) and worker OIDC auth verification."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from typing import Any

from google.api_core.exceptions import AlreadyExists

from spherex_ingest.domain.jobs import JobRecord, WorkerExecutionResult, WorkerTaskPayload

logger = logging.getLogger(__name__)


class WorkerAuthError(PermissionError):
    """Raised when a private worker invocation fails authentication or authorization."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class LocalThreadPoolJobDispatcher:
    """In-process bounded thread-pool dispatcher for durably persisted local jobs."""

    def __init__(
        self,
        worker_fn: Callable[[str], WorkerExecutionResult],
        *,
        max_workers: int = 2,
        retry_in_process: bool = True,
    ) -> None:
        self._worker_fn = worker_fn
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="spherex-job"
        )
        self._retry_in_process = retry_in_process
        self._futures: list[Future[WorkerExecutionResult]] = []

    def dispatch(self, job: JobRecord) -> None:
        future = self._executor.submit(self._run_with_retries, job.job_id)
        self._futures.append(future)
        # Prune completed futures to avoid unbounded memory growth.
        self._futures = [f for f in self._futures if not f.done()]

    def _run_with_retries(self, job_id: str) -> WorkerExecutionResult:
        while True:
            result = self._worker_fn(job_id)
            if not (self._retry_in_process and result.should_retry):
                return result

    def wait_for_idle(self, timeout: float | None = None) -> None:
        """Wait for all currently queued local futures to finish (useful in tests)."""
        while True:
            pending = [f for f in self._futures if not f.done()]
            if not pending:
                return
            for future in pending:
                future.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


class CloudTasksJobDispatcher:
    """Cloud-ready dispatcher enqueuing HTTP OIDC tasks to Google Cloud Tasks."""

    def __init__(
        self,
        *,
        queue_path: str,
        worker_url: str,
        service_account_email: str,
        audience: str | None = None,
        dispatch_deadline_seconds: int = 180,
        tasks_client: Any | None = None,
    ) -> None:
        self.queue_path = queue_path
        self.worker_url = worker_url.rstrip("/")
        self.service_account_email = service_account_email
        self.audience = audience or self.worker_url
        self.dispatch_deadline_seconds = dispatch_deadline_seconds
        self._tasks_client = tasks_client

    @classmethod
    @lru_cache(maxsize=4)
    def from_environment(
        cls,
        *,
        project_id: str,
        location: str,
        queue_id: str,
        worker_base_url: str,
        service_account_email: str,
        audience: str | None = None,
        dispatch_deadline_seconds: int = 180,
    ) -> CloudTasksJobDispatcher:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        queue_path = client.queue_path(project_id, location, queue_id)
        worker_url = f"{worker_base_url.rstrip('/')}/internal/worker/ingest"
        return cls(
            queue_path=queue_path,
            worker_url=worker_url,
            service_account_email=service_account_email,
            audience=audience or worker_url,
            dispatch_deadline_seconds=dispatch_deadline_seconds,
            tasks_client=client,
        )

    def _client(self) -> Any:
        if self._tasks_client is None:
            from google.cloud import tasks_v2

            self._tasks_client = tasks_v2.CloudTasksClient()
        return self._tasks_client

    def dispatch(self, job: JobRecord) -> None:
        payload = WorkerTaskPayload(
            job_id=job.job_id,
            request_key=job.request_key,
            correlation_id=job.correlation_id,
        ).model_dump_json()

        task: dict[str, Any] = {
            "name": f"{self.queue_path}/tasks/{job.job_id}",
            "http_request": {
                "http_method": "POST",
                "url": self.worker_url,
                "headers": {"Content-Type": "application/json"},
                "body": payload.encode("utf-8"),
                "oidc_token": {
                    "service_account_email": self.service_account_email,
                    "audience": self.audience,
                },
            },
            "dispatch_deadline": {"seconds": self.dispatch_deadline_seconds},
        }
        try:
            self._client().create_task(parent=self.queue_path, task=task)
        except AlreadyExists:
            # A prior submission may have succeeded before its response was lost.
            return
        logger.info(
            "Enqueued Cloud Task for job_id=%s correlation_id=%s",
            job.job_id,
            job.correlation_id,
        )


def _default_google_id_token_verifier(token: str, audience: str) -> dict[str, Any]:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return dict(
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=audience,
        )
    )


class OIDCWorkerAuthVerifier:
    """Verifies Cloud Tasks / IAM OIDC bearer tokens on the private worker endpoint."""

    def __init__(
        self,
        *,
        expected_audience: str,
        expected_service_account_email: str | None = None,
        require_cloud_tasks_header: bool = False,
        token_verifier: Callable[[str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.expected_audience = expected_audience
        self.expected_service_account_email = expected_service_account_email
        self.require_cloud_tasks_header = require_cloud_tasks_header
        self._token_verifier = token_verifier or _default_google_id_token_verifier

    def verify(self, authorization: str | None, headers: Mapping[str, str]) -> None:
        if self.require_cloud_tasks_header:
            task_name = headers.get("x-cloudtasks-taskname") or headers.get(
                "X-CloudTasks-TaskName"
            )
            if not task_name:
                raise WorkerAuthError(
                    "Missing required Cloud Tasks task identity header.",
                    status_code=403,
                )

        if not authorization or not authorization.startswith("Bearer "):
            raise WorkerAuthError("Missing bearer token.", status_code=401)

        token = authorization[len("Bearer ") :].strip()
        if not token:
            raise WorkerAuthError("Empty bearer token.", status_code=401)

        try:
            claims = self._token_verifier(token, self.expected_audience)
        except WorkerAuthError:
            raise
        except Exception as exc:
            raise WorkerAuthError("Invalid OIDC bearer token.", status_code=401) from exc

        if self.expected_service_account_email:
            email = claims.get("email")
            verified = claims.get("email_verified", True)
            if email != self.expected_service_account_email or not verified:
                raise WorkerAuthError(
                    "OIDC token service account is not authorized.",
                    status_code=403,
                )


class LocalDevWorkerAuthVerifier:
    """Permits local dev worker calls only when auth enforcement is explicitly disabled."""

    def __init__(self, *, allow_unauthenticated: bool) -> None:
        self.allow_unauthenticated = allow_unauthenticated

    def verify(self, authorization: str | None, headers: Mapping[str, str]) -> None:
        if not self.allow_unauthenticated:
            raise WorkerAuthError(
                "Worker authentication is required but no OIDC verifier is configured.",
                status_code=401,
            )


__all__ = [
    "CloudTasksJobDispatcher",
    "LocalDevWorkerAuthVerifier",
    "LocalThreadPoolJobDispatcher",
    "OIDCWorkerAuthVerifier",
    "WorkerAuthError",
    "json",
]
