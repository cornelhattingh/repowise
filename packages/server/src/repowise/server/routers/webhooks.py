"""/api/webhooks — GitHub, GitLab, and Azure DevOps webhook handlers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from repowise.core.persistence import crud
from repowise.server.deps import get_db_session
from repowise.server.schemas import WebhookResponse

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_GITHUB_SECRET = os.environ.get("REPOWISE_GITHUB_WEBHOOK_SECRET", "")
_GITLAB_TOKEN = os.environ.get("REPOWISE_GITLAB_WEBHOOK_TOKEN", "")
_AZURE_SECRET = os.environ.get("REPOWISE_AZURE_WEBHOOK_SECRET", "")


def _verify_github_signature(body: bytes, signature_header: str) -> None:
    """Verify GitHub HMAC-SHA256 webhook signature."""
    if not _GITHUB_SECRET:
        return  # No secret configured — skip verification (dev mode)

    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature prefix")

    expected = hmac.new(
        _GITHUB_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(f"sha256={expected}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _verify_gitlab_token(token_header: str) -> None:
    """Verify GitLab webhook token."""
    if not _GITLAB_TOKEN:
        return  # No token configured — skip verification (dev mode)

    if not hmac.compare_digest(token_header, _GITLAB_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")


def _launch_webhook_job(request: Request, job_id: str) -> None:
    """Launch a webhook-triggered job as a background task."""
    import asyncio

    from repowise.server.job_executor import execute_job

    task = asyncio.create_task(
        execute_job(job_id, request.app.state),
        name=f"webhook-job-{job_id}",
    )
    bg_tasks: set = request.app.state.background_tasks
    bg_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        bg_tasks.discard(t)

    task.add_done_callback(_on_done)


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> WebhookResponse:
    """Receive and process GitHub webhook events.

    Verifies HMAC-SHA256 signature, stores the event, and enqueues a sync
    job for push events on the default branch.
    """
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, sig)

    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    payload = json.loads(body)

    # Try to find the repository by matching the clone URL
    repo_url = ""
    if "repository" in payload:
        repo_url = payload["repository"].get("clone_url", "")
        if not repo_url:
            repo_url = payload["repository"].get("html_url", "")

    # Store the webhook event
    event = await crud.store_webhook_event(
        session,
        provider="github",
        event_type=event_type,
        payload=payload,
        delivery_id=delivery_id,
    )

    # For push events: create a sync job
    if event_type == "push":
        ref = payload.get("ref", "")
        # Only sync pushes to the default branch
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/") :]
            # Find matching repo by URL
            from sqlalchemy import select

            from repowise.core.persistence.models import Repository

            result = await session.execute(
                select(Repository).where(Repository.url.contains(repo_url[:50]))
            )
            repo = result.scalar_one_or_none()
            if repo and branch == repo.default_branch:
                job = await crud.upsert_generation_job(
                    session,
                    repository_id=repo.id,
                    status="pending",
                    config={
                        "mode": "incremental",
                        "trigger": "webhook",
                        "before": payload.get("before", ""),
                        "after": payload.get("after", ""),
                    },
                )
                await crud.mark_webhook_processed(session, event.id, job_id=job.id)
                await session.commit()
                _launch_webhook_job(request, job.id)

    return WebhookResponse(event_id=event.id)


@router.post("/gitlab", response_model=WebhookResponse)
async def gitlab_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> WebhookResponse:
    """Receive and process GitLab webhook events.

    Verifies X-Gitlab-Token header, stores the event, and enqueues a sync
    job for push events on the default branch.
    """
    token = request.headers.get("X-Gitlab-Token", "")
    _verify_gitlab_token(token)

    body = await request.body()
    payload = json.loads(body)
    event_type = request.headers.get("X-Gitlab-Event", "unknown")

    event = await crud.store_webhook_event(
        session,
        provider="gitlab",
        event_type=event_type,
        payload=payload,
    )

    # For push events: create a sync job
    if event_type == "Push Hook":
        ref = payload.get("ref", "")
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/") :]
            project_url = payload.get("project", {}).get("web_url", "")

            from sqlalchemy import select

            from repowise.core.persistence.models import Repository

            result = await session.execute(
                select(Repository).where(Repository.url.contains(project_url[:50]))
            )
            repo = result.scalar_one_or_none()
            if repo and branch == repo.default_branch:
                job = await crud.upsert_generation_job(
                    session,
                    repository_id=repo.id,
                    status="pending",
                    config={
                        "mode": "incremental",
                        "trigger": "webhook",
                        "before": payload.get("before", ""),
                        "after": payload.get("after", ""),
                    },
                )
                await crud.mark_webhook_processed(session, event.id, job_id=job.id)
                await session.commit()
                _launch_webhook_job(request, job.id)

    return WebhookResponse(event_id=event.id)


def _verify_azure_basic_auth(authorization_header: str) -> None:
    """Verify Azure DevOps Service Hooks Basic auth credential.

    Azure DevOps encodes the shared secret as the password portion of
    HTTP Basic auth (``Authorization: Basic base64(username:password)``).
    Set REPOWISE_AZURE_WEBHOOK_SECRET to the password value you configured
    in the Service Hook subscription.
    """
    if not _AZURE_SECRET:
        return  # No secret configured — skip verification (dev mode)

    if not authorization_header.startswith("Basic "):
        raise HTTPException(status_code=401, detail="Missing Basic auth")

    try:
        decoded = base64.b64decode(authorization_header[6:]).decode("utf-8")
        _, _, password = decoded.partition(":")
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed Basic auth")

    if not hmac.compare_digest(password, _AZURE_SECRET):
        raise HTTPException(status_code=401, detail="Invalid credential")


@router.post("/azure", response_model=WebhookResponse)
async def azure_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> WebhookResponse:
    """Receive and process Azure DevOps Service Hook events.

    Verifies HTTP Basic auth (password = REPOWISE_AZURE_WEBHOOK_SECRET),
    stores the event, and enqueues a sync job for:

    - ``git.push`` — direct push to the default branch
    - ``git.pullrequest.merged`` — PR merged into the default branch

    Configure in Azure DevOps:
      Project Settings → Service Hooks → Web Hooks
      URL: https://<host>/api/webhooks/azure
      Basic auth password: value of REPOWISE_AZURE_WEBHOOK_SECRET
      Trigger: "Code pushed" and/or "Pull request merged"
    """
    auth = request.headers.get("Authorization", "")
    _verify_azure_basic_auth(auth)

    body = await request.body()
    payload = json.loads(body)
    event_type = payload.get("eventType", "unknown")

    event = await crud.store_webhook_event(
        session,
        provider="azure",
        event_type=event_type,
        payload=payload,
    )

    resource = payload.get("resource", {})
    repo_url = resource.get("repository", {}).get("remoteUrl", "")

    before = ""
    after = ""
    branch = ""

    if event_type == "git.push":
        # refUpdates is a list; use the first branch entry
        ref_updates = resource.get("refUpdates", [{}])
        if ref_updates:
            branch = ref_updates[0].get("name", "")
            before = ref_updates[0].get("oldObjectId", "")
            after = ref_updates[0].get("newObjectId", "")

    elif event_type == "git.pullrequest.merged":
        branch = resource.get("targetRefName", "")
        # after = merge commit on the target branch
        after = resource.get("lastMergeTargetCommit", {}).get("commitId", "")
        # before = source branch tip (used as diff base)
        before = resource.get("lastMergeSourceCommit", {}).get("commitId", "")

    # Only sync pushes/merges to the default branch
    if branch.startswith("refs/heads/") and repo_url:
        branch_name = branch[len("refs/heads/"):]

        from sqlalchemy import select

        from repowise.core.persistence.models import Repository

        result = await session.execute(
            select(Repository).where(Repository.url.contains(repo_url[:50]))
        )
        repo = result.scalar_one_or_none()
        if repo and branch_name == repo.default_branch:
            job = await crud.upsert_generation_job(
                session,
                repository_id=repo.id,
                status="pending",
                config={
                    "mode": "incremental",
                    "trigger": "webhook",
                    "before": before,
                    "after": after,
                },
            )
            await crud.mark_webhook_processed(session, event.id, job_id=job.id)
            await session.commit()
            _launch_webhook_job(request, job.id)

    return WebhookResponse(event_id=event.id)
