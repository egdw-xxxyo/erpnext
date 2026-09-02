"""Off-host FTP backup targets configuration.

Any allowed ops user can view/edit — same tier as the rest of ops' config
(OPS_SSH_HOST, OPS_ENV_LABEL, ...). One shared server (host/port/username/
password) plus any number of named targets (just name + env label + remote
path) on that server. A target's password is write-only: stored encrypted
(see ftp_config.py) and never included in any response after save, only a
"configured since" marker.
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
	FtpServer,
	FtpTarget,
	MisconfiguredSecretKey,
	NotConfigured,
	delete_target,
	get_server,
	get_target,
	list_targets,
	save_server,
	save_target,
)
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")


def _render_panel(request: Request, session: Session, **ctx) -> HTMLResponse:
	return templates.TemplateResponse(
		request,
		"partials/ftp_settings.html",
		{"settings": settings, "session": session, "server": get_server(), "targets": list_targets(), **ctx},
	)


def _render_panel_oob(request: Request, session: Session, **ctx) -> str:
	return templates.get_template("partials/ftp_settings_oob.html").render(
		{"settings": settings, "session": session, "server": get_server(), "targets": list_targets(), **ctx}
	)


def _render_target_modal(
	request: Request, session: Session, edit: FtpTarget | None = None, **ctx
) -> HTMLResponse:
	return templates.TemplateResponse(
		request,
		"partials/ftp_target_modal.html",
		{"settings": settings, "session": session, "env_labels": ENV_LABELS, "edit": edit, **ctx},
	)


def _render_server_modal(request: Request, session: Session, **ctx) -> HTMLResponse:
	return templates.TemplateResponse(
		request,
		"partials/ftp_server_modal.html",
		{"settings": settings, "session": session, "server": get_server(), **ctx},
	)


def _check_csrf(request: Request, session: Session, form) -> None:
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")


# ---- panel -------------------------------------------------------------------


@router.get("/ftp", response_class=HTMLResponse)
async def ftp_settings(request: Request, session: SessionDep):
	return _render_panel(request, session)


# ---- server modal --------------------------------------------------------------


@router.get("/ftp/server/edit", response_class=HTMLResponse)
async def ftp_server_edit(request: Request, session: SessionDep):
	return _render_server_modal(request, session)


@router.post("/ftp/server", response_class=HTMLResponse)
async def ftp_server_save(request: Request, session: SessionDep):
	form = await request.form()
	_check_csrf(request, session, form)

	host = (form.get("host") or "").strip()
	username = (form.get("username") or "").strip()
	password = form.get("password") or ""
	port_raw = (form.get("port") or "21").strip()
	if not host or not username:
		return _render_server_modal(request, session, error="Host and username are required.")
	try:
		port = int(port_raw)
		if not (1 <= port <= 65535):
			raise ValueError
	except ValueError:
		return _render_server_modal(request, session, error="Port must be a number between 1 and 65535.")

	try:
		save_server(host=host, port=port, username=username, password=password)
	except (MisconfiguredSecretKey, NotConfigured) as exc:
		return _render_server_modal(request, session, error=str(exc))

	await _audit(session, request, "ftp-server-save", host, port, username, "saved")
	return HTMLResponse(_render_panel_oob(request, session, saved=True))


@router.post("/ftp/server/test", response_class=HTMLResponse)
async def ftp_server_test(request: Request, session: SessionDep):
	form = await request.form()
	_check_csrf(request, session, form)

	host = (form.get("host") or "").strip()
	username = (form.get("username") or "").strip()
	password = form.get("password") or ""
	port_raw = (form.get("port") or "21").strip()
	try:
		port = int(port_raw)
	except ValueError:
		return _render_server_modal(request, session, test_error="Port must be a number between 1 and 65535.")

	if not password:
		existing = get_server()
		if existing is None:
			return _render_server_modal(
				request, session, test_error="Password required — nothing saved yet to fall back on."
			)
		password = existing.password

	throwaway = FtpTarget(
		id="",
		name="(test)",
		env_label="test",
		host=host,
		port=port,
		username=username,
		password=password,
		remote_dir="/",
		updated_at=0.0,
	)
	try:
		names = await asyncio.to_thread(ftp.test_connection, session.conn, throwaway)
	except Exception as exc:
		await _audit(session, request, "ftp-server-test", host, port, username, f"failed: {exc}")
		return _render_server_modal(request, session, test_error=str(exc))

	await _audit(session, request, "ftp-server-test", host, port, username, "ok")
	return _render_server_modal(request, session, test_entries=names)


# ---- target modal --------------------------------------------------------------


@router.get("/ftp/new", response_class=HTMLResponse)
async def ftp_target_new(request: Request, session: SessionDep):
	return _render_target_modal(request, session)


@router.get("/ftp/{target_id}/edit", response_class=HTMLResponse)
async def ftp_target_edit(target_id: str, request: Request, session: SessionDep):
	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")
	return _render_target_modal(request, session, edit=target)


@router.post("/ftp", response_class=HTMLResponse)
async def ftp_target_save(request: Request, session: SessionDep):
	form = await request.form()
	_check_csrf(request, session, form)

	target_id = (form.get("target_id") or "").strip()
	name = (form.get("name") or "").strip()
	env_label = (form.get("env_label") or "").strip()
	remote_dir = (form.get("remote_dir") or "/").strip()

	if not name or not remote_dir:
		return _render_target_modal(
			request,
			session,
			edit=get_target(target_id) if target_id else None,
			error="Name and remote path are required.",
		)
	if env_label not in ENV_LABELS:
		return _render_target_modal(
			request,
			session,
			edit=get_target(target_id) if target_id else None,
			error="Target must be one of: " + ", ".join(ENV_LABELS),
		)
	if get_server() is None:
		return _render_target_modal(request, session, error="Configure the FTP server first.")

	try:
		save_target(target_id=target_id or None, name=name, env_label=env_label, remote_dir=remote_dir)
	except NotConfigured as exc:
		return _render_target_modal(
			request, session, edit=get_target(target_id) if target_id else None, error=str(exc)
		)

	await _audit(session, request, "ftp-config-save", name, env_label, remote_dir, "saved")
	return HTMLResponse(_render_panel_oob(request, session, saved=True))


@router.get("/ftp/{target_id}/remove-confirm", response_class=HTMLResponse)
async def ftp_target_remove_confirm(target_id: str, request: Request, session: SessionDep):
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
				f"Removes the stored FTP target {target.name!r} ({target.remote_dir}). "
				"Any backup already pushed there stays there — this only forgets the target."
			),
			"post_url": f"/settings/ftp/{target_id}/delete",
			"hidden": {},
			"require_typed": False,
			"danger": True,
			"button_label": "Remove target",
			"target_el": "#modal-body",
		},
	)


@router.post("/ftp/{target_id}/delete", response_class=HTMLResponse)
async def ftp_target_delete(target_id: str, request: Request, session: SessionDep):
	form = await request.form()
	_check_csrf(request, session, form)

	target = get_target(target_id)
	if target is None:
		raise HTTPException(status_code=404, detail="no such target")

	delete_target(target_id)
	await _audit(
		session, request, "ftp-config-delete", target.name, target.env_label, target.remote_dir, "deleted"
	)
	return HTMLResponse(_render_panel_oob(request, session, saved=True))


async def _audit(session: Session, request: Request, action: str, *fields: object) -> None:
	# Kept permissive on positional fields — server-save/test and target-save/
	# delete each log a different tuple of (non-secret) identifying values,
	# with the outcome string always last.
	*args, outcome = fields
	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action=action,
		args={"values": [str(a) for a in args]},
		result=outcome,
	)
