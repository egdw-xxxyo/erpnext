import frappe
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

	def set(self, state_name, context=None):
		if state_name != self._current and state_name not in self._allowed:
			raise TransitionError(f"{self._current} → {state_name}")
		self._real.set(state_name, context)

	def clear(self):
		self._real.clear()


class WorkplaceScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_active: DF.Check
		script: DF.Code | None
		script_name: DF.Data | None
		workplace: DF.Link | None

	def validate(self):
		if self.is_active:
			filters = {"is_active": 1, "name": ["!=", self.name]}
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

		self._validate_state_machine()

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
			if t.to_state not in valid:
				frappe.throw(f"Transition {t.idx}: to_state '{t.to_state}' is not in States")


def run_state(script_name, e, scripts=None):
	"""Dispatch a scan to the current state's script.

	If Redis state is empty, falls back to the row marked as initial.
	The state's script must define `on_scan(e)`. The state's script may transition
	via `e.state.set(name, ctx)` (validated against the Transitions table) or
	`e.state.clear()` (always allowed).
	"""
	ws = frappe.get_cached_doc("Workplace Script", script_name)

	current = e.state.name
	state_row = None
	if current:
		state_row = next((s for s in ws.states if s.state == current), None)

	if not state_row:
		state_row = next((s for s in ws.states if s.is_initial), None)
		if not state_row:
			raise StateMachineError(f"No initial state defined on {script_name}")
		current = state_row.state

	code = state_row.on_enter_script
	if not code or not code.strip():
		return None

	allowed = {t.to_state for t in ws.transitions if t.from_state == current}
	real_proxy = e.state
	guard = _GuardedStateProxy(real_proxy, current, allowed)
	e.state = guard

	try:
		ns = {"frappe": frappe, "scripts": scripts, "e": e}
		exec(code, ns)  # noqa: S102

		handler = ns.get("on_scan")
		if not handler:
			return None
		return handler(e)
	except TransitionError as ex:
		td = None
		if scripts and hasattr(scripts, "display") and hasattr(scripts.display, "td"):
			td = scripts.display.td
		text = f"Помилка переходу\n{ex}"
		return td(text) if td else {"templateData": text}
	finally:
		e.state = real_proxy
