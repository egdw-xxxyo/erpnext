import json

import frappe
from frappe import _
from frappe.model.document import Document


class StateMachineError(Exception):
	pass


class TransitionError(Exception):
	pass


class _GuardedStateProxy:
	"""Wraps the real ScannerStateProxy to enforce declared transitions.

	`e.state.set(target, ctx)` is allowed only if (current_state, target) is in the
	Transitions table — or if target == current_state (self-transition is always allowed,
	used to update context). `e.state.clear()` is always allowed (reset to initial).
	"""

	__slots__ = ("_real", "_current", "_allowed")

	def __init__(self, real, current_state, allowed_targets):
		object.__setattr__(self, "_real", real)
		object.__setattr__(self, "_current", current_state)
		object.__setattr__(self, "_allowed", allowed_targets)

	@property
	def name(self):
		return self._real.name

	@property
	def context(self):
		return self._real.context

	@property
	def subflow(self):
		return getattr(self._real, "subflow", None)

	def set(self, state_name, context=None):
		if state_name != self._current and state_name not in self._allowed:
			raise TransitionError(f"{self._current} → {state_name}")
		self._real.set(state_name, context)

	def update(self, patch, state_name=None):
		target = state_name or self._current
		if target != self._current and target not in self._allowed:
			raise TransitionError(f"{self._current} → {target}")
		self._real.update(patch, state_name)

	def set_subflow(self, subflow_name, state_name, context=None):
		self._real.set_subflow(subflow_name, state_name, context)

	def exit_subflow(self, state_name=None, context=None):
		self._real.exit_subflow(state_name, context)

	def clear(self):
		self._real.clear()


def _serialize_state(s):
	return {
		"state": s.state,
		"label": s.label,
		"is_initial": int(s.is_initial or 0),
		"is_final": int(s.is_final or 0),
		"position_x": s.position_x,
		"position_y": s.position_y,
		"on_enter_script": s.on_enter_script,
	}


def _serialize_transition(t):
	return {"from_state": t.from_state, "event": t.event, "to_state": t.to_state}


def _capture_working_copy(doc):
	return {
		"script": doc.script or "",
		"states": [_serialize_state(s) for s in (doc.states or [])],
		"transitions": [_serialize_transition(t) for t in (doc.transitions or [])],
	}


def _load_snapshot(row):
	try:
		return json.loads(row.snapshot or "{}")
	except Exception:
		return {}


def _resolve_default_snapshot(ws):
	row = next((v for v in (ws.versions or []) if v.is_default), None)
	if not row:
		return _capture_working_copy(ws)
	return _load_snapshot(row)


class WorkplaceScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.devices.doctype.workplace_script_context_field.workplace_script_context_field import (
			WorkplaceScriptContextField,
		)

		default_version: DF.Data | None
		is_active: DF.Check
		parent_script: DF.Link | None
		script: DF.Code | None
		script_name: DF.Data | None
		context_fields: DF.Table[WorkplaceScriptContextField]
		viewing_version: DF.Data | None
		workplace: DF.Link | None

	def validate(self):
		if self.parent_script:
			if self.workplace:
				frappe.throw("Subflow scripts (with Parent Script) must not have a Workplace assigned")
			if self.parent_script == self.name:
				frappe.throw("Parent Script cannot reference itself")
		elif self.is_active:
			filters = {"is_active": 1, "name": ["!=", self.name], "parent_script": ["is", "not set"]}
			if self.workplace:
				filters["workplace"] = self.workplace
				existing = frappe.db.exists("Workplace Script", filters)
				if existing:
					frappe.throw(
						f"An active Workplace Script already exists for workplace {self.workplace}: {existing}"
					)
			else:
				filters["workplace"] = ["is", "not set"]
				existing = frappe.db.exists("Workplace Script", filters)
				if existing:
					frappe.throw(
						f"An active default Workplace Script (no workplace) already exists: {existing}"
					)

		self._ensure_versions()
		self._validate_state_machine()
		self._validate_context_fields()

	def _ensure_versions(self):
		if not self.versions:
			self.append(
				"versions",
				{
					"version": "v1",
					"is_default": 1,
					"snapshot": json.dumps(_capture_working_copy(self)),
					"created_on": frappe.utils.now_datetime(),
				},
			)
			self.default_version = "v1"
			self.viewing_version = "v1"

		defaults = [v for v in self.versions if v.is_default]
		if len(defaults) == 0:
			self.versions[0].is_default = 1
			defaults = [self.versions[0]]
		elif len(defaults) > 1:
			frappe.throw("Exactly one version must be marked as default")

		self.default_version = defaults[0].version

		if not self.viewing_version:
			self.viewing_version = self.default_version
		target = next((v for v in self.versions if v.version == self.viewing_version), None)
		if target is None:
			frappe.throw(f"Viewing version {self.viewing_version} not found")
		target.snapshot = json.dumps(_capture_working_copy(self))

	def _validate_state_machine(self):
		if not self.states and not self.transitions:
			return

		state_names = [s.state for s in self.states]
		dupes = {n for n in state_names if state_names.count(n) > 1}
		if dupes:
			frappe.throw(f"Duplicate state names: {', '.join(sorted(dupes))}")

		initials = [s for s in self.states if s.is_initial]
		if len(initials) > 1:
			frappe.throw("Only one state may be marked as Initial")

		valid = set(state_names)
		for t in self.transitions:
			if t.from_state not in valid:
				frappe.throw(f"Transition {t.idx}: from_state '{t.from_state}' is not in States")
			if t.to_state and t.to_state != "__exit__" and t.to_state not in valid:
				frappe.throw(f"Transition {t.idx}: to_state '{t.to_state}' is not in States")

	def _validate_context_fields(self):
		"""Validate the declared context contract.

		Declarations are purely descriptive for the scanner runtime — a script without any
		row behaves exactly as it did before — so everything here is skipped when the table
		is empty.
		"""
		if not self.context_fields:
			return

		keys = []
		for row in self.context_fields:
			row.key = (row.key or "").strip()
			if not row.key:
				frappe.throw(_("Context field {0}: Key is required").format(row.idx))
			keys.append(row.key)

		dupes = {k for k in keys if keys.count(k) > 1}
		if dupes:
			frappe.throw(_("Duplicate context field keys: {0}").format(", ".join(sorted(dupes))))

		snapshot_states = {s.get("state") for s in (_resolve_default_snapshot(self).get("states") or [])}
		known_states = {s.state for s in (self.states or [])} | snapshot_states

		for row in self.context_fields:
			if row.fieldtype in ("Link", "Select") and not (row.options or "").strip():
				frappe.throw(
					_("Context field {0}: Options is required for a {1} field").format(row.key, row.fieldtype)
				)

			if row.is_primary and not row.app_editable:
				frappe.throw(_("Context field {0}: Primary requires App Editable").format(row.key))

			if row.is_primary and row.preserve_on_switch:
				frappe.throw(
					_(
						"Context field {0}: Primary cannot be Preserve On Switch — the primary key is always rewritten by the switch"
					).format(row.key)
				)

			enter_state = (row.enter_state or "").strip()
			if enter_state and enter_state not in known_states:
				frappe.throw(
					_("Context field {0}: Enter State '{1}' is not a state of this script").format(
						row.key, enter_state
					)
				)

			if (row.link_filters or "").strip():
				try:
					parsed = json.loads(row.link_filters)
				except ValueError:
					frappe.throw(_("Context field {0}: Link Filters is not valid JSON").format(row.key))
				if not isinstance(parsed, dict):
					frappe.throw(_("Context field {0}: Link Filters must be a JSON object").format(row.key))


@frappe.whitelist()
def get_diagram_extras(script_name):
	"""Return reachable subflows + this script's entries, for diagram enrichment.

	For a root script: subflows = its children.
	For a subflow: subflows = siblings (children of its parent_script).
	entries = this script's own Subflow Entries rows.
	"""
	this_doc = frappe.get_cached_doc("Workplace Script", script_name)
	parent = this_doc.parent_script
	if parent:
		sibling_rows = frappe.get_all(
			"Workplace Script",
			filters={"parent_script": parent, "name": ["!=", script_name]},
			fields=["name"],
		)
	else:
		sibling_rows = frappe.get_all(
			"Workplace Script",
			filters={"parent_script": script_name},
			fields=["name"],
		)

	out_subflows = []
	for sf in sibling_rows:
		try:
			doc = frappe.get_cached_doc("Workplace Script", sf.name)
			snap = _resolve_default_snapshot(doc)
			initial = next((s.get("state") for s in (snap.get("states") or []) if s.get("is_initial")), None)
		except Exception:
			initial = None
		out_subflows.append({"name": sf.name, "initial_state": initial})

	entries = frappe.get_all(
		"Workplace Script Subflow Entry",
		filters={"parent": script_name, "parenttype": "Workplace Script", "parentfield": "subflow_entries"},
		fields=["from_state", "trigger_type", "trigger_value", "target_subflow", "description"],
		order_by="idx asc",
	)
	return {"subflows": out_subflows, "entries": entries}


def run_state(script_name, e, scripts=None, handler="on_scan"):
	"""Dispatch an event to the current state's script.

	Reads states/transitions from the default version's snapshot, not the working copy.
	If Redis state is empty, falls back to the row marked as initial.

	`handler` names the function the state script must define. It defaults to `on_scan` so
	every existing scanner script body keeps working untouched; the OTDR measurement path
	passes `on_measurement`, which lets one workplace answer both a barcode scan and a
	reflectometer trace without the two handlers colliding.
	"""
	ws = frappe.get_cached_doc("Workplace Script", script_name)
	snap = _resolve_default_snapshot(ws)
	states = snap.get("states", []) or []
	transitions = snap.get("transitions", []) or []

	current = e.state.name
	state_row = None
	if current:
		state_row = next((s for s in states if s.get("state") == current), None)

	if not state_row:
		state_row = next((s for s in states if s.get("is_initial")), None)
		if not state_row:
			raise StateMachineError(f"No initial state defined on {script_name}")
		current = state_row.get("state")

	code = state_row.get("on_enter_script") or ""
	if not code.strip():
		return None

	allowed = {t["to_state"] for t in transitions if t.get("from_state") == current}
	real_proxy = e.state
	guard = _GuardedStateProxy(real_proxy, current, allowed)
	e.state = guard

	try:
		ns = {"frappe": frappe, "scripts": scripts, "e": e}
		exec(code, ns)

		fn = ns.get(handler)
		if not fn:
			return None
		return fn(e)
	except TransitionError as ex:
		td = None
		if scripts and hasattr(scripts, "display") and hasattr(scripts.display, "td"):
			td = scripts.display.td
		text = f"Помилка переходу\n{ex}"
		return td(text) if td else {"templateData": text}
	finally:
		e.state = real_proxy
