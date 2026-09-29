"""Configuration cards for the files ./deploy reads: the standby mirror's
``.mirror.env`` and ``site-config.json``. Both are edited over the operator's
own SSH session, like every other change this app makes to the host."""

from __future__ import annotations

import asyncio
import shlex

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, host_files, mirror_config, site_config
from ..commands import COMMANDS
from ..config import settings
from ..deps import SessionDep, client_ip
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")


async def _form(request: Request, session: Session) -> dict[str, str]:
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")
	return {k: str(v) for k, v in form.items()}


def _audit(request: Request, session: Session, action: str, args: dict) -> None:
	audit.write(
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action=action,
		args=args,
		result="saved",
	)


# --- Standby mirror -------------------------------------------------------------


def _mirror_values(session: Session) -> dict[str, str]:
	return mirror_config.parse(host_files.read(session.conn, mirror_config.ENV_FILE))


def _mirror_state(session: Session) -> tuple[str, str]:
	result = session.conn.run_in_repo(
		"cat .mirror/state 2>/dev/null || echo standby; echo '---'; ./deploy mirror status 2>&1 | head -40",
		timeout=45,
	)
	state, _, status = result.out.partition("---\n")
	return state.strip() or "standby", status.strip()


def _render_mirror(request: Request, session: Session, values: dict | None = None, **ctx) -> HTMLResponse:
	error = ctx.pop("error", None)
	try:
		if values is None:
			values = _mirror_values(session)
	except host_files.HostFileError as exc:
		values, error = {}, str(exc)
	role = values.get("MIRROR_ROLE", "")
	state, status = _mirror_state(session) if role else ("", "")
	return templates.TemplateResponse(
		request,
		"partials/mirror_settings.html",
		{
			"settings": settings,
			"session": session,
			"commands": COMMANDS,
			"values": values,
			"role": role,
			"roles": mirror_config.ROLES,
			"fields": mirror_config.FIELDS,
			"state": state,
			"status": status,
			"error": error,
			**ctx,
		},
	)


@router.get("/mirror", response_class=HTMLResponse)
async def mirror_get(request: Request, session: SessionDep):
	return await asyncio.to_thread(_render_mirror, request, session)


@router.post("/mirror", response_class=HTMLResponse)
async def mirror_save(request: Request, session: SessionDep):
	form = await _form(request, session)
	try:
		current = await asyncio.to_thread(_mirror_values, session)
	except host_files.HostFileError as exc:
		return await asyncio.to_thread(_render_mirror, request, session, error=str(exc))

	if current.get("MIRROR_ROLE") == "replica":
		state, _ = await asyncio.to_thread(_mirror_state, session)
		new_role = form.get("role") if form.get("enabled") == "on" else ""
		if state == "active" and new_role != "replica":
			return await asyncio.to_thread(
				_render_mirror,
				request,
				session,
				error="The mirror is serving users. Fail back before changing its role.",
			)

	try:
		values = mirror_config.validate(current, form)
		await asyncio.to_thread(
			host_files.write, session.conn, mirror_config.ENV_FILE, mirror_config.render(values)
		)
	except (mirror_config.InvalidMirrorConfig, host_files.HostFileError) as exc:
		merged = {**current, **{k: v for k, v in form.items() if k in mirror_config.FIELD_KEYS}}
		merged["MIRROR_ROLE"] = form.get("role", "") if form.get("enabled") == "on" else ""
		return await asyncio.to_thread(_render_mirror, request, session, values=merged, error=str(exc))

	await asyncio.to_thread(
		_audit,
		request,
		session,
		"mirror-config-save",
		{k: ("***" if k == "MIRROR_REPL_PASSWORD" else v) for k, v in values.items()},
	)
	return await asyncio.to_thread(_render_mirror, request, session, saved=True)


@router.post("/mirror/keygen", response_class=HTMLResponse)
async def mirror_keygen(request: Request, session: SessionDep):
	await _form(request, session)
	key = mirror_config.KEY_FILE
	script = f"""set -e
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f {key} ] || ssh-keygen -q -t ed25519 -N '' -C "erp-mirror@$(hostname)" -f {key}
echo "$HOME/.ssh/erp_mirror"
cat {key}.pub
"""
	result = await asyncio.to_thread(session.conn.run, script, 20)
	if not result.ok:
		return await asyncio.to_thread(
			_render_mirror, request, session, error=result.err.strip() or "ssh-keygen failed"
		)
	path, _, public_key = result.out.strip().partition("\n")

	values = await asyncio.to_thread(_mirror_values, session)
	if not values.get("MIRROR_PRIMARY_SSH_KEY"):
		values["MIRROR_PRIMARY_SSH_KEY"] = path
		await asyncio.to_thread(
			host_files.write, session.conn, mirror_config.ENV_FILE, mirror_config.render(values)
		)
	await asyncio.to_thread(_audit, request, session, "mirror-keygen", {"path": path})
	return await asyncio.to_thread(_render_mirror, request, session, public_key=public_key.strip())


@router.post("/mirror/test", response_class=HTMLResponse)
async def mirror_test(request: Request, session: SessionDep):
	await _form(request, session)
	values = await asyncio.to_thread(_mirror_values, session)
	target, key, repo = (
		values.get("MIRROR_PRIMARY_SSH", ""),
		values.get("MIRROR_PRIMARY_SSH_KEY", ""),
		values.get("MIRROR_PRIMARY_REPO", ""),
	)
	if not (target and key and repo):
		return await asyncio.to_thread(
			_render_mirror, request, session, test_error="Save the SSH login, key and repo path first."
		)
	remote = shlex.quote(f"test -x {shlex.quote(repo + '/deploy')} && echo deploy-found")
	script = (
		f"ssh -i {shlex.quote(key)} -o BatchMode=yes -o ConnectTimeout=8 "
		f"-o StrictHostKeyChecking=accept-new {shlex.quote(target)} {remote} 2>&1"
	)
	result = await asyncio.to_thread(session.conn.run, script, 20)
	if result.ok and "deploy-found" in result.out:
		return await asyncio.to_thread(
			_render_mirror, request, session, test_ok=f"Connected to {target}; found {repo}/deploy."
		)
	return await asyncio.to_thread(
		_render_mirror,
		request,
		session,
		test_error=(result.out.strip() or result.err.strip() or f"{repo}/deploy not found on main.")[-500:],
	)


# --- Site config ------------------------------------------------------------------


def _render_site_config(
	request: Request, session: Session, config: dict | None = None, **ctx
) -> HTMLResponse:
	error = ctx.pop("error", None)
	extra = ctx.pop("extra", None)
	try:
		if config is None:
			config = site_config.parse(host_files.read(session.conn, site_config.CONFIG_FILE))
	except (host_files.HostFileError, site_config.InvalidSiteConfig) as exc:
		config, error = {}, str(exc)
	return templates.TemplateResponse(
		request,
		"partials/site_config_settings.html",
		{
			"settings": settings,
			"session": session,
			"commands": COMMANDS,
			"config": config,
			"keys": site_config.KEYS,
			"extra": site_config.extra_json(config) if extra is None else extra,
			"error": error,
			**ctx,
		},
	)


@router.get("/site-config", response_class=HTMLResponse)
async def site_config_get(request: Request, session: SessionDep):
	return await asyncio.to_thread(_render_site_config, request, session)


@router.post("/site-config", response_class=HTMLResponse)
async def site_config_save(request: Request, session: SessionDep):
	form = await _form(request, session)
	try:
		current = site_config.parse(
			await asyncio.to_thread(host_files.read, session.conn, site_config.CONFIG_FILE)
		)
		config = site_config.validate(current, form)
		await asyncio.to_thread(
			host_files.write, session.conn, site_config.CONFIG_FILE, site_config.render(config), "644"
		)
	except (site_config.InvalidSiteConfig, host_files.HostFileError) as exc:
		return await asyncio.to_thread(
			_render_site_config, request, session, error=str(exc), extra=form.get("extra", "")
		)

	await asyncio.to_thread(_audit, request, session, "site-config-save", {"keys": sorted(config)})
	return await asyncio.to_thread(_render_site_config, request, session, saved=True)
