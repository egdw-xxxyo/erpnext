"""Per-ops-user git SSH deploy key (see git_keys.py / git_ssh.py for why).

Scoped to the logged-in ops user (session.username) — each operator manages
only their own key, the same way GitHub issues SSH keys per person. Nothing
here is shared across users the way the FTP backup targets are.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, git_keys, git_ssh
from ..config import settings
from ..deps import SessionDep, client_ip
from ..git_keys import MisconfiguredSecretKey
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")


def _render(request: Request, session: Session, **ctx) -> HTMLResponse:
	current = git_keys.load(session.username)
	return templates.TemplateResponse(
		request,
		"partials/git_key_settings.html",
		{"settings": settings, "session": session, "current": current, **ctx},
	)


@router.get("/git-key", response_class=HTMLResponse)
async def git_key_get(request: Request, session: SessionDep):
	return _render(request, session)


@router.post("/git-key", response_class=HTMLResponse)
async def git_key_save(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	private_key = (form.get("private_key") or "").strip()
	if not private_key:
		return _render(request, session, error="Paste a private key first.")
	if "PRIVATE KEY" not in private_key:
		return _render(request, session, error="That doesn't look like a private key (no PRIVATE KEY header).")

	try:
		await asyncio.to_thread(git_keys.save, session.username, private_key)
	except MisconfiguredSecretKey as exc:
		return _render(request, session, error=str(exc))

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="git-key-save",
		# No key material — this is the audit log, a plain host-side text
		# file any allowed ops user can read via /information.
		args={},
		result="saved",
	)
	return _render(request, session, saved=True)


@router.post("/git-key/delete", response_class=HTMLResponse)
async def git_key_delete(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	await asyncio.to_thread(git_keys.delete, session.username)
	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="git-key-delete",
		args={},
		result="deleted",
	)
	return _render(request, session, saved=True)


@router.post("/git-key/test", response_class=HTMLResponse)
async def git_key_test(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	current = git_keys.load(session.username)
	if current is None:
		return _render(request, session, test_error="No key saved yet.")

	try:
		greeting = await asyncio.to_thread(git_ssh.test_connection, session.conn, current)
	except Exception as exc:
		await asyncio.to_thread(
			audit.write,
			session.conn,
			user=session.username,
			client_ip=client_ip(request),
			action="git-key-test",
			args={},
			result=f"failed: {exc}",
		)
		return _render(request, session, test_error=str(exc))

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="git-key-test",
		args={},
		result="ok",
	)
	return _render(request, session, test_ok=greeting)
