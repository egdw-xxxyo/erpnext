"""Which printer a label comes out of.

The label template says *what* to print; the bench says *where*. A Workplace Script may
now run at several benches (`Workplace Script.workplaces`), so a printer named on a
Packing Template or on an Item is no longer enough on its own — two benches sharing one
script would both print at the first bench's printer.

Precedence, most specific first:

  1. the printer the operator picked (the app's printer picker)
  2. the bench's own printer — the `Workplace Printer` row whose `purpose` matches,
     else the row marked default
  3. the printer named on the document being printed (Packing Template, Item Label
     Template), passed in as `fallback`
  4. anything else the caller offers as a later fallback

`resolve_printer` returns `(printer, source)` so callers can log which tier answered.
"""

import frappe

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
