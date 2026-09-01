"""Login and logout.

Credentials are the operator's own OS account, validated by opening an SSH
connection to the host. That connection then *is* the session — the dashboard
holds no privilege of its own.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import audit, local_conn, lockout, sessions, ssh
from .config import settings
from .deps import client_ip
from .sessions import COOKIE_NAME
from .templating import templates

router = APIRouter()

# Floor on the login response time so a valid username cannot be distinguished
# from an invalid one by how fast the rejection comes back.
MIN_LOGIN_SECONDS = 1.0


def _safe_next(raw: str) -> str:
	"""Only allow same-origin absolute paths, never an off-site redirect."""
	if raw.startswith("/") and not raw.startswith("//"):
		return raw
	return "/"


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
	if sessions.get(request.cookies.get(COOKIE_NAME)):
		return RedirectResponse(_safe_next(next), status_code=303)
	return templates.TemplateResponse(
		request, "login.html", {"next": _safe_next(next), "error": None, "settings": settings}
	)


@router.post("/login", response_class=HTMLResponse)
async def login(
	request: Request,
	username: str = Form(...),
	password: str = Form(...),
	next: str = Form("/"),
):
	started = time.monotonic()
	ip = client_ip(request)
	username = username.strip()

	async def reject(message: str, code: int = 401):
		remaining = MIN_LOGIN_SECONDS - (time.monotonic() - started)
		if remaining > 0:
			await asyncio.sleep(remaining)
		return templates.TemplateResponse(
			request,
			"login.html",
			{"next": _safe_next(next), "error": message, "settings": settings},
			status_code=code,
		)

	wait = lockout.check(username, ip)
	if wait > 0:
		return await reject(f"Too many failed attempts. Try again in {int(wait / 60) + 1} min.", 429)

	# Checked before the SSH attempt so a name that is not permitted never
	# reaches sshd and never counts against MaxAuthTries.
	if settings.allowed_users and username not in settings.allowed_users:
		lockout.record_failure(username, ip)
		return await reject("Invalid username or password.")

	if settings.local_mode:
		# No sshd to authenticate against — allowed_users IS the auth check.
		# Never leave this unset in local mode, or any username logs in.
		if not settings.allowed_users:
			return await reject("OPS_LOCAL_MODE requires OPS_ALLOWED_USERS to be set.", 503)
		conn = local_conn.connect(username)
	else:
		try:
			conn = await asyncio.to_thread(ssh.connect, username, password)
		except ssh.AuthFailed:
			lockout.record_failure(username, ip)
			return await reject("Invalid username or password.")
		except ssh.HostUnreachable as exc:
			# Not a credential problem — say so, otherwise every outage looks
			# like a forgotten password.
			return await reject(f"Cannot reach the host: {exc}", 503)

	lockout.record_success(username, ip)
	cookie, session = sessions.create(username, conn)
	await asyncio.to_thread(audit.write, conn, user=username, client_ip=ip, action="login", result="ok")

	response = RedirectResponse(_safe_next(next), status_code=303)
	response.set_cookie(
		COOKIE_NAME,
		cookie,
		httponly=True,
		samesite="strict",
		path="/",
		secure=request.url.scheme == "https",
	)
	return response


@router.post("/logout")
async def logout(request: Request):
	sessions.drop(request.cookies.get(COOKIE_NAME))
	response = RedirectResponse("/login", status_code=303)
	response.delete_cookie(COOKIE_NAME, path="/")
	return response
