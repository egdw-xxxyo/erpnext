"""Off-host FTP backup targets configuration.

Any allowed ops user can view/edit — same tier as the rest of ops' config
(OPS_SSH_HOST, OPS_ENV_LABEL, ...). Multiple named targets can be configured,
each tagged prod/dev/test, so e.g. a dev instance can hold a read-only-in-
intent copy of prod's target to pull a prod backup down for local testing.
A target's password is write-only: stored encrypted (see ftp_config.py) and
never included in any response after save, only a "configured since" marker.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, ftp
from ..config import settings
from ..deps import SessionDep, client_ip
from ..ftp_config import (
	ENV_LABELS,
	FtpTarget,
	MisconfiguredSecretKey,
	delete_target,
	get_target,
	list_targets,
	save_target,
)
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")


def _parse_form(form) -> tuple[str, str, str, int, str, str, str] | str:
	"""Returns (target_id, name, env_label, port, host, username, password, remote_dir)
	shaped as (target_id, name, env_label, host, port, username, password, remote_dir)
	or an error string."""
	target_id = (form.get("target_id") or "").strip()
	name = (form.get("name") or "").strip()
	env_label = (form.get("env_label") or "").strip()
	host = (form.get("host") or "").strip()
	port_raw = (form.get("port") or "21").strip()
	username = (form.get("username") or "").strip()
	password = form.get("password") or ""
	remote_dir = (form.get("remote_dir") or "/").strip()

	if not name or not host or not username or not remote_dir:
		return "Name, host, username and remote folder are required."
	if env_label not in ENV_LABELS:
		return "Target must be one of: " + ", ".join(ENV_LABELS)
	try:
		port = int(port_raw)
		if not (1 <= port <= 65535):
			raise ValueError
	except ValueError:
		return "Port must be a number between 1 and 65535."
	return target_id, name, env_label, host, port, username, password, remote_dir


def _render(request: Request, session: Session, edit: FtpTarget | None = None, **ctx) -> HTMLResponse:
	return templates.TemplateResponse(
		request,
		"partials/ftp_settings.html",
		{
			"settings": settings,
			"session": session,
			"targets": list_targets(),
			"env_labels": ENV_LABELS,
			"edit": edit,
			**ctx,
		},
	)


@router.get("/ftp", response_class=HTMLResponse)
async def ftp_settings(request: Request, session: SessionDep):
	return _render(request, session)


@router.get("/ftp/{target_id}/edit", response_class=HTMLResponse)
async def ftp_settings_edit(target_id: str, request: Request, session: SessionDep):
	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")
	return _render(request, session, edit=target)


@router.post("/ftp", response_class=HTMLResponse)
async def ftp_settings_save(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	parsed = _parse_form(form)
	if isinstance(parsed, str):
		return _render(request, session, error=parsed)
	target_id, name, env_label, host, port, username, password, remote_dir = parsed

	if target_id:
		existing = get_target(target_id)
		if existing is None:
			return _render(request, session, error="That target no longer exists.")
		if not password:
			password = existing.password  # keep the existing secret when the field is left blank
	elif not password:
		return _render(request, session, error="Password is required for a new target.")

	try:
		save_target(
			target_id=target_id or None,
			name=name,
			env_label=env_label,
			host=host,
			port=port,
			username=username,
			password=password,
			remote_dir=remote_dir,
		)
	except MisconfiguredSecretKey as exc:
		return _render(request, session, error=str(exc))

	await _audit(session, request, "ftp-config-save", name, host, port, username, remote_dir, "saved")
	return _render(request, session, saved=True)


@router.get("/ftp/{target_id}/remove-confirm", response_class=HTMLResponse)
async def ftp_settings_remove_confirm(target_id: str, request: Request, session: SessionDep):
	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")
	return templates.TemplateResponse(
		request,
		"partials/confirm_popup.html",
		{
			"settings": settings,
			"session": session,
			"title": f"Remove {target.name}",
			"warning": (
				f"Removes the stored FTP target {target.name!r} ({target.host}). "
				"Any backup already pushed there stays there — this only forgets the credentials."
			),
			"post_url": f"/settings/ftp/{target_id}/delete",
			"hidden": {},
			"require_typed": False,
			"danger": True,
			"button_label": "Remove target",
			"target_el": "#panel-ftp-settings",
		},
	)


@router.post("/ftp/{target_id}/delete", response_class=HTMLResponse)
async def ftp_settings_delete(target_id: str, request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")

	delete_target(target_id)
	await _audit(
		session,
		request,
		"ftp-config-delete",
		target.name,
		target.host,
		target.port,
		target.username,
		target.remote_dir,
		"deleted",
	)
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
	target_id, name, env_label, host, port, username, password, remote_dir = parsed

	if not password:
		existing = get_target(target_id) if target_id else None
		if existing is None:
			return _render(
				request, session, test_error="Password is required — nothing saved yet to fall back on."
			)
		password = existing.password

	# Not persisted — a throwaway target just for this one connection check,
	# so "Test" never has to be preceded by "Save" to try new credentials.
	throwaway = FtpTarget(
		id=target_id or "",
		name=name,
		env_label=env_label,
		host=host,
		port=port,
		username=username,
		password=password,
		remote_dir="/" + remote_dir.strip("/"),
		updated_at=0.0,
	)
	try:
		names = await asyncio.to_thread(ftp.test_connection, session.conn, throwaway)
	except MisconfiguredSecretKey as exc:
		return _render(
			request, session, test_error=str(exc), edit=get_target(target_id) if target_id else None
		)
	except Exception as exc:
		await _audit(
			session, request, "ftp-config-test", name, host, port, username, remote_dir, f"failed: {exc}"
		)
		return _render(
			request, session, test_error=str(exc), edit=get_target(target_id) if target_id else None
		)

	await _audit(session, request, "ftp-config-test", name, host, port, username, remote_dir, "ok")
	return _render(request, session, test_entries=names, edit=get_target(target_id) if target_id else None)


async def _audit(
	session: Session,
	request: Request,
	action: str,
	name: str,
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
		args={"name": name, "host": host, "port": port, "username": username, "remote_dir": remote_dir},
		result=result,
	)
