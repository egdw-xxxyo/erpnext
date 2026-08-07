import frappe


def execute():
	if not frappe.db.sql("SHOW TABLES LIKE 'tabPacking Box'"):
		return

	rows = frappe.db.sql("SELECT * FROM `tabPacking Box`", as_dict=True)
	for row in rows:
		old_name = row["name"]
		new_name = old_name.replace("BOX-", "PKG-", 1) if old_name.startswith("BOX-") else old_name

		if frappe.db.exists("Package", new_name):
			continue

		row["name"] = new_name
		row["box_barcode"] = new_name
		if row.get("amended_from") and row["amended_from"].startswith("BOX-"):
			row["amended_from"] = row["amended_from"].replace("BOX-", "PKG-", 1)

		cols = ", ".join([f"`{k}`" for k in row.keys()])
		vals = ", ".join(["%s"] * len(row))
		frappe.db.sql(
			f"INSERT INTO `tabPackage` ({cols}) VALUES ({vals})",
			list(row.values()),
		)

		items = frappe.db.sql(
			"SELECT * FROM `tabPacking Box Item` WHERE parent=%s",
			old_name,
			as_dict=True,
		)
		for item in items:
			item["parent"] = new_name
			item["parenttype"] = "Package"
			item["parentfield"] = "items"
			icols = ", ".join([f"`{k}`" for k in item.keys()])
			ivals = ", ".join(["%s"] * len(item))
			frappe.db.sql(
				f"INSERT INTO `tabPackage Item` ({icols}) VALUES ({ivals})",
				list(item.values()),
			)

	# Clean up old DocType metadata (tables left as-is to avoid implicit commit)
	for dt in ("Packing Box Item", "Packing Box"):
		frappe.db.sql(f"DELETE FROM `tab{dt}`")
		frappe.db.sql("DELETE FROM `tabDocType` WHERE name=%s", dt)
		frappe.db.sql("DELETE FROM `tabDocField` WHERE parent=%s", dt)
		frappe.db.sql("DELETE FROM `tabDocPerm` WHERE parent=%s", dt)
