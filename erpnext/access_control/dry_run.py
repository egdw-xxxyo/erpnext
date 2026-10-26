import json
import socket
import sys
import time
from collections import Counter
from functools import reduce
from urllib.parse import urlparse

import frappe
from frappe import _

SIMULATED_METHODS = frozenset(
	{
		"frappe.desk.form.save.savedocs",
		"frappe.desk.form.save.cancel",
		"frappe.model.workflow.apply_workflow",
	}
)
MAX_STEPS = 30
BUDGET_SECONDS = 15
LOCK_WAIT_SECONDS = 5
_network_guard = {"installed": False, "allowed": frozenset()}


class DryRun:
	def __init__(self):
		self.skipped = []

	def skip(self, kind, detail):
		self.skipped.append((kind, str(detail)))

	def refuse(self, kind):
		frappe.throw(_("This action changes the database schema and cannot be simulated"))

	def summary(self) -> dict:
		return dict(Counter(kind for kind, _detail in self.skipped))


def _hosts() -> frozenset[str]:
	names = {frappe.conf.db_host or "localhost"} | {
		urlparse(frappe.conf.get(key) or "").hostname
		for key in ("redis_cache", "redis_queue", "redis_socketio")
		if frappe.conf.get(key)
	}
	return frozenset(address for name in names if name for address in {name, *_resolve(name)})


def _resolve(name: str) -> set[str]:
	try:
		return {info[4][0] for info in socket.getaddrinfo(name, None)}
	except OSError:
		return set()


def _audit(event, args):
	if event != "socket.connect" or not getattr(getattr(frappe.local, "flags", None), "dry_run", None):
		return
	address = args[1]
	if not isinstance(address, tuple) or address[0] in _network_guard["allowed"]:
		return
	raise PermissionError(_("Network access is blocked during a simulation: {0}").format(address[0]))


def install_network_guard():
	if _network_guard["installed"]:
		return
	_network_guard["allowed"] = _hosts()
	sys.addaudithook(_audit)
	_network_guard["installed"] = True


def begin(dry_run: DryRun):
	install_network_guard()
	frappe.flags.dry_run = dry_run
	frappe.flags.mute_emails = True


def guarded_functions() -> list:
	from frappe.database.database import Database
	from frappe.deferred_insert import deferred_insert
	from frappe.realtime import publish_realtime
	from frappe.utils.background_jobs import enqueue
	from frappe.utils.global_search import update_global_search

	return [enqueue, publish_realtime, update_global_search, deferred_insert, Database.sql_ddl]


def framework_supports_dry_run() -> bool:
	return all("dry_run" in fn.__code__.co_names for fn in guarded_functions())


def parse_steps(steps) -> list[dict]:
	parsed = frappe.parse_json(steps) or []
	if not isinstance(parsed, list) or not parsed or len(parsed) > MAX_STEPS:
		frappe.throw(_("Invalid simulation steps"))
	invalid = [
		step for step in parsed if not isinstance(step, dict) or step.get("method") not in SIMULATED_METHODS
	]
	if invalid:
		frappe.throw(_("This action cannot be simulated"))
	return [
		{
			"method": step["method"],
			"args": _as_form_args(step.get("args")),
			"names": [str(name) for name in step.get("names") or []],
		}
		for step in parsed
	]


def _as_form_args(args) -> dict:
	return {
		key: frappe.as_json(value) if isinstance(value, dict | list) else value
		for key, value in (frappe.parse_json(args) or {}).items()
	}


def _run_step(step: dict):
	from frappe.handler import execute_cmd

	frappe.local.form_dict = frappe._dict(step["args"])
	frappe.local.response = frappe._dict(docs=[])
	frappe.local.message_log = []
	result = execute_cmd(step["method"])
	if result is not None:
		frappe.response["message"] = result


def _start_read_committed():
	frappe.db.sql("rollback")
	frappe.db.sql("set transaction isolation level read committed")
	frappe.db.sql("start transaction")
	frappe.db.sql(f"set session innodb_lock_wait_timeout = {LOCK_WAIT_SECONDS}")


def _finish():
	db = frappe.db
	db.rollback()
	for doc in list(getattr(frappe.local, "locked_documents", None) or []):
		doc.unlock()
	db.sql("set session innodb_lock_wait_timeout = default")


def _swap_names(text: str, mapping: dict[str, str]) -> str:
	return reduce(
		lambda result, pair: result.replace(json.dumps(pair[0]), json.dumps(pair[1])),
		mapping.items(),
		text,
	)


def _renamed_args(args: dict, mapping: dict[str, str]) -> dict:
	return {
		key: mapping.get(value, _swap_names(value, mapping)) if isinstance(value, str) else value
		for key, value in args.items()
	}


def _names_in(doc: dict) -> list[str]:
	rows = [
		row for value in doc.values() if isinstance(value, list) for row in value if isinstance(row, dict)
	]
	return [str(doc["name"]), *(str(row["name"]) for row in rows if row.get("name"))]


def _produced_names() -> list[str]:
	message = frappe.response.get("message")
	docs = [*frappe.response.get("docs", []), *([message] if isinstance(message, dict) else [])]
	plain = [frappe.parse_json(frappe.as_json(doc)) for doc in docs]
	return list(dict.fromkeys(name for doc in plain if doc.get("name") for name in _names_in(doc)))


def _with_current_timestamps(args: dict, touched: frozenset[str]) -> dict:
	doc = frappe.parse_json(args.get("doc")) if isinstance(args.get("doc"), str) else None
	if not isinstance(doc, dict) or not doc.get("doctype") or doc.get("name") not in touched:
		return args
	current = frappe.db.get_value(doc["doctype"], doc["name"], ["creation", "modified"], as_dict=True)
	return {**args, "doc": frappe.as_json({**doc, **current})} if current else args


def _new_names(recorded: list[str], produced: list[str]) -> dict[str, str]:
	return {old: new for old, new in zip(recorded, produced, strict=False) if old != new}


def _restore_client_names(mapping: dict[str, str]):
	if not mapping:
		return
	reverse = {new: old for old, new in mapping.items()}
	frappe.local.response = frappe._dict(
		json.loads(_swap_names(frappe.as_json(frappe.local.response), reverse))
	)


def _replay(steps: list[dict], started: float) -> dict[str, str]:
	mapping, touched = {}, frozenset()
	for index, step in enumerate(steps):
		if time.monotonic() - started > BUDGET_SECONDS:
			frappe.throw(_("The simulation took too long and was stopped"))
		try:
			_run_step(
				{**step, "args": _with_current_timestamps(_renamed_args(step["args"], mapping), touched)}
			)
		except Exception:
			if index < len(steps) - 1:
				frappe.local.message_log = []
				frappe.throw(
					_("Earlier simulated steps no longer apply. Reset the simulation and start again"),
					title=_("Simulation"),
				)
			raise
		produced = _produced_names()
		mapping = {**mapping, **_new_names(step["names"], produced)}
		touched = touched | set(produced)
	return mapping


@frappe.whitelist(methods=["POST"])
def simulate(steps: str) -> object:
	from erpnext.access_control.impersonation import view_session

	if not view_session():
		frappe.throw(_("Simulation is available only in a view session"), frappe.PermissionError)

	if not framework_supports_dry_run():
		frappe.throw(_("Simulation is not supported by the installed framework version"))
	parsed = parse_steps(steps)
	dry_run = frappe.flags.dry_run or DryRun()
	begin(dry_run)
	_start_read_committed()
	frappe.db._disable_transaction_control += 1
	started = time.monotonic()
	try:
		mapping = _replay(parsed, started)
	finally:
		frappe.db._disable_transaction_control -= 1
		_finish()
		frappe.flags.read_only = True
	_restore_client_names(mapping)
	frappe.response["dry_run"] = {
		"steps": len(parsed),
		"names": _produced_names(),
		"seconds": round(time.monotonic() - started, 3),
		"skipped": dry_run.summary(),
	}
	return frappe.response.get("message")
