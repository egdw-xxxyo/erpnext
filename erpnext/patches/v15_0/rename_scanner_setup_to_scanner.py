import frappe


def execute():
	if not frappe.db.exists("DocType", "Scanner Setup"):
		return

	# If "Scanner" already exists, just delete "Scanner Setup"
	if frappe.db.exists("DocType", "Scanner"):
		frappe.delete_doc("DocType", "Scanner Setup", force=True)
	else:
		frappe.rename_doc("DocType", "Scanner Setup", "Scanner", force=True)

	# Rename "Scanner1" record to "Scanner" if it exists
	if frappe.db.exists("Scanner", "Scanner1"):
		frappe.rename_doc("Scanner", "Scanner1", "Scanner", force=True)

	# Migrate existing Scanner Scan Log records into child table rows
	if frappe.db.exists("DocType", "Scanner Scan Log"):
		logs = frappe.db.sql(
			"""
			SELECT scanner, timestamp, raw_data, status, resolved_action,
				scanner_mode, target_doctype, target_document,
				result_message, error_message
			FROM `tabScanner Scan Log`
			ORDER BY timestamp ASC
		""",
			as_dict=True,
		)

		scanners = {}
		for log in logs:
			scanner_name = log.get("scanner")
			if not scanner_name:
				continue
			scanners.setdefault(scanner_name, []).append(log)

		for scanner_name, scanner_logs in scanners.items():
			if not frappe.db.exists("Scanner", scanner_name):
				continue

			# Keep only last 100
			scanner_logs = scanner_logs[-100:]

			doc = frappe.get_doc("Scanner", scanner_name)
			for log in scanner_logs:
				doc.append(
					"scan_logs",
					{
						"timestamp": log.get("timestamp"),
						"raw_data": log.get("raw_data"),
						"status": log.get("status"),
						"resolved_action": log.get("resolved_action"),
						"target_doctype": log.get("target_doctype"),
						"target_document": log.get("target_document"),
						"result_message": log.get("result_message"),
						"error_message": log.get("error_message"),
					},
				)
			doc.flags.ignore_permissions = True
			doc.save()

		# Drop the old Scanner Scan Log table
		frappe.delete_doc("DocType", "Scanner Scan Log", force=True)

	frappe.db.commit()
