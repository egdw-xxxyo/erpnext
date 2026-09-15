"""Milestone markers emitted by ./deploy and ./updateRepo.

The scripts print one line per milestone (tools/ops-progress.sh):

    [OPS] 2026-09-15T09:14:02Z migrate start Running bench migrate

A job's markers are appended to .ops-jobs/<id>.progress, which stats.py reads
back. This module turns those lines into an ordered step list the panels render
— the phase order comes from the lines themselves, so a script that grows a new
milestone shows up without a change here; the catalog below only supplies nicer
labels and the expected step count used for "3 of 11".
"""

from __future__ import annotations

import re

LINE_RE = re.compile(r"\[OPS\]\s+(\S+)\s+(\S+)\s+(start|ok|fail|skip)(?:\s+(.*))?$")

LABELS = {
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
		"ops",
		"done",
	],
	"backup": ["backup-prune", "backup"],
	"update-repo": ["repo", "tags", "submodules", "done"],
	"switch-branch": ["repo", "tags", "submodules", "done"],
	"ops-rebuild": ["ops-image", "ops", "done"],
}


def parse(lines, job_state: str | None = None) -> dict:
	"""Fold marker lines into ordered steps. `job_state` is the job's own state."""
	steps: list[dict] = []
	index: dict[str, dict] = {}

	for line in lines or []:
		match = LINE_RE.search(line)
		if not match:
			continue
		stamp, phase, status, text = match.group(1), match.group(2), match.group(3), match.group(4) or ""
		step = index.get(phase)
		if step is None:
			step = {"key": phase, "label": LABELS.get(phase, phase), "started": stamp}
			index[phase] = step
			steps.append(step)
		step["text"] = text.strip() or step.get("text", "")
		if status == "start":
			step["state"] = "running"
		else:
			step["state"] = {"ok": "done", "fail": "failed", "skip": "skipped"}[status]
			step["finished"] = stamp

	# A job that died mid-step leaves that step at "running" forever. The job's
	# own state is the only thing that knows better.
	if job_state in {"failed", "crashed", "rejected"}:
		for step in steps:
			if step.get("state") == "running":
				step["state"] = "failed"

	current = next((s for s in reversed(steps) if s.get("state") == "running"), None)
	if current is None and steps:
		current = steps[-1]

	return {
		"steps": steps,
		"current": current,
		"done": sum(1 for s in steps if s.get("state") in {"done", "skipped"}),
		"failed": any(s.get("state") == "failed" for s in steps),
	}


def summary(job: dict) -> dict:
	"""Parsed progress for one job row out of the stats snapshot."""
	data = parse(job.get("progress"), job.get("state"))
	expected = EXPECTED.get(job.get("action") or "", [])
	data["total"] = max(len(expected), len(data["steps"]))
	return data
