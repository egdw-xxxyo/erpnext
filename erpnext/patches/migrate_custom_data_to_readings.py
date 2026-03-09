"""
One-time migration: convert Production Log.custom_data JSON to
Production Log Field child table rows.

Run inside container:
  bench --site frontend execute erpnext.patches.migrate_custom_data_to_readings.run
"""
import json

import frappe


def run():
	logs = frappe.get_all(
		"Production Log",
		filters={"custom_data": ["is", "set"]},
		fields=["name", "custom_data", "operation"],
	)

	op_fields_cache = {}

	def get_op_fields(operation):
		if operation not in op_fields_cache:
			op_fields_cache[operation] = {
				f.fieldname: f
				for f in frappe.get_all(
					"Operation Field",
					filters={"parent": operation, "parenttype": "Operation"},
					fields=["fieldname", "label", "fieldtype"],
				)
			}
		return op_fields_cache[operation]

	migrated = 0
	for log in logs:
		try:
			data = json.loads(log.custom_data)
		except (json.JSONDecodeError, TypeError):
			continue

		if not data:
			continue

		plog = frappe.get_doc("Production Log", log.name)

		if plog.readings:
			continue

		fields_map = get_op_fields(log.operation) if log.operation else {}
		for fieldname, value in data.items():
			field_def = fields_map.get(fieldname, {})
			plog.append("readings", {
				"operation_field": fieldname,
				"label": field_def.get("label", fieldname),
				"fieldtype": field_def.get("fieldtype", "Data"),
				"value": str(value) if value is not None else "",
			})

		plog.save(ignore_permissions=True)
		migrated += 1

	frappe.db.commit()
	print(f"Migrated {migrated} Production Logs")
