"""Off-host SFTP backup target configuration.

Any allowed ops user can view/edit it — one shared target per instance, same
tier as the rest of ops' config (OPS_SSH_HOST, OPS_ENV_LABEL, ...). The
password is write-only: it is stored encrypted (see sftp_config.py) and never
included in any response after save, only a "configured since" marker is.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit
from ..config import settings
from ..deps import SessionDep, client_ip
from ..sessions import Session
from ..sftp_config import MisconfiguredSecretKey, load, save
from ..templating import templates

router = APIRouter(prefix="/settings")


def _render(request: Request, session: Session, **ctx) -> HTMLResponse:
	config = load()
	return templates.TemplateResponse(
		request,
		"partials/sftp_settings.html",
		{"settings": settings, "session": session, "config": config, **ctx},
	)


@router.get("/sftp", response_class=HTMLResponse)
async def sftp_settings(request: Request, session: SessionDep):
	return _render(request, session)


@router.post("/sftp", response_class=HTMLResponse)
async def sftp_settings_save(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	host = (form.get("host") or "").strip()
	port_raw = (form.get("port") or "22").strip()
	username = (form.get("username") or "").strip()
	password = form.get("password") or ""
	remote_dir = (form.get("remote_dir") or "/").strip()

	if not host or not username or not remote_dir:
		return _render(request, session, error="Host, username and remote folder are required.")
	try:
		port = int(port_raw)
		if not (1 <= port <= 65535):
			raise ValueError
	except ValueError:
		return _render(request, session, error="Port must be a number between 1 and 65535.")

	existing = load()
	if not password:
		if existing is None:
			return _render(request, session, error="Password is required the first time.")
		password = existing.password  # keep the existing secret when the field is left blank

	try:
		save(host=host, port=port, username=username, password=password, remote_dir=remote_dir)
	except MisconfiguredSecretKey as exc:
		return _render(request, session, error=str(exc))

	await _audit(session, request, host, port, username, remote_dir)
	return _render(request, session, saved=True)


async def _audit(
	session: Session, request: Request, host: str, port: int, username: str, remote_dir: str
) -> None:
	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="sftp-config-save",
		# Deliberately no password — this is the audit log, which is a plain
		# host-side text file any allowed ops user can read via /audit.
		args={"host": host, "port": port, "username": username, "remote_dir": remote_dir},
		result="saved",
	)
