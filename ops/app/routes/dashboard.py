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


def _page(request: Request, session: Session, nav: str, template: str, data, extra: dict | None = None):
	context = {
		"settings": settings,
		"session": session,
		"data": data,
		"commands": COMMANDS,
		"nav": nav,
	}
	if extra:
		context.update(extra)
	return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: SessionDep):
	data = await stats.cache.get(session.conn)
	return _page(request, session, "dashboard", "dashboard.html", data)


@router.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request, session: SessionDep):
	data = await stats.cache.get(session.conn)
	return _page(request, session, "backups", "backups.html", data)


@router.get("/deploy", response_class=HTMLResponse)
async def deploy_page(request: Request, session: SessionDep):
	data = await stats.cache.get(session.conn)
	return _page(request, session, "deploy", "deploy.html", data)


@router.get("/configuration", response_class=HTMLResponse)
async def configuration_page(request: Request, session: SessionDep):
	data = await stats.cache.get(session.conn)
	return _page(request, session, "configuration", "configuration.html", data)


@router.get("/information", response_class=HTMLResponse)
async def information_page(request: Request, session: SessionDep):
	records = await asyncio.to_thread(audit.tail, session.conn, 200)
	data = await stats.cache.get(session.conn)
	return _page(request, session, "information", "information.html", data, {"records": records})
