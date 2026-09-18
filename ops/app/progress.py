"""Milestone markers emitted by ./deploy and ./updateRepo.

The scripts print one line per milestone (tools/ops-progress.sh):

    [OPS] 2026-09-15T09:14:02Z migrate start Running bench migrate

A job's markers are appended to .ops-jobs/<id>.progress, which stats.py reads
back. This module turns those lines into an ordered step list the panels render
— the phase order comes from the lines themselves, so a script that grows a new
milestone shows up without a change here; the catalog below only supplies nicer
labels and the expected step count used for "3 of 11".

The job runner (jobs.py) brackets every run with a `job start` / `job ok|fail`
pair — the start and end of the whole run — and copies the markers of every
successful run into .ops-jobs/history/<action>/, keeping the last five. Those
runs are the basis of the per-stage and total time estimates.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

LINE_RE = re.compile(r"\[OPS\]\s+(\S+)\s+(\S+)\s+(start|ok|fail|skip)(?:\s+(.*))?$")

# Written by the job runner, not by a script: brackets the whole run.
JOB_PHASE = "job"

LABELS = {
	JOB_PHASE: "Command start",
	"image": "Build image",
	"containers": "Recreate containers",
	"assets": "Sync assets",
	"config": "Apply site config",
	"migrate": "Migrate schema",
	"custom-fields": "Custom fields",
	"manifest": "Asset manifest",
	"extra-apps": "Extra apps",
	"ops-image": "Build dashboard image",
	"ops": "Restart dashboard",
	"backup": "Backup",
	"backup-prune": "Prune backups",
	"repo": "Pull repo",
	"tags": "Fetch tags",
	"submodules": "Update submodules",
	"done": "Finished",
}

# Only used for the "step N of M" hint; a mismatch is cosmetic.
EXPECTED: dict[str, list[str]] = {
	"build": [
		JOB_PHASE,
		"backup-prune",
		"backup",
		"image",
		"containers",
		"assets",
		"config",
		"migrate",
		"custom-fields",
		"manifest",
		"extra-apps",
		"done",
	],
	"backup": [JOB_PHASE, "backup-prune", "backup"],
	"update-repo": [JOB_PHASE, "repo", "tags", "submodules", "done"],
	"switch-branch": [JOB_PHASE, "repo", "tags", "submodules", "done"],
	"ops-rebuild": [JOB_PHASE, "ops-image", "ops", "done"],
}


def epoch(stamp: str | None) -> float | None:
	if not stamp:
		return None
	try:
		return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
	except ValueError:
		return None


def span(start: str | None, end: str | None) -> float | None:
	a, b = epoch(start), epoch(end)
	if a is None or b is None:
		return None
	return max(b - a, 0.0)


def _close_job_step(index: dict[str, dict], stamp: str) -> None:
	step = index.get(JOB_PHASE)
	if step and step.get("state") == "running":
		step.update(state="done", finished=stamp, took=span(step.get("started"), stamp))


def parse(lines, job_state: str | None = None) -> dict:
	"""Fold marker lines into ordered steps. `job_state` is the job's own state."""
	steps: list[dict] = []
	index: dict[str, dict] = {}
	job: dict[str, str] = {}

	for line in lines or []:
		match = LINE_RE.search(line)
		if not match:
			continue
		stamp, phase, status, text = match.group(1), match.group(2), match.group(3), match.group(4) or ""
		if phase == JOB_PHASE:
			if status == "start":
				job["started"] = stamp
				step = {"key": JOB_PHASE, "label": LABELS[JOB_PHASE], "started": stamp}
				step.update(state="running", text=text.strip())
				index[JOB_PHASE] = step
				steps.insert(0, step)
			else:
				job["finished"] = stamp
				_close_job_step(index, stamp)
			continue
		step = index.get(phase)
		if step is None:
			# The first script milestone ends the "command start" step.
			_close_job_step(index, stamp)
			step = {"key": phase, "label": LABELS.get(phase, phase), "started": stamp}
			index[phase] = step
			steps.append(step)
		step["text"] = text.strip() or step.get("text", "")
		if status == "start":
			step["state"] = "running"
		else:
			step["state"] = {"ok": "done", "fail": "failed", "skip": "skipped"}[status]
			step["finished"] = stamp
			step["took"] = span(step.get("started"), stamp)

	# A job that died mid-step leaves that step at "running" forever. The job's
	# own state is the only thing that knows better.
	if job_state in {"failed", "crashed", "rejected"}:
		for step in steps:
			if step.get("state") == "running":
				step["state"] = "failed"

	current = next((s for s in reversed(steps) if s.get("state") == "running"), None)
	if current is None and steps:
		current = steps[-1]

	started = job.get("started") or (steps[0]["started"] if steps else None)
	finished = job.get("finished")
	return {
		"steps": steps,
		"current": current,
		"done": sum(1 for s in steps if s.get("state") in {"done", "skipped"}),
		"failed": any(s.get("state") == "failed" for s in steps),
		"started": started,
		"finished": finished,
		"took": span(started, finished),
	}


def estimates(runs) -> dict:
	"""Average stage and total durations over past runs (newest first)."""
	per_stage: dict[str, list[float]] = {}
	totals: list[float] = []
	order: list[str] = []

	for lines in runs or []:
		parsed = parse(lines)
		if not order:
			order = [s["key"] for s in parsed["steps"]]
		for step in parsed["steps"]:
			if step.get("state") == "done" and step.get("took") is not None:
				per_stage.setdefault(step["key"], []).append(step["took"])
		if parsed["took"] is not None:
			totals.append(parsed["took"])

	return {
		"runs": len(runs or []),
		"order": order,
		"stages": {key: sum(values) / len(values) for key, values in per_stage.items()},
		"total": sum(totals) / len(totals) if totals else None,
	}


def summary(job: dict, history: dict | None = None, now: float | None = None) -> dict:
	"""Parsed progress for one job row, with time-left estimates while it runs."""
	now = time.time() if now is None else now
	action = job.get("action") or ""
	running = job.get("state") == "running"
	data = parse(job.get("progress"), job.get("state"))
	est = estimates((history or {}).get(action))
	steps = data["steps"]

	if running:
		seen = {s["key"] for s in steps}
		steps.extend(
			{"key": key, "label": LABELS.get(key, key), "state": "pending"}
			for key in est["order"]
			if key not in seen
		)

	for step in steps:
		avg = est["stages"].get(step["key"])
		step["avg"] = avg
		if not running or avg is None:
			continue
		if step["state"] == "running":
			elapsed = max(now - (epoch(step.get("started")) or now), 0.0)
			step["elapsed"] = elapsed
			step["left"] = max(avg - elapsed, 0.0)
		elif step["state"] == "pending":
			step["left"] = avg

	expected = EXPECTED.get(action, [])
	data["total"] = max(len(expected), len(steps))
	data["runs"] = est["runs"]
	data["avg_total"] = est["total"]
	data["left"] = None
	if running:
		start = epoch(data["started"]) or float(job.get("started") or now)
		data["elapsed"] = max(now - start, 0.0)
		if est["total"] is not None:
			data["left"] = max(est["total"] - data["elapsed"], 0.0)
	return data
