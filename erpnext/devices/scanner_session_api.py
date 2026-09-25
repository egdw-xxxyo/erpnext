# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The API the phone in the operator's pocket talks to about their scanner.

A scanner's working memory is a frame in Redis (`scanner_state:{scanner}`) holding the
current state and a free-form context dict. Until now the only window onto it was the
scanner's own 9x20 display and the only way to change it was a barcode. That is fine while
the work is a stream of scans, and painful the moment the operator needs to answer "which
order am I packing?" or "pack that one instead".

This module opens that frame to a session-authenticated client. It is deliberately a
separate module from `scanner_api`, which is the guest-callable HMAC-authenticated hot path
for the devices themselves: nothing here is `allow_guest`, and the permission model is the
inverse — `_assert_scanner_mine`, i.e. the scanner must be claimed by the caller's Employee.

What the keys in the context *mean* is not guessed. A Workplace Script declares its context
contract in its `context_fields` table (see `Workplace Script Context Field`), which is what
makes a generic screen possible: the declaration carries the label, the type, whether the
app may write the key, whether it is the primary entity the session is about, and what
survives when that entity is switched.
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.devices.doctype.scanner.scanner_api import (
	_clear_state,
	_get_workplace_script,
	_load_state,
	_save_state,
	_subflow_initial_state,
	reset_frame,
)
from erpnext.devices.otdr_measurement_api import MANAGER_ROLES, _session_employee
from erpnext.devices.session_user import preserved_session

REALTIME_EVENT = "scanner_session_update"
DEFAULT_SCAN_LOG_LIMIT = 25

SCAN_LOG_FIELDS = [
	"name",
	"idx",
	"timestamp",
	"raw_data",
	"status",
	"resolved_action",
	"scanner_state",
	"target_doctype",
	"target_document",
	"result_message",
	"error_message",
	"resolve_ms",
	"script_ms",
	"total_ms",
]

CONTEXT_FIELD_FIELDS = [
	"key",
	"link_doctype",
	"label",
	"fieldtype",
	"options",
	"default_value",
	"show_in_app",
	"app_editable",
	"is_primary",
	"preserve_on_switch",
	"blocks_switch",
	"editable_in_states",
	"enter_state",
	"link_filters",
	"link_order_by",
	"description",
]


# ---------------------------------------------------------------------------
# Identity and permission
# ---------------------------------------------------------------------------


def _is_manager():
	return any(role in frappe.get_roles() for role in MANAGER_ROLES)


def _scanner_row(scanner):
	"""Read the Scanner's session columns without loading the doc.

	`Scanner` grants read only to Device Manager / Device Operator, and a shop-floor user
	holds neither — so every read here goes through `frappe.db`, and
	`_assert_scanner_mine` is the whole access check.
	"""
	row = frappe.db.get_value(
		"Scanner",
		scanner,
		["name", "scanner_name", "is_active", "workplace", "employee", "scanner_configuration"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Scanner {0} not found").format(scanner), frappe.DoesNotExistError)
	return row


def _assert_scanner_mine(scanner):
	"""A scanner may be inspected and steered by the employee who claimed it.

	Claiming happens on the device — the operator scans their badge, and `set_employee`
	writes it onto the Scanner row. Managers are exempt so a supervisor can look at a bench
	they are not badged into, mirroring `_assert_workplace_allowed` in the measurement API.
	"""
	if not scanner:
		frappe.throw(_("Scanner is required"))

	row = _scanner_row(scanner)
	if _is_manager():
		return row

	employee = _session_employee()
	if not employee or row.employee != employee:
		frappe.throw(
			_("Scanner {0} is not assigned to you").format(scanner),
			frappe.PermissionError,
		)
	return row


def _state_timeout(scanner_row):
	timeout = (
		frappe.db.get_value(
			"Scanner Configuration", scanner_row.get("scanner_configuration"), "state_timeout"
		)
		if scanner_row.get("scanner_configuration")
		else None
	)
	return cint(timeout) or 300


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def _script_context_fields(script_name):
	if not script_name:
		return []
	return frappe.get_all(
		"Workplace Script Context Field",
		filters={
			"parent": script_name,
			"parenttype": "Workplace Script",
			"parentfield": "context_fields",
		},
		fields=CONTEXT_FIELD_FIELDS,
		order_by="idx asc",
	)


def _declared_context_fields(root_script, subflow):
	"""The context contract in force, as `{key: declaration}` in display order.

	A session inside a subflow runs that subflow's states, so the subflow's declarations are
	the authoritative ones — but a root script may legitimately declare keys that outlive a
	subflow switch, so the two are merged with the subflow winning on a collision. This
	mirrors how `handle_scan` picks the active script: `frame.subflow or root`.

	With **no** subflow active the root's own subflows are folded in as well. Their keys are
	how a flow is entered — in packing, `so` is declared by «Пакування — Замовлення» and
	setting it is what starts that subflow (see `_subflow_for`) — so without this an idle
	scanner would offer nothing to start and the app could only watch. Once a subflow is
	running, only it and the root contribute: offering a sibling flow's keys mid-flow would
	write context the running states never read.
	"""
	scripts = [root_script]
	if subflow:
		scripts.append(subflow)
	elif root_script:
		scripts.extend(
			frappe.get_all(
				"Workplace Script",
				filters={"parent_script": root_script, "is_active": 1},
				pluck="name",
				order_by="name asc",
			)
		)

	declared = {}
	for script in scripts:
		if not script:
			continue
		for row in _script_context_fields(script):
			row.source_script = script
			row.undeclared = 0
			declared[row.key] = row
	return declared


def _editable_states(decl):
	"""State names where the app may write this key. Empty — every state."""
	return [line.strip() for line in (decl.get("editable_in_states") or "").splitlines() if line.strip()]


def _editable_now(decl, state):
	"""Whether the app may write this key while the session sits in `state`.

	A key is answered at one step of the flow and read-only afterwards: the packing template
	is chosen before the order, the order before the item. Without a state the session has no
	frame yet, so the declaration's own `app_editable` is the whole answer.
	"""
	if not cint(decl.get("app_editable")):
		return False
	states = _editable_states(decl)
	if not states:
		return True
	if not state:
		return True
	return state in states


def seeded_context(root_script, subflow, base=None):
	"""`base` with every declared default filled in for keys it does not carry.

	A fresh frame starts at the flow's first step, and a step whose answer is always the same
	(one packing template at the bench) is a step the operator should not have to take. The
	default is seeded rather than resolved at read time so the scripts, which only ever read
	`e.state.context`, see exactly what the app shows.
	"""
	context = dict(base or {})
	for key, decl in _declared_context_fields(root_script, subflow).items():
		if context.get(key) not in (None, ""):
			continue
		default = decl.get("default_value")
		if default in (None, ""):
			continue
		try:
			context[key] = _coerce_value(decl, default)
		except Exception:
			# A default pointing at a deleted or filtered-out document must cost the operator
			# one extra tap, not the whole session.
			frappe.logger("scanner").warning(
				f"context field {key}: default '{default}' is not a valid value", exc_info=True
			)
	return context


def _state_past_defaults(state, declared, context):
	"""Where the session belongs once the defaults have answered for it.

	A default is an answer already given, so the step that asks for it is a step to walk
	past: with the packing template pre-filled the operator should land on the order, not on
	a screen whose only editable row is the one already filled in. Only a key that carries a
	default and names both the step it is answered at and the step that follows moves the
	session, and each state is visited once, so a cycle in the declarations cannot spin here.
	"""
	seen = set()
	while state and state not in seen:
		seen.add(state)
		nxt = None
		for key, decl in declared.items():
			if not decl.get("default_value"):
				continue
			if context.get(key) in (None, "", [], {}):
				continue
			enter_state = (decl.get("enter_state") or "").strip()
			if not enter_state or enter_state == state:
				continue
			if state in _editable_states(decl):
				nxt = enter_state
				break
		if not nxt:
			break
		state = nxt
	return state


def seeded_frame(root_script, frame):
	"""`frame` with declared defaults filled in and the state moved past what they answer.

	Returns a new dict; an empty frame stays empty, because an idle scanner has no session to
	seed — the defaults land the moment the app or a scan opens one.
	"""
	if not frame:
		return dict(frame or {})

	subflow = frame.get("subflow")
	declared = _declared_context_fields(root_script, subflow)
	context = seeded_context(root_script, subflow, frame.get("context") or {})
	seeded = dict(frame)
	seeded["context"] = context
	seeded["state"] = _state_past_defaults(frame.get("state"), declared, context)
	return seeded


def _link_doctype(decl):
	"""The DocType a Link key points at.

	`link_doctype` is what the form asks for now — a real DocType picker instead of free text.
	Rows written before that field existed keep the DocType name in `options`, so it is still
	read as a fallback.
	"""
	return (decl.get("link_doctype") or decl.get("options") or "").strip()


def _link_filters(decl):
	raw = (decl.get("link_filters") or "").strip()
	if not raw:
		return {}
	try:
		parsed = json.loads(raw)
	except ValueError:
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _link_label(doctype, value):
	"""`SO-0001 — ТОВ Ромашка`, so the app never needs per-doctype knowledge."""
	try:
		title_field = frappe.get_meta(doctype).title_field
	except Exception:
		return value
	if not title_field or title_field == "name":
		return value
	title = frappe.db.get_value(doctype, value, title_field)
	return f"{value} — {title}" if title and title != value else value


def _render_display(decl, value):
	if value is None or value == "":
		return None
	if isinstance(value, list):
		return _("{0} pcs").format(len(value))
	if isinstance(value, dict):
		return _("{0} values").format(len(value))
	if decl.get("fieldtype") == "Check":
		return _("Yes") if cint(value) else _("No")
	if decl.get("fieldtype") == "Link" and _link_doctype(decl):
		try:
			return _link_label(_link_doctype(decl), value)
		except Exception:
			return str(value)
	return str(value)


def _state_label(script_name, state_name):
	if not script_name or not state_name:
		return None
	from erpnext.devices.doctype.workplace_script.workplace_script import (
		_resolve_default_snapshot,
	)

	try:
		snap = _resolve_default_snapshot(frappe.get_cached_doc("Workplace Script", script_name))
	except Exception:
		return None
	for row in snap.get("states") or []:
		if row.get("state") == state_name:
			return row.get("label") or None
	return None


def _snapshot_states(script_name):
	from erpnext.devices.doctype.workplace_script.workplace_script import (
		_resolve_default_snapshot,
	)

	try:
		snap = _resolve_default_snapshot(frappe.get_cached_doc("Workplace Script", script_name))
	except Exception:
		return set()
	return {row.get("state") for row in (snap.get("states") or [])}


def _scanner_commands():
	"""`{barcode: label}` for every command barcode, the command's own name as the label.

	Scanner Command names are already the Ukrainian wording the operator knows from the
	printed barcode sheet («Завершити пакування»), so a button does not invent a second
	vocabulary for the same action.
	"""
	rows = frappe.get_all("Scanner Command", fields=["name", "barcode_id", "description"])
	return {
		(row.barcode_id or "").strip(): {"label": row.name, "description": row.description}
		for row in rows
		if (row.barcode_id or "").strip()
	}


def _state_commands(script_name, state):
	"""Command buttons the app offers in `state`, read off the Transitions table.

	A transition whose event names a command barcode is the declaration: it is what the
	diagram already draws and what runtime already validates, so the buttons cannot drift
	from the flow the scanner actually runs. Anything else on that table — "серійник
	відскановано" — is a scan the operator makes with the device, not a button.
	"""
	if not script_name or not state:
		return []

	from erpnext.devices.doctype.workplace_script.workplace_script import (
		_resolve_default_snapshot,
	)

	try:
		snap = _resolve_default_snapshot(frappe.get_cached_doc("Workplace Script", script_name))
	except Exception:
		return []

	known = _scanner_commands()
	commands = []
	seen = set()
	for row in snap.get("transitions") or []:
		if row.get("from_state") != state:
			continue
		barcode = (row.get("event") or "").strip()
		decl = known.get(barcode)
		if not decl or barcode in seen:
			continue
		seen.add(barcode)
		commands.append(
			{
				"command": barcode,
				"label": decl["label"],
				"description": decl.get("description"),
				"to_state": row.get("to_state"),
			}
		)
	return commands


def _flows(root_script, active_subflow):
	"""The flows this scanner can be in: the root script itself, plus its subflows.

	A subflow is normally entered by scanning its command barcode (`subflow_entries`), so
	the trigger is reported alongside — the app shows «Замовлення (CMD-SO-ADD)» and the
	operator can recognise the barcode they would otherwise have hunted for.
	"""
	if not root_script:
		return []

	triggers = {}
	for row in frappe.get_all(
		"Workplace Script Subflow Entry",
		filters={"parent": root_script, "parenttype": "Workplace Script", "parentfield": "subflow_entries"},
		fields=["target_subflow", "trigger_type", "trigger_value"],
		order_by="idx asc",
	):
		triggers.setdefault(row.target_subflow, row.trigger_value)

	out = [
		{
			"name": root_script,
			"label": root_script,
			"is_root": 1,
			"is_active": 0 if active_subflow else 1,
			"trigger": None,
			"initial_state": _subflow_initial_state(root_script),
		}
	]
	for name in frappe.get_all(
		"Workplace Script",
		filters={"parent_script": root_script, "is_active": 1},
		pluck="name",
		order_by="name asc",
	):
		out.append(
			{
				"name": name,
				"label": name.split("—")[-1].strip() or name,
				"is_root": 0,
				"is_active": 1 if name == active_subflow else 0,
				"trigger": triggers.get(name),
				"initial_state": _subflow_initial_state(name),
			}
		)
	return out


# ---------------------------------------------------------------------------
# Reading a session
# ---------------------------------------------------------------------------


def _read_session(scanner_row):
	"""The whole screen's worth of state for one scanner, in one dict."""
	timeout = _state_timeout(scanner_row)
	frame = _load_state(scanner_row.name, timeout) or {}

	root_script = None
	if scanner_row.get("workplace"):
		# Without a workplace `_get_workplace_script` falls through to the site-wide default
		# script, whose declarations would have nothing to do with this scanner. Say
		# "not assigned" instead of showing a stranger's contract.
		script_doc = _get_workplace_script(scanner_row.get("workplace"))
		root_script = script_doc.name if script_doc else None

	seeded = seeded_frame(root_script, frame)
	if frame and seeded != frame:
		# Seeding is what the next write would do anyway; persisting it here keeps the screen
		# and the scanner's own frame from disagreeing about which step the session is on.
		_save_state(scanner_row.name, seeded, timeout)
		frame = _load_state(scanner_row.name, timeout) or seeded

	subflow = frame.get("subflow")
	active_script = subflow or root_script
	declared = _declared_context_fields(root_script, subflow)
	context = frame.get("context") or {}

	fields = []
	for key, decl in declared.items():
		fields.append(
			{
				"key": key,
				"label": decl.get("label") or key,
				"fieldtype": decl.get("fieldtype") or "Data",
				"options": decl.get("options"),
				"link_doctype": _link_doctype(decl) or None,
				"show_in_app": cint(decl.get("show_in_app")),
				"app_editable": cint(decl.get("app_editable")),
				"is_primary": cint(decl.get("is_primary")),
				"preserve_on_switch": cint(decl.get("preserve_on_switch")),
				"blocks_switch": cint(decl.get("blocks_switch")),
				"editable_in_states": _editable_states(decl),
				"editable_now": 1 if _editable_now(decl, frame.get("state")) else 0,
				"enter_state": decl.get("enter_state"),
				"description": decl.get("description"),
				"source_script": decl.get("source_script"),
				"undeclared": 0,
				"value": context.get(key),
				"display": _render_display(decl, context.get(key)),
			}
		)

	# Keys the running script keeps but nobody declared. Returned so the screen is never a
	# lie about what is in the frame, but hidden by default — during rollout most scripts
	# declare nothing at all.
	for key, value in context.items():
		if key in declared:
			continue
		fields.append(
			{
				"key": key,
				"label": key,
				"fieldtype": "Data",
				"options": None,
				"link_doctype": None,
				"show_in_app": 0,
				"app_editable": 0,
				"is_primary": 0,
				"preserve_on_switch": 0,
				"blocks_switch": 0,
				"editable_in_states": [],
				"editable_now": 0,
				"enter_state": None,
				"description": None,
				"source_script": None,
				"undeclared": 1,
				"value": value,
				"display": _render_display({"fieldtype": "Data"}, value),
			}
		)

	updated_at = frame.get("updated_at")
	return {
		"scanner": scanner_row.name,
		"scanner_label": scanner_row.get("scanner_name") or scanner_row.name,
		"workplace": scanner_row.get("workplace"),
		"workplace_label": scanner_row.get("workplace"),
		"employee": scanner_row.get("employee"),
		"script": root_script,
		"active_script": active_script,
		"subflow": subflow,
		"state": frame.get("state"),
		"state_label": _state_label(active_script, frame.get("state")),
		"active": bool(frame),
		"rev": frame.get("rev"),
		"updated_at": updated_at,
		"state_timeout": timeout,
		"flows": _flows(root_script, subflow),
		"commands": _state_commands(active_script, frame.get("state")),
		"expires_in": max(int(timeout - (time.time() - updated_at)), 0) if updated_at else None,
		"context_fields": fields,
	}


# ---------------------------------------------------------------------------
# Realtime
# ---------------------------------------------------------------------------


def _owner_user(scanner_name):
	employee = frappe.db.get_value("Scanner", scanner_name, "employee")
	return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def _publish_session_update(scanner_name, session, scan=None, user=None):
	"""Push the frame to the operator who owns the scanner.

	Per-user rooms only, as the chat page does: a doctype room would reach whoever holds
	`Scanner` read permission, which is not who is standing at the bench. Scoping to the
	*current* `Scanner.employee` also means a re-badged scanner stops notifying the previous
	operator without any extra bookkeeping.
	"""
	user = user or _owner_user(scanner_name)
	if not user:
		return
	frappe.publish_realtime(
		event=REALTIME_EVENT,
		message={"scanner": scanner_name, "session": session, "scan": scan},
		user=user,
		after_commit=False,
	)


def publish_after_scan(scanner, scan_log_row=None):
	"""Called from `handle_scan` once the scan is committed.

	Never raises: a realtime hiccup must not turn a good scan into a failed one.
	"""
	try:
		# Resolve the audience before building the payload: reading the session costs a
		# Redis read, a script snapshot and a Link title lookup, and an unclaimed scanner
		# has nobody to send it to. This runs inside the scan request.
		user = _owner_user(scanner.name)
		if not user:
			return

		scan = None
		if scan_log_row:
			scan = frappe.db.get_value("Scanner Scan Log Entry", scan_log_row, SCAN_LOG_FIELDS, as_dict=True)
			scan = (_with_labels([scan]) or [None])[0]
		row = frappe.db.get_value(
			"Scanner",
			scanner.name,
			["name", "scanner_name", "is_active", "workplace", "employee", "scanner_configuration"],
			as_dict=True,
		)
		if not row:
			return
		_publish_session_update(scanner.name, _read_session(row), scan, user=user)
	except Exception:
		frappe.logger("scanner").warning(
			f"{getattr(scanner, 'name', scanner)}: failed to publish {REALTIME_EVENT}", exc_info=True
		)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_my_scanners():
	"""Scanners claimed by the logged-in Employee, session included.

	Never throws: no Employee record, or no scanner badged in, is an empty screen rather
	than an error the operator cannot act on.
	"""
	employee = _session_employee()
	if not employee:
		return []

	rows = frappe.get_all(
		"Scanner",
		filters={"employee": employee, "is_active": 1},
		fields=["name", "scanner_name", "is_active", "workplace", "employee", "scanner_configuration"],
		order_by="scanner_name asc",
	)
	return [
		{
			"name": row.name,
			"label": row.scanner_name or row.name,
			"workplace": row.workplace,
			"session": _read_session(row),
		}
		for row in rows
	]


@frappe.whitelist(methods=["GET"])
def get_scanner_session(scanner=None):
	return _read_session(_assert_scanner_mine(scanner))


@frappe.whitelist(methods=["GET"])
def get_scan_log(scanner=None, limit=DEFAULT_SCAN_LOG_LIMIT):
	"""The scanner's recent scans, newest first.

	`idx` is append-only per scanner, so it orders the feed without trusting clocks.
	`script_logs` is left out: it is unbounded, carries script internals, and the desk shows
	it on the Scanner itself. Each scan carries the labels it printed instead.
	"""
	_assert_scanner_mine(scanner)
	rows = frappe.get_all(
		"Scanner Scan Log Entry",
		filters={"parent": scanner, "parenttype": "Scanner", "parentfield": "scan_logs"},
		fields=SCAN_LOG_FIELDS,
		order_by="idx desc",
		limit_page_length=min(cint(limit) or DEFAULT_SCAN_LOG_LIMIT, 100),
	)
	return _with_labels(rows)


def _with_labels(rows):
	"""Attach to each scan the labels its script printed, as `labels`.

	One entry per distinct label — the same template for the same document — with how many
	copies went out in total, and the newest job of it, which is what a reprint copies.
	Print Jobs are cleaned up after a week, so an older scan simply shows none.
	"""
	rows = [row for row in rows if row]
	names = [row.name for row in rows]
	jobs = (
		frappe.get_all(
			"Print Job",
			filters={"scan_log_entry": ["in", names]},
			fields=[
				"name",
				"scan_log_entry",
				"label_template",
				"reference_name",
				"raw_data",
				"copies",
				"status",
			],
			order_by="creation asc",
		)
		if names
		else []
	)

	grouped = {}
	for job in jobs:
		key = (job.scan_log_entry, job.label_template, job.reference_name, job.raw_data)
		label = grouped.setdefault(
			key,
			{"label_template": job.label_template, "reference_name": job.reference_name, "count": 0},
		)
		label["count"] += cint(job.copies) or 1
		label["print_job"] = job.name
		label["status"] = job.status

	by_row = {}
	for (entry, *_rest), label in grouped.items():
		by_row.setdefault(entry, []).append(label)
	for row in rows:
		row["labels"] = by_row.get(row.name, [])
	return rows


@frappe.whitelist(methods=["POST"])
def reprint_scan_label(scanner=None, print_job=None):
	"""Print a label from the scan journal again, on the printer it first came out of.

	The job must have been queued by a scan of this scanner — that, and the scanner being
	the caller's, is the whole check: the operator has no Print Job role, and needs none to
	repeat a label their own scan already printed. The copy is linked to the same scan, so
	the journal's count goes up by the copies printed.
	"""
	row = _assert_scanner_mine(scanner)
	if not print_job:
		frappe.throw(_("Print Job is required"))
	source = frappe.db.get_value(
		"Print Job",
		print_job,
		[
			"label_template",
			"label_printer",
			"reference_name",
			"parent_doctype",
			"parent_name",
			"raw_data",
			"copies",
			"scanner",
			"scan_log_entry",
		],
		as_dict=True,
	)
	if not source or source.scanner != row.name:
		frappe.throw(
			_("Print Job {0} was not printed by this scanner").format(print_job), frappe.PermissionError
		)

	from erpnext.devices.doctype.label_printer.label_printer import queue_print_job

	frappe.flags.scan_log_entry = source.scan_log_entry
	frappe.flags.scan_scanner = row.name
	result = queue_print_job(
		label_template=source.label_template,
		printer_name=source.label_printer,
		reference_name=source.reference_name,
		raw_data=source.raw_data,
		copies=source.copies or 1,
		ignore_permissions=True,
	)
	job = result.get("print_job")
	if source.parent_doctype or source.parent_name:
		frappe.db.set_value(
			"Print Job",
			job,
			{"parent_doctype": source.parent_doctype, "parent_name": source.parent_name},
			update_modified=False,
		)
	# Printing runs after commit: `print_label` rolls back on a printer error, which inside
	# this request would take the new job with it.
	frappe.enqueue(
		"erpnext.devices.doctype.label_printer.label_printer.print_label",
		queue="short",
		enqueue_after_commit=True,
		print_job_name=job,
	)
	return {"print_job": job}


@frappe.whitelist(methods=["GET"])
def search_context_options(scanner=None, key=None, query=None, limit=20):
	"""Options for an app-editable Link or Select context field.

	The doctype comes from the declaration, never from the caller — otherwise this would be
	a generic read oracle over the whole site. `get_list` (not `get_all`) keeps the caller's
	own read permissions in play on top of that.
	"""
	row = _assert_scanner_mine(scanner)
	frame = _load_state(row.name, _state_timeout(row)) or {}
	decl = _require_editable(_declared_context_fields(_root_script_name(row), frame.get("subflow")), key)

	if decl.get("fieldtype") == "Select":
		options = [o.strip() for o in (decl.get("options") or "").split("\n") if o.strip()]
		if query:
			needle = query.lower()
			options = [o for o in options if needle in o.lower()]
		return [{"value": o, "label": o} for o in options]

	if decl.get("fieldtype") != "Link":
		frappe.throw(_("Context field {0} has no options to pick from").format(key))

	doctype = _link_doctype(decl)
	filters = _link_filters(decl)
	limit = min(cint(limit) or 20, 50)

	# A declaration may restrict the picker by name — one packing template for this bench —
	# and the operator's search must narrow that list, never replace the restriction.
	declared_name_filter = "name" in filters
	if query and not declared_name_filter:
		filters["name"] = ["like", f"%{query}%"]

	names = frappe.get_list(
		doctype,
		filters=filters,
		pluck="name",
		order_by=decl.get("link_order_by") or "modified desc",
		limit_page_length=limit if not (query and declared_name_filter) else 0,
	)
	if query and declared_name_filter:
		needle = query.lower()
		names = [name for name in names if needle in name.lower()][:limit]
	return [{"value": name, "label": _link_label(doctype, name)} for name in names]


@frappe.whitelist(methods=["POST"])
def set_context_field(scanner=None, key=None, value=None):
	"""Write one declared context key from the app.

	Switching the primary entity is the point of this endpoint, and switching means the rest
	of the session is about the wrong thing — so everything except keys marked
	`preserve_on_switch` is dropped. Keys marked `blocks_switch` refuse the switch outright:
	they record work already written to the database (packages bound to the old order), and
	silently abandoning it mid-basket is worse than making the operator finish or reset.
	"""
	row = _assert_scanner_mine(scanner)
	timeout = _state_timeout(row)
	frame = _load_state(row.name, timeout) or {}
	root_script = _root_script_name(row)
	frame = seeded_frame(root_script, frame)
	context = dict(frame.get("context") or {})
	declared = _declared_context_fields(root_script, frame.get("subflow"))
	decl = _require_editable(declared, key, frame.get("state"))

	coerced = _coerce_value(decl, value)
	current = context.get(key)
	is_switch = bool(cint(decl.get("is_primary"))) and current not in (None, "") and current != coerced

	if is_switch:
		_assert_no_blockers(declared, context)

	subflow = frame.get("subflow") or _subflow_for(decl)

	if cint(decl.get("is_primary")):
		context = {
			k: v for k, v in context.items() if cint((declared.get(k) or {}).get("preserve_on_switch"))
		}
		context = seeded_context(root_script, subflow, context)
	context[key] = coerced

	new_frame = {"state": _target_state(decl, frame, declared), "context": context}
	if subflow:
		new_frame["subflow"] = subflow

	_save_state(row.name, seeded_frame(root_script, new_frame), timeout)

	session = _read_session(row)
	_publish_session_update(row.name, session)
	return session


def _assert_no_blockers(declared, context):
	"""Refuse to abandon work the session has already written to the database.

	`blocks_switch` keys record committed side effects — in packing, the packages already
	bound to the current order — so leaving them behind silently is worse than making the
	operator finish the batch or reset on purpose.
	"""
	blockers = [
		d.get("label") or k
		for k, d in declared.items()
		if cint(d.get("blocks_switch")) and context.get(k) not in (None, "", [], {})
	]
	if blockers:
		frappe.throw(_("Finish or reset the session first — it still holds: {0}").format(", ".join(blockers)))


@frappe.whitelist(methods=["POST"])
def set_scanner_flow(scanner=None, flow=None):
	"""Move the scanner into a flow, or back out to the root script.

	The same switch a subflow command barcode performs (`_enter_subflow`): the target's
	initial state, empty context. Passing the root script — or nothing — drops the frame, so
	the scanner is back at the root waiting for the next scan. Guarded by the same
	`blocks_switch` rule as a primary switch, because changing flow abandons the context
	just as thoroughly.
	"""
	row = _assert_scanner_mine(scanner)
	root_script = _root_script_name(row)
	if not root_script:
		frappe.throw(_("Scanner {0} has no workplace script").format(scanner))

	timeout = _state_timeout(row)
	frame = _load_state(row.name, timeout) or {}
	context = frame.get("context") or {}
	declared = _declared_context_fields(root_script, frame.get("subflow"))
	_assert_no_blockers(declared, context)

	if not flow or flow == root_script:
		_clear_state(row.name)
	else:
		allowed = {f["name"] for f in _flows(root_script, frame.get("subflow")) if not f["is_root"]}
		if flow not in allowed:
			frappe.throw(_("{0} is not a flow of {1}").format(flow, root_script))
		initial = _subflow_initial_state(flow)
		if not initial:
			frappe.throw(_("Flow {0} has no initial state").format(flow))
		_save_state(
			row.name,
			seeded_frame(root_script, {"subflow": flow, "state": initial, "context": {}}),
			timeout,
		)

	session = _read_session(row)
	_publish_session_update(row.name, session)
	return session


@frappe.whitelist(methods=["POST"])
def run_scanner_command(scanner=None, command=None):
	"""Press a command button: run its barcode exactly as the device would have scanned it.

	Only a command the current state declares is accepted, so the phone can do nothing at a
	step that the printed barcode sheet could not do at the same step. The work itself goes
	through `run_scan` — same script, same frame, same scan log — and the refreshed session
	comes back so the screen redraws from what actually happened.
	"""
	from erpnext.devices.doctype.scanner.scanner_api import run_scan

	row = _assert_scanner_mine(scanner)
	command = (command or "").strip()
	if not command:
		frappe.throw(_("Command is required"))

	frame = _load_state(row.name, _state_timeout(row)) or {}
	root_script = _root_script_name(row)
	active_script = frame.get("subflow") or root_script
	offered = {c["command"] for c in _state_commands(active_script, frame.get("state"))}
	if command not in offered:
		frappe.throw(_("{0} is not available at this step").format(command))

	# `run_scan` impersonates the scanner's employee, exactly as a device scan does. The
	# caller is that employee anyway (`_assert_scanner_mine`), but restore the whole session,
	# not just the user: `set_user` empties it, and saving that back logs the phone out.
	with preserved_session():
		result = run_scan(frappe.get_doc("Scanner", row.name), command)

	session = _read_session(_scanner_row(row.name))
	_publish_session_update(row.name, session)
	return {"result": result, "session": session}


@frappe.whitelist(methods=["POST"])
def reset_scanner_session(scanner=None):
	"""What the CMD-RESET barcode does, from the app.

	Deliberately the same rule rather than a plain wipe: inside a subflow the operator
	expects to land back at that subflow's start, not to be thrown out of the flow.
	"""
	row = _assert_scanner_mine(scanner)
	timeout = _state_timeout(row)
	frame = _load_state(row.name, timeout) or {}

	new_frame, _message = reset_frame(frame)
	if new_frame:
		_save_state(row.name, seeded_frame(_root_script_name(row), new_frame), timeout)
	else:
		_clear_state(row.name)

	session = _read_session(row)
	_publish_session_update(row.name, session)
	return session


# ---------------------------------------------------------------------------
# Write-path helpers
# ---------------------------------------------------------------------------


def _root_script_name(scanner_row):
	if not scanner_row.get("workplace"):
		return None
	script_doc = _get_workplace_script(scanner_row.get("workplace"))
	return script_doc.name if script_doc else None


def _require_editable(declared, key, state=None):
	"""The declaration for `key`, or a throw.

	Only app-editable keys are addressable, and only at the step of the flow that asks for
	them: once the order is chosen the template is settled, and rewriting it behind the
	operator's back would relabel boxes they have already packed.
	"""
	if not key:
		frappe.throw(_("Context field key is required"))

	decl = declared.get(key)
	if not decl:
		frappe.throw(_("Unknown context field {0}").format(key))
	if not cint(decl.get("app_editable")):
		frappe.throw(_("Context field {0} is not editable from the app").format(key))
	if not _editable_now(decl, state):
		frappe.throw(
			_("{0} cannot be changed at this step — reset the session to change it").format(
				decl.get("label") or key
			)
		)
	return decl


def _coerce_value(decl, value):
	fieldtype = decl.get("fieldtype") or "Data"

	if fieldtype == "Check":
		return 1 if cint(value) else 0
	if fieldtype == "Int":
		return cint(value)
	if fieldtype == "Float":
		return flt(value)

	value = (value or "").strip() if isinstance(value, str) else value
	if value in (None, ""):
		return None

	if fieldtype == "Select":
		options = [o.strip() for o in (decl.get("options") or "").split("\n") if o.strip()]
		if value not in options:
			frappe.throw(_("{0} is not a valid option for {1}").format(value, decl.get("key")))
		return value

	if fieldtype == "Link":
		doctype = _link_doctype(decl)
		if not frappe.db.exists(doctype, value):
			frappe.throw(_("{0} {1} not found").format(_(doctype), value), frappe.DoesNotExistError)
		# The same filters the picker applies, re-checked here: a client that skipped the
		# picker must not be able to park a draft order on the scanner.
		filters = _link_filters(decl)
		if filters:
			filters["name"] = value
			if not frappe.db.get_all(doctype, filters=filters, limit_page_length=1):
				frappe.throw(_("{0} {1} is not available for selection").format(_(doctype), value))
		return value

	return value


def _target_state(decl, frame, declared):
	"""Where the session lands after the write.

	`enter_state` is validated at save time too, but declarations are not versioned while
	states are — a version rollback can leave it pointing at a state the running snapshot
	no longer has. Keeping the current state is the safe fallback; the script's own
	defensive `ctx.get()` guards handle the rest.
	"""
	enter_state = (decl.get("enter_state") or "").strip()
	if not enter_state:
		return frame.get("state")

	script = frame.get("subflow") or decl.get("source_script")
	if script and enter_state not in _snapshot_states(script):
		frappe.logger("scanner").warning(
			f"{script}: context field {decl.get('key')} names enter_state "
			f"'{enter_state}', which the running version does not define"
		)
		return frame.get("state")
	return enter_state


def _subflow_for(decl):
	"""Starting a session from the app enters the declaring script if it is a subflow."""
	script = decl.get("source_script")
	if not script:
		return None
	if not frappe.db.get_value("Workplace Script", script, "parent_script"):
		return None
	# Only meaningful if that subflow actually has somewhere to start.
	return script if _subflow_initial_state(script) else None
