"""Scheduled off-host backups (host crontab) and the pre-deploy safety-backup
toggle. See schedule.py and commands.py's "build" entry for why these two
unrelated-looking settings share one panel: both exist to make sure a backup
happened before something risky (time passing, or a deploy) — one via cron,
one via the build command's own shell line.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import audit, prefs, schedule
from ..config import settings
from ..deps import SessionDep, client_ip
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/settings")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _render(request: Request, session: Session, **ctx) -> HTMLResponse:
	current = schedule.read(session.conn)
	return templates.TemplateResponse(
		request,
		"partials/schedule_settings.html",
		{
			"settings": settings,
			"session": session,
			"current": current,
			"weekdays": list(enumerate(WEEKDAYS)),
			"pre_deploy_backup": prefs.get("pre_deploy_backup", True),
			**ctx,
		},
	)


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_settings(request: Request, session: SessionDep):
	return await asyncio.to_thread(_render, request, session)


@router.post("/schedule", response_class=HTMLResponse)
async def schedule_settings_save(request: Request, session: SessionDep):
	form = await request.form()
	token = request.headers.get("x-csrf-token") or form.get("csrf") or ""
	if token != session.csrf:
		raise HTTPException(status_code=403, detail="bad or missing CSRF token")

	enabled = (form.get("enabled") or "") == "on"
	frequency = (form.get("frequency") or "daily").strip()
	time_str = (form.get("time") or "").strip()
	weekday_raw = (form.get("weekday") or "0").strip()

	if frequency not in ("daily", "weekly"):
		return await asyncio.to_thread(_render, request, session, error="Invalid frequency.")
	try:
		hour_str, minute_str = time_str.split(":")
		hour, minute = int(hour_str), int(minute_str)
		if not (0 <= hour <= 23 and 0 <= minute <= 59):
			raise ValueError
	except ValueError:
		return await asyncio.to_thread(_render, request, session, error="Time must be HH:MM.")
	try:
		weekday = int(weekday_raw)
		if not (0 <= weekday <= 6):
			raise ValueError
	except ValueError:
		return await asyncio.to_thread(_render, request, session, error="Invalid weekday.")

	prefs.set("pre_deploy_backup", (form.get("pre_deploy_backup") or "") == "on")

	try:
		if enabled:
			await asyncio.to_thread(
				schedule.write,
				session.conn,
				frequency=frequency,
				weekday=weekday,
				time_str=f"{hour:02d}:{minute:02d}",
				repo_path=settings.repo_path,
			)
		else:
			await asyncio.to_thread(schedule.remove, session.conn)
	except schedule.ScheduleError as exc:
		return await asyncio.to_thread(_render, request, session, error=str(exc))

	await asyncio.to_thread(
		audit.write,
		session.conn,
		user=session.username,
		client_ip=client_ip(request),
		action="schedule-save",
		args={"enabled": enabled, "frequency": frequency, "time": time_str, "weekday": weekday},
		result="saved",
	)
	return await asyncio.to_thread(_render, request, session, saved=True)
