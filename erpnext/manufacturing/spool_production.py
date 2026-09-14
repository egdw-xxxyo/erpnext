"""Spool line endpoints for the Android OTDR app.

The work is done by the generic `Production Line` engine
(`erpnext.manufacturing.doctype.production_line.production_line`); this module only pins the
line type to "Spool" and adds what is specific to spools. The endpoint names are what the
released app calls, so they stay put.

The serial is assigned here rather than typed at the bench: the operator is told which spool
they are winding, which is also what removes the mistyped-serial case from
`otdr_measurement_api.submit_measurement`.
"""

import frappe

from erpnext.manufacturing.doctype.production_line import production_line

LINE_TYPE = "Spool"


@frappe.whitelist(methods=["GET"])
def get_production_plan(workplace=None, **kwargs):
	"""What this bench is supposed to wind today, and how much of it is left."""
	return production_line.get_plan(LINE_TYPE, workplace=workplace)


@frappe.whitelist(methods=["POST"])
def next_spool(workplace=None, item_code=None, **kwargs):
	"""Hand the operator the next spool to wind, opening an overflow Work Order if needed.

	Returns the serial the app then shows on screen and sends back with the measurement, so
	the spool is identified without anybody reading a number off a label.
	"""
	from erpnext.devices.otdr_measurement_api import _assert_workplace_allowed, _session_employee

	if workplace:
		_assert_workplace_allowed(workplace, _session_employee())
	return production_line.next_unit(LINE_TYPE, workplace=workplace, item_code=item_code)


@frappe.whitelist(methods=["POST"])
def release_spool(job_card=None, **kwargs):
	"""Put an unwound spool back in the pool — the operator picked it up and walked away."""
	return production_line.release_unit(job_card)


@frappe.whitelist(methods=["POST"])
def finish_spool(job_card=None, workplace=None, **kwargs):
	"""Take a measured spool off the winder: close its Job Card and put it into stock.

	A rejected spool stays on its card for whoever decides between scrap and rewind.
	"""
	from erpnext.devices.otdr_measurement_api import _assert_workplace_allowed, _session_employee

	if workplace:
		_assert_workplace_allowed(workplace, _session_employee())
	return production_line.finish_unit(job_card)
