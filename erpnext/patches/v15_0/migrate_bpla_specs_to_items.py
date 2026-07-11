import frappe


def execute():
	migrate_bpla_spec("BPLA spec", "drone_code", "паспорт", "назва")
	migrate_bpla_spec("BPLA spec 10", "drone_code", "паспорт", "назва")
	migrate_battery_spec()
	migrate_fo_spec()
	frappe.db.commit()


def migrate_bpla_spec(doctype, shifr_field, passport_field, name_field):
	if not frappe.db.exists("DocType", doctype):
		return
	cols = _columns(doctype)
	if "код_виробу" not in cols:
		return
	select_fields = ["name", "`код_виробу`"]
	for f in (shifr_field, passport_field, name_field):
		if f in cols:
			select_fields.append(f"`{f}`")
	rows = frappe.db.sql(
		f"""SELECT {', '.join(select_fields)} FROM `tab{doctype}`
		WHERE `код_виробу` IS NOT NULL AND `код_виробу` != ''""",
		as_dict=1,
	)
	for r in rows:
		item_code = r["код_виробу"]
		if not frappe.db.exists("Item", item_code):
			continue
		_upsert_param(item_code, "Шифр", r.get(shifr_field))
		_upsert_param(item_code, "Паспорт", r.get(passport_field))
		_upsert_param(item_code, "Найменування", r.get(name_field))
		_upsert_param(item_code, "Код виробу", item_code)
		_denormalize_custom_shifr(item_code, r.get(shifr_field))


def _columns(doctype):
	rows = frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`")
	return {r[0] for r in rows}


def migrate_battery_spec():
	if not frappe.db.exists("DocType", "Battery Spec"):
		return
	cols = _columns("Battery Spec")
	if "код_виробу" not in cols:
		return
	shifr_col = "`код_єскд`" if "код_єскд" in cols else "NULL AS `код_єскд`"
	rows = frappe.db.sql(
		f"""SELECT name, `код_виробу`, {shifr_col} FROM `tabBattery Spec`
		WHERE `код_виробу` IS NOT NULL AND `код_виробу` != ''""",
		as_dict=1,
	)
	for r in rows:
		item_code = r["код_виробу"]
		if not frappe.db.exists("Item", item_code):
			continue
		_upsert_param(item_code, "Шифр", r.get("код_єскд"))
		_upsert_param(item_code, "Код виробу", item_code)
		_denormalize_custom_shifr(item_code, r.get("код_єскд"))


def migrate_fo_spec():
	if not frappe.db.exists("DocType", "FO spec"):
		return
	cols = _columns("FO spec")
	if "код_виробу" not in cols:
		return
	select_fields = ["name", "`код_виробу`"]
	for f in ("специфікація", "назва_за_єскд", "довжина_намотки_км"):
		if f in cols:
			select_fields.append(f"`{f}`")
	rows = frappe.db.sql(
		f"""SELECT {', '.join(select_fields)} FROM `tabFO spec`
		WHERE `код_виробу` IS NOT NULL AND `код_виробу` != ''""",
		as_dict=1,
	)
	for r in rows:
		item_code = r["код_виробу"]
		if not frappe.db.exists("Item", item_code):
			continue
		_upsert_param(item_code, "Шифр", r.get("специфікація"))
		_upsert_param(item_code, "Найменування", r.get("назва_за_єскд"))
		_upsert_param(item_code, "Код виробу", item_code)
		if r.get("довжина_намотки_км"):
			_upsert_param(item_code, "Довжина намотки", str(r["довжина_намотки_км"]))
		_denormalize_custom_shifr(item_code, r.get("специфікація"))


def _upsert_param(item_code, parameter, value):
	if not value:
		return
	if not frappe.db.exists("Quality Inspection Parameter", parameter):
		frappe.get_doc({"doctype": "Quality Inspection Parameter", "parameter": parameter}).insert(ignore_permissions=True)
	existing = frappe.db.exists(
		"Item Specification Parameter",
		{"parent": item_code, "parenttype": "Item", "parameter": parameter},
	)
	if existing:
		frappe.db.set_value("Item Specification Parameter", existing, "value", str(value))
		return
	row_name = frappe.generate_hash(length=10)
	frappe.db.sql(
		"""INSERT INTO `tabItem Specification Parameter`
		(name, creation, modified, owner, modified_by, parent, parenttype, parentfield, idx, parameter, value)
		VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, 'Item', 'item_spec_parameters',
		(SELECT COALESCE(MAX(idx),0)+1 FROM `tabItem Specification Parameter` t WHERE t.parent=%s), %s, %s)""",
		(row_name, item_code, item_code, parameter, str(value)),
	)


def _denormalize_custom_shifr(item_code, value):
	if not value:
		return
	frappe.db.set_value("Item", item_code, "custom_шифр", value, update_modified=False)
