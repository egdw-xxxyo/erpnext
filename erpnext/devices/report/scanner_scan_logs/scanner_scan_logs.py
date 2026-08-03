import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Timestamp"), "fieldname": "timestamp", "fieldtype": "Datetime", "width": 165},
		{"label": _("Scanner"), "fieldname": "scanner", "fieldtype": "Link", "options": "Scanner", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Scanned Data"), "fieldname": "raw_data", "fieldtype": "Data", "width": 180},
		{"label": _("State"), "fieldname": "scanner_state", "fieldtype": "Data", "width": 130},
		{"label": _("Target Document"), "fieldname": "target_document", "fieldtype": "Dynamic Link", "options": "target_doctype", "width": 170},
		{"label": _("Result"), "fieldname": "result_message", "fieldtype": "Small Text", "width": 220},
		{"label": _("Error"), "fieldname": "error_message", "fieldtype": "Small Text", "width": 200},
		{"label": _("Total (ms)"), "fieldname": "total_ms", "fieldtype": "Int", "width": 90},
		{"label": _("Script (ms)"), "fieldname": "script_ms", "fieldtype": "Int", "width": 90},
		{"label": _("Resolve (ms)"), "fieldname": "resolve_ms", "fieldtype": "Int", "width": 100},
	]


def get_data(filters):
	conditions = ["parenttype = 'Scanner'"]
	values = {}

	if filters.get("scanner"):
		conditions.append("parent = %(scanner)s")
		values["scanner"] = filters.scanner
	if filters.get("status"):
		conditions.append("status = %(status)s")
		values["status"] = filters.status
	if filters.get("from_date"):
		conditions.append("timestamp >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("timestamp <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("only_slow"):
		conditions.append("total_ms > %(slow_ms)s")
		values["slow_ms"] = filters.get("slow_ms") or 1000

	return frappe.db.sql(
		"""SELECT parent AS scanner, timestamp, status, raw_data, scanner_state,
			target_doctype, target_document, result_message, error_message,
			total_ms, script_ms, resolve_ms
		FROM `tabScanner Scan Log Entry`
		WHERE {conditions}
		ORDER BY timestamp DESC
		LIMIT 500""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)
