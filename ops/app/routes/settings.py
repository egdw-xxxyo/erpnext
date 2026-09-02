"""Off-host FTP backup target configuration.

Any allowed ops user can view/edit it — one shared target per instance, same
tier as the rest of ops' config (OPS_SSH_HOST, OPS_ENV_LABEL, ...). The
password is write-only: it is stored encrypted (see ftp_config.py) and never
included in any response after save, only a "configured since" marker is.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, ftp
from ..config import settings
from ..deps import SessionDep, client_ip
from ..ftp_config import FtpConfig, MisconfiguredSecretKey, load, save
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")


def _parse_form(form) -> tuple[str, int, str, str, str] | str:
	"""Returns (host, port, username, password, remote_dir) or an error string."""
	host = (form.get("host") or "").strip()
	port_raw = (form.get("port") or "21").strip()
	username = (form.get("username") or "").strip()
	password = form.get("password") or ""
	remote_dir = (form.get("remote_dir") or "/").strip()

	if not host or not username or not remote_dir:
		return "Host, username and remote folder are required."
	try:
		port = int(port_raw)
		if not (1 <= port <= 65535):
			raise ValueError
	except ValueError:
		return "Port must be a number between 1 and 65535."
	return host, port, username, password, remote_dir


def _render(request: Request, session: Session, **ctx) -> HTMLResponse:
	config = load()
	return templates.TemplateResponse(
		request,
		"partials/ftp_settings.html",
		{"settings": settings, "session": session, "config": config, **ctx},
	)


@router.get("/ftp", response_class=HTMLResponse)
async def ftp_settings(request: Request, session: SessionDep):
	return _render(request, session)


@router.post("/ftp", response_class=HTMLResponse)
async def ftp_settings_save(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	parsed = _parse_form(form)
	if isinstance(parsed, str):
		return _render(request, session, error=parsed)
	host, port, username, password, remote_dir = parsed

	existing = load()
	if not password:
		if existing is None:
			return _render(request, session, error="Password is required the first time.")
		password = existing.password  # keep the existing secret when the field is left blank

	try:
		save(host=host, port=port, username=username, password=password, remote_dir=remote_dir)
	except MisconfiguredSecretKey as exc:
		return _render(request, session, error=str(exc))

	await _audit(session, request, "ftp-config-save", host, port, username, remote_dir, "saved")
	return _render(request, session, saved=True)


@router.post("/ftp/test", response_class=HTMLResponse)
async def ftp_settings_test(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	parsed = _parse_form(form)
	if isinstance(parsed, str):
		return _render(request, session, test_error=parsed)
	host, port, username, password, remote_dir = parsed

	if not password:
		existing = load()
		if existing is None:
			return _render(
				request, session, test_error="Password is required — nothing saved yet to fall back on."
			)
		password = existing.password

	# Not persisted — a throwaway config just for this one connection check,
	# so "Test" never has to be preceded by "Save" to try new credentials.
	cfg = FtpConfig(
		host=host,
		port=port,
		username=username,
		password=password,
		remote_dir="/" + remote_dir.strip("/"),
		updated_at=0.0,
	)
	try:
		names = await asyncio.to_thread(ftp.test_connection, session.conn, cfg)
	except MisconfiguredSecretKey as exc:
		return _render(request, session, test_error=str(exc))
	except Exception as exc:
		await _audit(session, request, "ftp-config-test", host, port, username, remote_dir, f"failed: {exc}")
		return _render(request, session, test_error=str(exc))

	await _audit(session, request, "ftp-config-test", host, port, username, remote_dir, "ok")
	return _render(request, session, test_entries=names)


async def _audit(
	session: Session,
	request: Request,
	action: str,
	host: str,
	port: int,
	username: str,
	remote_dir: str,
	result: str,
) -> None:
	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action=action,
		# Deliberately no password — this is the audit log, which is a plain
		# host-side text file any allowed ops user can read via /audit.
		args={"host": host, "port": port, "username": username, "remote_dir": remote_dir},
		result=result,
	)
