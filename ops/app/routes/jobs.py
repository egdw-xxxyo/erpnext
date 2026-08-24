"""Job status and the live console stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .. import jobs as jobs_mod
from ..config import settings
from ..deps import SessionDep
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/jobs")

HEARTBEAT_SECONDS = 15


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_console(job_id: str, request: Request, session: SessionDep):
	if not job_id.isalnum():
		raise HTTPException(status_code=400, detail="bad job id")
	state = await asyncio.to_thread(jobs_mod.status, session.conn, job_id)
	return templates.TemplateResponse(
		request,
		"partials/job_console.html",
		{"settings": settings, "session": session, "job_id": job_id, "state": state},
	)


@router.get("/{job_id}/status")
async def job_status(job_id: str, session: SessionDep):
	if not job_id.isalnum():
		raise HTTPException(status_code=400, detail="bad job id")
	return await asyncio.to_thread(jobs_mod.status, session.conn, job_id)


def _sse(data: str, event: str | None = None, event_id: int | None = None) -> bytes:
	out = ""
	if event_id is not None:
		out += f"id: {event_id}\n"
	if event:
		out += f"event: {event}\n"
	for line in data.split("\n"):
		out += f"data: {line}\n"
	return (out + "\n").encode("utf-8")


@router.get("/{job_id}/stream")
async def job_stream(job_id: str, request: Request, session: SessionDep):
	"""Stream the job log as SSE, resumable by byte offset.

	Each event's id is the byte offset reached after that chunk. On reconnect
	the browser sends Last-Event-ID and we resume from there — which is what
	lets the console survive this container being restarted mid-deploy by the
	very job it is showing.
	"""
	if not job_id.isalnum():
		raise HTTPException(status_code=400, detail="bad job id")

	try:
		offset = int(request.headers.get("last-event-id") or request.query_params.get("offset") or 0)
	except ValueError:
		offset = 0

	channel = await asyncio.to_thread(session.conn.open_stream, jobs_mod.tail_command(job_id, offset))

	async def generate():
		position = offset
		last_beat = asyncio.get_event_loop().time()
		try:
			while True:
				if await request.is_disconnected():
					break

				chunk = b""
				if channel.recv_ready():
					chunk = await asyncio.to_thread(channel.recv, 65536)

				if chunk:
					position += len(chunk)
					yield _sse(chunk.decode("utf-8", "replace").rstrip("\n"), event_id=position)
					last_beat = asyncio.get_event_loop().time()
					continue

				if channel.exit_status_ready() and not channel.recv_ready():
					break

				now = asyncio.get_event_loop().time()
				if now - last_beat > HEARTBEAT_SECONDS:
					yield b": ping\n\n"
					last_beat = now
				await asyncio.sleep(0.25)

			state = await asyncio.to_thread(jobs_mod.status, session.conn, job_id)
			yield _sse(json.dumps(state), event="done", event_id=position)
		finally:
			try:
				channel.close()
			except Exception:
				pass

	return StreamingResponse(
		generate(),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)
