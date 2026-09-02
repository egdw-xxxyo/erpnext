"""Ops dashboard entrypoint.

Run with a single uvicorn worker: SSH connections and sessions live in this
process, so a second worker would serve requests for sessions it cannot see.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, jobs, lockout, sessions
from .config import settings
from .deps import LoginRequired
from .routes import actions, dashboard, git_key_settings, panels, remote_backups
from .routes import jobs as jobs_routes
from .routes import schedule as schedule_routes
from .routes import settings as settings_routes

REAP_INTERVAL = 300
SWEEP_INTERVAL = 3600


async def _reaper() -> None:
	"""Close SSH connections for expired sessions and mark orphaned jobs."""
	last_sweep = 0.0
	while True:
		await asyncio.sleep(REAP_INTERVAL)
		try:
			sessions.reap()
		except Exception as exc:
			print(f"[ops] session reap failed: {exc}", flush=True)

		loop_now = asyncio.get_event_loop().time()
		if loop_now - last_sweep < SWEEP_INTERVAL:
			continue
		last_sweep = loop_now
		# The sweep needs a host connection; borrow any live session rather
		# than holding credentials of our own.
		live = sessions.any_live()
		if live:
			await asyncio.to_thread(jobs.sweep, live.conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
	lockout.load()
	task = asyncio.create_task(_reaper())
	print(
		f"[ops] ready — env={settings.env_label} host={settings.ssh_host}:{settings.ssh_port} "
		f"repo={settings.repo_path}",
		flush=True,
	)
	yield
	task.cancel()
	with contextlib.suppress(asyncio.CancelledError):
		await task


app = FastAPI(title="ERPNext Ops", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(panels.router)
app.include_router(jobs_routes.router)
app.include_router(actions.router)
app.include_router(remote_backups.router)
app.include_router(settings_routes.router)
app.include_router(schedule_routes.router)
app.include_router(git_key_settings.router)


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
	# A full page load gets bounced to the login form; an htmx fragment gets a
	# 401 plus a header the client turns into a redirect, so a panel poll after
	# a session expires does not silently paint the login page into a card.
	if request.headers.get("hx-request") == "true":
		return JSONResponse(
			{"detail": "login required"},
			status_code=401,
			headers={"HX-Redirect": "/login"},
		)
	return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.get("/healthz")
async def healthz():
	"""Liveness of the dashboard itself, not of ERPNext."""
	return {"ok": True, "env": settings.env_label, "sessions": sessions.active_count()}
