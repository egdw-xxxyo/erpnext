from frappe import _


def get_data():
	"""Connections shown on the Serial No form.

	A spool can be measured more than once — re-wound, re-checked after a marginal result —
	so the reflectometer traces are listed here rather than summarised on the document. This
	is the "which measurements does this spool have" lookup that the old capped device-side
	log could not answer.
	"""
	return {
		"fieldname": "serial_no",
		"transactions": [
			{
				"label": _("Quality"),
				"items": ["OTDR Measurement"],
			},
		],
	}
