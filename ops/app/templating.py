"""Jinja environment and the display filters the templates rely on."""

from __future__ import annotations

import time

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def human_bytes(value) -> str:
	try:
		size = float(value)
	except (TypeError, ValueError):
		return "—"
	for unit in ("B", "KB", "MB", "GB", "TB"):
		if abs(size) < 1024 or unit == "TB":
			return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
		size /= 1024
	return f"{size:.1f} TB"


def human_time(epoch) -> str:
	try:
		return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(epoch)))
	except (TypeError, ValueError):
		return "—"


def ago(epoch) -> str:
	try:
		delta = time.time() - float(epoch)
	except (TypeError, ValueError):
		return "—"
	if delta < 60:
		return f"{int(delta)}s ago"
	if delta < 3600:
		return f"{int(delta / 60)}m ago"
	if delta < 86400:
		return f"{int(delta / 3600)}h ago"
	return f"{int(delta / 86400)}d ago"


def duration(seconds) -> str:
	try:
		total = int(float(seconds))
	except (TypeError, ValueError):
		return "—"
	if total < 60:
		return f"{total}s"
	return f"{total // 60}m {total % 60}s"


templates.env.filters["human_bytes"] = human_bytes
templates.env.filters["human_time"] = human_time
templates.env.filters["ago"] = ago
templates.env.filters["duration"] = duration
