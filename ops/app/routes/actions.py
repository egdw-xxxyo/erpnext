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

	# The same gate ./deploy enforces, applied here so the operator gets a real
	# explanation instead of an instant opaque failure.
	if key == "build" and (data.get("version") or {}).get("site_env") == "prod":
		if not git.get("tag") and not git.get("merge"):
			return _fragment(
				request,
				session,
				error=(
					f"Prod deploys are blocked for untagged commits. HEAD ({git.get('head')}) "
					"has no tag and is not a merge commit — tag the release first."
				),
			)

	if command.destructive and command.confirm_phrase:
		expected = settings.site if command.confirm_phrase == "site" else command.confirm_phrase
		if (form.get("confirm") or "").strip() != expected:
			return _fragment(
				request, session, error=f"Confirmation did not match. Type '{expected}' exactly."
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


@router.get("/backup-remove/{name}/confirm", response_class=HTMLResponse)
async def backup_remove_confirm(name: str, request: Request, session: SessionDep):
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	return templates.TemplateResponse(
		request,
		"partials/confirm_popup.html",
		{
			"settings": settings,
			"session": session,
			"title": f"Remove {name}",
			"warning": f"Permanently deletes local backup set {name}. This cannot be undone.",
			"post_url": "/actions/backup-remove",
			"hidden": {"name": name},
			"require_typed": True,
			"danger": True,
			"button_label": "Remove permanently",
		},
	)


@router.get("/backup-clean/confirm", response_class=HTMLResponse)
async def backup_clean_confirm(request: Request, session: SessionDep):
	return templates.TemplateResponse(
		request,
		"partials/confirm_popup.html",
		{
			"settings": settings,
			"session": session,
			"title": "Clean old backups",
			"warning": "Deletes every local backup except the most recent one. This cannot be undone.",
			"post_url": "/actions/backup-clean",
			"hidden": {},
			"require_typed": True,
			"danger": True,
			"button_label": "Clean old backups",
		},
	)


@router.get("/space-hard-clean/confirm", response_class=HTMLResponse)
async def space_hard_clean_confirm(request: Request, session: SessionDep):
	return templates.TemplateResponse(
		request,
		"partials/confirm_popup.html",
		{
			"settings": settings,
			"session": session,
			"title": "Hard clean",
			"warning": (
				"Removes every unused Docker image, including the previous release's tagged image — "
				"you will not be able to roll back to it afterwards. Also fully clears the build "
				"cache, so the next build starts uncached and is slower. This cannot be undone."
			),
			"post_url": "/actions/space-hard-clean",
			"hidden": {},
			"require_typed": True,
			"danger": True,
			"button_label": "Remove images and cache",
		},
	)


@router.post("/restore/{name}/confirm", response_class=HTMLResponse)
async def restore_confirm(name: str, request: Request, session: SessionDep):
	"""Step one of a restore: show what is about to be destroyed."""
	await _csrf(request, session)
	try:
		name = commands.validate_backup_name(name)
	except commands.InvalidArgument as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	data = await stats.cache.get(session.conn)
	backup = next((b for b in data.get("backups") or [] if b["name"] == name), None)
	if backup is None:
		raise HTTPException(status_code=404, detail="no such backup")

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="restore",
		args={"name": name},
		result="confirm-shown",
	)
	return templates.TemplateResponse(
		request,
		"partials/restore_confirm.html",
		{"settings": settings, "session": session, "backup": backup},
	)
