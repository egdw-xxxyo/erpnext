"""Off-host SFTP backup target: browse the remote manifest, push, pull.

Mirrors routes/actions.py (CSRF, audit-before-return) but does not go through
the generic commands.py dispatch — push/pull need a netrc file staged on the
host before the job command line can even be built (see sftp.py).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, commands, jobs, sftp, stats
from ..config import settings
from ..deps import SessionDep, client_ip
from ..sessions import Session
from ..sftp_config import NotConfigured
from ..templating import templates

router = APIRouter(prefix="/remote")


async def _csrf(request: Request, session: Session) -> None:
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")


def _fragment(request: Request, session: Session, **ctx) -> HTMLResponse:
	return templates.TemplateResponse(
		request, "partials/launched.html", {"settings": settings, "session": session, **ctx}
	)


@router.get("/backups", response_class=HTMLResponse)
async def remote_backups_panel(request: Request, session: SessionDep):
	force = request.query_params.get("force") == "1"
	remote = await sftp.remote_cache.get(session.conn, force=force)
	local = await stats.cache.get(session.conn)
	return templates.TemplateResponse(
		request,
		"partials/remote_backups.html",
		{
			"settings": settings,
			"session": session,
			"remote": remote,
			"git": local.get("git") or {},
		},
	)


@router.post("/push/{name}", response_class=HTMLResponse)
async def push(name: str, request: Request, session: SessionDep):
	await _csrf(request, session)
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	try:
		job_id = await asyncio.to_thread(sftp.push, session.conn, name, session.username)
	except NotConfigured as exc:
		return _fragment(request, session, error=str(exc))
	except jobs.JobBusy:
		return _fragment(request, session, error="Another job is already running. Wait for it to finish.")
	except Exception as exc:
		return _fragment(request, session, error=f"Could not start the push: {exc}")

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="backup-push",
		args={"name": name},
		job_id=job_id,
		result="launched",
	)
	return _fragment(request, session, job_id=job_id, label=f"Push backup {name}")


@router.post("/pull/{name}", response_class=HTMLResponse)
async def pull(name: str, request: Request, session: SessionDep):
	await _csrf(request, session)
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	try:
		job_id = await asyncio.to_thread(sftp.pull, session.conn, name, session.username)
	except NotConfigured as exc:
		return _fragment(request, session, error=str(exc))
	except jobs.JobBusy:
		return _fragment(request, session, error="Another job is already running. Wait for it to finish.")
	except Exception as exc:
		return _fragment(request, session, error=f"Could not start the pull: {exc}")

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="backup-pull",
		args={"name": name},
		job_id=job_id,
		result="launched",
	)
	return _fragment(request, session, job_id=job_id, label=f"Pull backup {name}")
