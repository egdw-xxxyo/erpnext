"""HTML fragments polled by htmx.

Every panel reads the same cached snapshot, so ten open panels across five
browsers still cost one SSH round-trip per TTL.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import schedule, stats
from ..commands import COMMANDS
from ..config import settings
from ..deps import SessionDep
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/panels")

PANELS = {
	"health": "partials/health.html",
	"containers": "partials/containers.html",
	"version": "partials/version.html",
	"version-badge": "partials/version_badge.html",
	"disk": "partials/disk.html",
	"backups": "partials/backups.html",
	"jobs": "partials/jobs.html",
	"actions": "partials/actions.html",
}


@router.get("/{name}", response_class=HTMLResponse)
async def panel(name: str, request: Request, session: SessionDep):
	template = PANELS.get(name)
	if template is None:
		raise HTTPException(status_code=404, detail="no such panel")

	force = request.query_params.get("force") == "1"
	data = await stats.cache.get(session.conn, force=force)

	context = {"settings": settings, "session": session, "data": data, "commands": COMMANDS}
	if name == "backups":
		context["current_schedule"] = await asyncio.to_thread(schedule.read, session.conn)
	if name == "disk":
		# Only measured when explicitly asked for: it walks thousands of files.
		if request.query_params.get("detail") == "1":
			context["detail"] = await stats.disk_detail.get(session.conn, force=force)
		else:
			context["detail"] = None
	return templates.TemplateResponse(request, template, context)
