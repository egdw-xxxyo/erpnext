import frappe

LEGACY_DOCTYPES = ["BPLA spec", "BPLA spec 10", "Battery Spec", "FO spec"]


def execute():
	for doctype in LEGACY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		for f in meta.fields:
			if f.fieldtype in (
				"Section Break", "Column Break", "Tab Break", "Heading",
				"Button", "HTML", "Read Only",
			):
				continue
			if f.read_only:
				continue
			_set_read_only(doctype, f.fieldname)
	frappe.db.commit()
	frappe.clear_cache()


def _set_read_only(doctype, fieldname):
	existing = frappe.db.exists(
		"Property Setter",
		{"doc_type": doctype, "field_name": fieldname, "property": "read_only"},
	)
	if existing:
		frappe.db.set_value("Property Setter", existing, "value", "1")
		return
	doc = frappe.get_doc({
		"doctype": "Property Setter",
		"doctype_or_field": "DocField",
		"doc_type": doctype,
		"field_name": fieldname,
		"property": "read_only",
		"property_type": "Check",
		"value": "1",
	})
	doc.insert(ignore_permissions=True)
	print(f"  Set read_only on {doctype}.{fieldname}")
