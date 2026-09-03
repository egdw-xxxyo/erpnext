"""Off-host FTP backup targets: browse each configured target's manifest,
push, pull. Mirrors routes/actions.py (CSRF, audit-before-return) but does
not go through the generic commands.py dispatch — push/pull need a netrc
file staged on the host before the job command line can even be built (see
ftp.py). Multi-target: a dev instance can hold prod's target too, to pull a
prod backup down for local testing without touching what dev itself pushes.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, commands, ftp, jobs, stats
from ..config import settings
from ..deps import SessionDep, client_ip
from ..ftp_config import NotConfigured, get_target, list_targets
from ..sessions import Session
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
	targets = list_targets()
	local = await stats.cache.get(session.conn)
	blocks = []
	for target in targets:
		remote = await ftp.remote_cache.get(session.conn, target.id)
		blocks.append({"target": target, "remote": remote})
	return templates.TemplateResponse(
		request,
		"partials/remote_backups.html",
		{
			"settings": settings,
			"session": session,
			"blocks": blocks,
			"git": local.get("git") or {},
		},
	)


@router.get("/backups/{target_id}", response_class=HTMLResponse)
async def remote_backups_target(target_id: str, request: Request, session: SessionDep):
	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")
	force = request.query_params.get("force") == "1"
	local = await stats.cache.get(session.conn)
	remote = await ftp.remote_cache.get(session.conn, target_id, force=force)
	return templates.TemplateResponse(
		request,
		"partials/remote_backup_target.html",
		{
			"settings": settings,
			"session": session,
			"target": target,
			"remote": remote,
			"git": local.get("git") or {},
		},
	)


@router.get("/push/{name}/confirm", response_class=HTMLResponse)
async def push_confirm(name: str, request: Request, session: SessionDep):
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	return templates.TemplateResponse(
		request,
		"partials/push_confirm.html",
		{"settings": settings, "session": session, "name": name, "targets": list_targets()},
	)


@router.post("/push/{name}", response_class=HTMLResponse)
async def push(name: str, request: Request, session: SessionDep):
	await _csrf(request, session)
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	form = await request.form()
	target_id = (form.get("target_id") or "").strip()

	try:
		job_id = await asyncio.to_thread(ftp.push, session.conn, name, session.username, target_id)
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
		args={"name": name, "target": target_id},
		job_id=job_id,
		result="launched",
	)
	return _fragment(request, session, job_id=job_id, label=f"Push backup {name}")


@router.post("/pull/{target_id}/{name}", response_class=HTMLResponse)
async def pull(target_id: str, name: str, request: Request, session: SessionDep):
	await _csrf(request, session)
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	try:
		job_id = await asyncio.to_thread(ftp.pull, session.conn, name, session.username, target_id)
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
		args={"name": name, "target": target_id},
		job_id=job_id,
		result="launched",
	)
	return _fragment(request, session, job_id=job_id, label=f"Pull backup {name}")
