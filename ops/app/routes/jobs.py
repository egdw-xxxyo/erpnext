"""Job status and the live console stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .. import jobs as jobs_mod
from .. import progress, stats
from ..config import settings
from ..deps import SessionDep
from ..sessions import Session
from ..templating import templates

router = APIRouter(prefix="/jobs")

HEARTBEAT_SECONDS = 15
# A line still unterminated after this long (a prompt, a progress bar with no
# newline yet) is sent as it is rather than held back indefinitely.
PARTIAL_FLUSH_SECONDS = 2


@router.get("/latest", response_class=HTMLResponse)
async def latest_job_console(request: Request, session: SessionDep):
	data = await stats.jobs_cache.get(session.conn)
	rows = data.get("jobs") or []
	job = next((j for j in rows if j.get("state") == "running"), rows[0] if rows else None)
	if job is None:
		return HTMLResponse('<p class="muted">No jobs yet. Run an action to see its output here.</p>')
	return await job_console(job["id"], request, session, label=job.get("label"))


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_console(job_id: str, request: Request, session: SessionDep, label: str | None = None):
	if not job_id.isalnum():
		raise HTTPException(status_code=400, detail="bad job id")
	state = await asyncio.to_thread(jobs_mod.status, session.conn, job_id)
	try:
		lines = await asyncio.to_thread(jobs_mod.progress_lines, session.conn, job_id)
	except Exception:
		lines = []
	timeline = progress.parse(lines, (state or {}).get("state"))
	return templates.TemplateResponse(
		request,
		"partials/job_console.html",
		{
			"settings": settings,
			"session": session,
			"job_id": job_id,
			"state": state,
			"label": label,
			"timeline": timeline,
		},
	)


@router.get("/{job_id}/status")
async def job_status(job_id: str, session: SessionDep):
	if not job_id.isalnum():
		raise HTTPException(status_code=400, detail="bad job id")
	return await asyncio.to_thread(jobs_mod.status, session.conn, job_id)


def _console_text(raw: bytes) -> str:
	"""Log bytes as console text. Progress bars (pip, git, yarn, docker)
	rewrite their line with a bare CR; an event-stream parser treats that CR
	as a line end, and everything after it on the line arrives without a
	``data:`` prefix and is silently dropped. Every CR becomes a newline."""
	text = raw.decode("utf-8", "replace")
	return text.replace("\r\n", "\n").replace("\r", "\n")


def _complete_lines(buffer: bytes) -> int:
	"""Length of the prefix of ``buffer`` made of whole lines. A trailing CR
	is held back: its LF may be the first byte of the next chunk."""
	cut = max(buffer.rfind(b"\n"), buffer.rfind(b"\r"))
	if cut == len(buffer) - 1 and buffer.endswith(b"\r"):
		cut = max(buffer.rfind(b"\n", 0, cut), buffer.rfind(b"\r", 0, cut))
	return cut + 1


def _sse(data: str, event: str | None = None, event_id: int | None = None) -> bytes:
	out = ""
	if event_id is not None:
		out += f"id: {event_id}\n"
	if event:
		out += f"event: {event}\n"
	for line in data.split("\n"):
		out += f"data: {line}\n"
	return (out + "\n").encode("utf-8")


async def _replay(body: str, offset: int, state: dict):
	raw = body.encode("utf-8")
	rest = raw[offset:]
	if rest:
		yield _sse(_console_text(rest).rstrip("\n"), event_id=len(raw))
	yield _sse(json.dumps(state), event="done", event_id=len(raw))


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

	# The host file is the complete log, and its byte offsets are the ones a
	# reconnecting browser sends back. The database copy is clipped for size,
	# so it only serves a finished run once the 14-day sweep has removed the
	# host file (status() then answers from the index, marked "archived").
	state = await asyncio.to_thread(jobs_mod.status, session.conn, job_id)
	if state.get("archived"):
		archived = await asyncio.to_thread(jobs_mod.archived_log, job_id)
		if archived is not None:
			return StreamingResponse(
				_replay(archived, offset, state),
				media_type="text/event-stream",
				headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
			)

	channel = await asyncio.to_thread(session.conn.open_stream, jobs_mod.tail_command(job_id, offset))

	async def generate():
		# The browser appends a newline after every event, so only whole
		# lines are sent; event ids stay byte offsets into the host file.
		position = offset
		pending = b""
		loop = asyncio.get_event_loop()
		last_beat = last_data = loop.time()

		def flush(size: int) -> bytes:
			nonlocal pending, position
			sent, pending = pending[:size], pending[size:]
			position += len(sent)
			return _sse(_console_text(sent).rstrip("\n"), event_id=position)

		try:
			while True:
				if await request.is_disconnected():
					break

				chunk = b""
				if channel.recv_ready():
					chunk = await asyncio.to_thread(channel.recv, 65536)

				if chunk:
					pending += chunk
					last_data = last_beat = loop.time()
					size = _complete_lines(pending)
					if size:
						yield flush(size)
					continue

				if pending and loop.time() - last_data > PARTIAL_FLUSH_SECONDS:
					yield flush(len(pending))
					last_beat = loop.time()

				if channel.exit_status_ready() and not channel.recv_ready():
					break

				now = asyncio.get_event_loop().time()
				if now - last_beat > HEARTBEAT_SECONDS:
					yield b": ping\n\n"
					last_beat = now
				await asyncio.sleep(0.25)

			if pending:
				yield flush(len(pending))
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
