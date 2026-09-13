"""Mutating routes: launching jobs.

Phase 2. Everything here goes through the fixed command table, requires a CSRF
token, and is written to the host-side audit log before it runs.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, commands, git_ssh, jobs, stats
from ..config import settings
from ..deps import SessionDep, client_ip
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/actions")

# These are the only commands that touch origin (git pull/fetch) — the rest
# never need a deploy key staged.
_GIT_COMMANDS = {"update-repo", "switch-branch"}


async def _csrf(request: Request, session: Session) -> None:
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")


def _fragment(request: Request, session: Session, **ctx) -> HTMLResponse:
	return templates.TemplateResponse(
		request, "partials/launched.html", {"settings": settings, "session": session, **ctx}
	)


@router.post("/{key}", response_class=HTMLResponse)
async def launch(key: str, request: Request, session: SessionDep):
	await _csrf(request, session)
	form = await request.form()
	ip = client_ip(request)

	try:
		command = commands.get(key)
		line, values = command.render(dict(form))
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	data = await stats.cache.get(session.conn)
	git = data.get("git") or {}

	if command.needs_clean_tree and git.get("dirty"):
		return _fragment(
			request,
			session,
			error=(
				"The working tree on the host has uncommitted changes to tracked files. "
				"Someone edited files in place — resolve that on the host first."
			),
		)

	if key in _GIT_COMMANDS:
		line = await asyncio.to_thread(git_ssh.wrap, session.conn, session.username, line)

	try:
		job_id = await asyncio.to_thread(
			jobs.launch, session.conn, key, line, command.label, session.username, values
		)
	except jobs.JobBusy:
		return _fragment(request, session, error="Another job is already running. Wait for it to finish.")
	except Exception as exc:
		return _fragment(request, session, error=f"Could not start the job: {exc}")

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=ip,
		action=key,
		args=values,
		job_id=job_id,
		result="launched",
	)
	return _fragment(request, session, job_id=job_id, label=command.label)
