"""Full-page routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import audit, stats
from ..commands import COMMANDS
from ..config import settings
from ..deps import SessionDep
from ..sessions import Session
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: SessionDep):
	data = await stats.cache.get(session.conn)
	return templates.TemplateResponse(
		request,
		"dashboard.html",
		{
			"settings": settings,
			"session": session,
			"data": data,
			"commands": COMMANDS,
		},
	)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, session: SessionDep):
	records = await asyncio.to_thread(audit.tail, session.conn, 200)
	return templates.TemplateResponse(
		request,
		"audit.html",
		{"settings": settings, "session": session, "records": records},
	)
