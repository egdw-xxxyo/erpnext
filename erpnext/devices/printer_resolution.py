"""Which printer a label comes out of.

The label template says *what* to print; the bench says *where*. A Workplace Script may
now run at several benches (`Workplace Script.workplaces`), so a printer named on a
Packing Template or on an Item is no longer enough on its own — two benches sharing one
script would both print at the first bench's printer.

Precedence, most specific first:

  1. the printer the operator picked (the app's printer picker)
  2. the bench's own printer — the `Workplace Printer` row whose `purpose` matches,
     else the row marked default, else the only row when the bench has just one
  3. the printer named on the document being printed (Packing Template, Item Label
     Template), passed in as `fallback`
  4. anything else the caller offers as a later fallback

`resolve_printer` returns `(printer, source)` so callers can log which tier answered.
"""

import frappe
from frappe import _

SOURCE_EXPLICIT = "explicit"
SOURCE_WORKPLACE = "workplace"
SOURCE_FALLBACK = "fallback"


def _workplace_name(workplace):
	if not workplace:
		return None
	if isinstance(workplace, str):
		return workplace
	return workplace.get("name")


def printers_for_workplace(workplace):
	"""Every printer a workplace declares, for the app's picker."""
	name = _workplace_name(workplace)
	if not name:
		return []

	return frappe.get_all(
		"Workplace Printer",
		filters={"parent": name, "parenttype": "Workplace"},
		fields=["label_printer", "printer_model", "ip_address", "is_default", "purpose"],
		order_by="is_default desc, idx",
	)


def workplace_printer(workplace, purpose=None):
	"""The bench's printer for `purpose`, else its default printer.

	`Workplace.printers` allows several — a bench with a spool printer and a box printer —
	with at most one marked default (enforced in `Workplace._validate_printers`). `purpose`
	is free text matched case- and space-insensitively, the same convention as
	`Item Label Template.purpose`.
	"""
	rows = printers_for_workplace(workplace)
	if not rows:
		return None

	if purpose:
		wanted = purpose.strip().casefold()
		for row in rows:
			if (row.get("purpose") or "").strip().casefold() == wanted:
				return row.get("label_printer")

	for row in rows:
		if row.get("is_default"):
			return row.get("label_printer")

	# A bench with one printer has nothing to choose between: nobody ticks "default" on the
	# only row, and refusing to print there looked like a broken printer to the operator.
	if len(rows) == 1:
		return rows[0].get("label_printer")

	return None


def resolve_printer(workplace=None, explicit=None, purpose=None, fallbacks=()):
	"""Pick the printer to use, returning `(printer, source)`.

	`fallbacks` are tried in order after the bench, and each may be either a printer name or
	a callable returning one (so an expensive lookup only runs when the earlier tiers came
	up empty).
	"""
	if explicit:
		return explicit, SOURCE_EXPLICIT

	printer = workplace_printer(workplace, purpose=purpose)
	if printer:
		return printer, SOURCE_WORKPLACE

	for candidate in fallbacks or ():
		value = candidate() if callable(candidate) else candidate
		if value:
			return value, SOURCE_FALLBACK

	return None, None


@frappe.whitelist()
def printer_for_workplace(workplace, purpose=None):
	"""Whitelisted lookup for clients and Workplace Scripts that only need the name."""
	return workplace_printer(workplace, purpose=purpose)


def _problem(code, message, short):
	return {"code": code, "message": message, "short": short}


def printer_problems(workplace, purpose=None, label_template=None, probe=False):
	"""Everything that stops a label coming out at this bench, as a list of problems.

	One check shared by every Workplace Script that prints, the scanner runtime and the app,
	so each of them warns about the same things in the same words. Empty list — good to go.
	Each problem is `{"code", "message", "short"}`: `message` for the app and the desk,
	`short` for a 20-column scanner display.

	`label_template` adds the label-size check: the roll loaded in the printer must match
	the size the template prints. `probe` also opens a TCP connection to the printer — up
	to three seconds when it is off, so callers use it on a flow switch, not on every scan.
	"""
	name = _workplace_name(workplace)
	if not name:
		return [_problem("no_workplace", _("No workplace selected"), _("No workplace"))]

	rows = printers_for_workplace(name)
	if not rows:
		return [
			_problem(
				"no_printer",
				_("Workplace {0} has no printer").format(name),
				_("No printer"),
			)
		]

	printer = workplace_printer(name, purpose=purpose)
	if not printer:
		return [
			_problem(
				"no_default_printer",
				_("Workplace {0} has several printers but none is default").format(name),
				_("No default printer"),
			)
		]

	doc = frappe.db.get_value(
		"Label Printer",
		printer,
		[
			"name",
			"is_enabled",
			"mock_printing",
			"ip_address",
			"loaded_label_size",
			"is_label_change_in_progress",
		],
		as_dict=True,
	)
	if not doc:
		return [
			_problem("printer_missing", _("Printer {0} not found").format(printer), _("Printer not found"))
		]
	if not doc.is_enabled:
		return [
			_problem("printer_disabled", _("Printer {0} is disabled").format(printer), _("Printer disabled"))
		]

	problems = []
	if not doc.mock_printing and not doc.ip_address:
		problems.append(
			_problem("no_ip", _("Printer {0} has no IP address").format(printer), _("Printer has no IP"))
		)
	if doc.is_label_change_in_progress:
		problems.append(
			_problem(
				"label_change",
				_("Printer {0} is changing labels").format(printer),
				_("Changing labels"),
			)
		)

	size = frappe.db.get_value("Label Template", label_template, "label_size") if label_template else None
	if size and doc.loaded_label_size and size != doc.loaded_label_size:
		problems.append(
			_problem(
				"label_size",
				_("Printer {0} has {1} loaded, labels need {2}").format(printer, doc.loaded_label_size, size),
				_("Wrong label size"),
			)
		)

	if probe and not problems and not doc.mock_printing:
		from erpnext.devices.doctype.label_printer.label_printer import check_connection

		try:
			connected = check_connection(printer).get("connected")
		except Exception:
			connected = False
		if not connected:
			problems.append(
				_problem("offline", _("Printer {0} is not responding").format(printer), _("Printer offline"))
			)

	return problems


def script_printer_requirement(script_name):
	"""`(purpose, label_template)` when this Workplace Script prints, else None."""
	if not script_name:
		return None
	row = frappe.db.get_value(
		"Workplace Script",
		script_name,
		["requires_printer", "printer_purpose", "printer_label_template"],
		as_dict=True,
	)
	if not row or not row.requires_printer:
		return None
	return row.printer_purpose or None, row.printer_label_template or None


def script_printer_problems(script_name, workplace, probe=False):
	"""`printer_problems` for a Workplace Script's own declared needs; empty if it never prints."""
	requirement = script_printer_requirement(script_name)
	if not requirement:
		return []
	purpose, label_template = requirement
	return printer_problems(workplace, purpose=purpose, label_template=label_template, probe=probe)


@frappe.whitelist()
def check_workplace_printer(workplace=None, purpose=None, label_template=None, probe=1):
	"""Desk/app check: what would stop this bench printing."""
	return printer_problems(workplace, purpose=purpose, label_template=label_template, probe=int(probe or 0))
