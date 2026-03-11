import json

import frappe
from frappe.utils import flt, get_link_to_form, now_datetime, time_diff_in_seconds

from erpnext.manufacturing.doctype.workstation.workstation import get_time_logs


def _get_workplace(workplace):
	return frappe.get_doc("Workplace", workplace)


def _get_status_color(status):
	color_map = {
		"Pending": "blue",
		"In Process": "yellow",
		"Submitted": "blue",
		"Open": "gray",
		"Not Started": "gray",
		"Closed": "green",
		"Work In Progress": "orange",
	}
	return color_map.get(status, "blue")


def _find_job_cards_by_serial_no(serial_no, operations):
	return frappe.get_all(
		"Job Card",
		fields=["name", "operation", "status", "production_item", "for_quantity", "workstation"],
		filters={
			"serial_no": ["like", f"%{serial_no}%"],
			"operation": ["in", operations],
			"docstatus": ("<", 2),
			"status": ["not in", ["Completed", "Stopped"]],
		},
		order_by="expected_start_date",
		limit=10,
	)


def _resolve_barcode_to_item(barcode):
	item_barcode = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	if item_barcode:
		return item_barcode

	serial_no = frappe.db.get_value("Serial No", barcode, "item_code")
	if serial_no:
		return serial_no

	if frappe.db.exists("Item", barcode):
		return barcode

	return None


def _resolve_material_barcode(barcode):
	if frappe.db.exists("Batch", barcode):
		item = frappe.db.get_value("Batch", barcode, "item")
		return "Batch", item, barcode, None

	item_code = frappe.db.get_value("Serial No", barcode, "item_code")
	if item_code:
		return "Serial No", item_code, None, barcode

	item_barcode = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	if item_barcode:
		return "Item Barcode", item_barcode, None, None

	if frappe.db.exists("Item", barcode):
		return "Item Barcode", barcode, None, None

	return "Unknown Label", None, None, None


def _parse_link_filters(filter_obj):
	if not filter_obj:
		return {}

	if isinstance(filter_obj, dict) and "and" not in filter_obj:
		return filter_obj

	tuples = []
	if isinstance(filter_obj, list) and len(filter_obj) == 3 and isinstance(filter_obj[0], str):
		tuples = [filter_obj]
	elif isinstance(filter_obj, dict) and "and" in filter_obj:
		tuples = filter_obj["and"]

	result = {}
	for t in tuples:
		if len(t) == 3:
			field, op, value = t
			if op == "=":
				result[field] = value
			else:
				result[field] = [op, value]
	return result


def _get_or_create_production_log(workplace, job_card):
	existing = frappe.db.get_value("Production Log", {"job_card": job_card}, "name")
	if existing:
		return frappe.get_doc("Production Log", existing)

	jc = frappe.get_doc("Job Card", job_card)
	plog = frappe.get_doc({
		"doctype": "Production Log",
		"job_card": job_card,
		"work_order": jc.work_order,
		"production_item": jc.production_item,
		"operation": jc.operation,
		"workplace": workplace,
	})
	plog.insert(ignore_permissions=True)
	return plog


@frappe.whitelist()
def get_workplaces():
	user = frappe.session.user
	if user == "Administrator":
		return frappe.get_all(
			"Workplace",
			filters={"is_active": 1},
			fields=["name", "workplace_name", "company"],
			order_by="workplace_name",
		)

	all_workplaces = frappe.get_all(
		"Workplace",
		filters={"is_active": 1},
		fields=["name", "workplace_name", "company"],
		order_by="workplace_name",
	)

	result = []
	for wp in all_workplaces:
		employees = frappe.get_all(
			"Workplace Employee",
			filters={"parent": wp.name, "parenttype": "Workplace"},
			fields=["user"],
		)
		if not employees or any(e.user == user for e in employees):
			result.append(wp)

	return result


@frappe.whitelist()
def get_job_cards(workplace):
	wp = _get_workplace(workplace)
	operations = [row.operation for row in wp.allowed_operations]
	if not operations:
		return []

	filters = {
		"operation": ["in", operations],
		"docstatus": ("<", 2),
		"status": ["not in", ["Completed", "Stopped"]],
	}

	jc_data = frappe.get_all(
		"Job Card",
		fields=[
			"name",
			"production_item",
			"work_order",
			"operation",
			"total_completed_qty",
			"for_quantity",
			"process_loss_qty",
			"transferred_qty",
			"status",
			"expected_start_date",
			"expected_end_date",
			"time_required",
			"wip_warehouse",
			"workstation",
		],
		filters=filters,
		order_by="expected_start_date, expected_end_date",
		limit=50,
	)

	job_cards = [row.name for row in jc_data]
	time_logs = get_time_logs(job_cards) if job_cards else {}

	user_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

	assignments = {}
	if job_cards:
		assignment_data = frappe.get_all(
			"Job Card Time Log",
			filters={"parent": ["in", job_cards], "parentfield": "employee"},
			fields=["parent", "employee"],
		)
		emp_names = {}
		emp_ids = list({a.employee for a in assignment_data if a.employee})
		if emp_ids:
			for emp in frappe.get_all("Employee", filters={"name": ["in", emp_ids]}, fields=["name", "employee_name"]):
				emp_names[emp.name] = emp.employee_name

		for a in assignment_data:
			if a.employee and a.employee not in [e["employee"] for e in assignments.get(a.parent, [])]:
				assignments.setdefault(a.parent, []).append({
					"employee": a.employee,
					"employee_name": emp_names.get(a.employee, a.employee),
				})

	plog_data = {}
	if job_cards:
		for plog in frappe.get_all(
			"Production Log",
			filters={"job_card": ["in", job_cards]},
			fields=["job_card", "workstation", "name"],
		):
			material_count = frappe.db.count(
				"Production Log Material", {"parent": plog.name}
			)
			readings = frappe.get_all(
				"Production Log Field",
				filters={"parent": plog.name},
				fields=["operation_field", "value"],
			)
			custom_data = {r.operation_field: r.value for r in readings}
			plog_data[plog.job_card] = {
				"workstation": plog.workstation,
				"material_count": material_count,
				"production_log": plog.name,
				"custom_data": custom_data,
			}

	op_custom_fields = {}
	unique_ops = list({row.operation for row in jc_data})
	for op_name in unique_ops:
		fields = frappe.get_all(
			"Operation Field",
			filters={"parent": op_name, "parenttype": "Operation"},
			fields=["label", "fieldname", "fieldtype", "options", "reqd",
			"link_doctype", "link_scan_filters", "show_barcode_scanner", "multiple"],
			order_by="idx",
		)
		if fields:
			op_custom_fields[op_name] = fields

	for row in jc_data:
		if row.status == "Open":
			row.status = "Not Started"

		item_code = row.production_item
		row.fg_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
		row.serial_no = frappe.db.get_value("Job Card", row.name, "serial_no") or ""

		row.status_colour = _get_status_color(row.status)
		row.job_card_link = (
			f'<a class="ellipsis" data-doctype="Job Card" data-name="{row.name}" '
			f'href="/app/job-card/{row.name}" title="{row.name}">{row.name}</a>'
		)
		row.operation_link = (
			f'<a class="ellipsis" data-doctype="Operation" data-name="{row.operation}" '
			f'href="/app/operation/{row.operation}" title="{row.operation}">{row.operation}</a>'
		)
		row.work_order_link = get_link_to_form("Work Order", row.work_order)
		row.time_logs = time_logs.get(row.name, [])
		row.assigned_employees = assignments.get(row.name, [])

		row.user_employee = user_employee

		plog = plog_data.get(row.name, {})
		row.plog_workstation = plog.get("workstation", "")
		row.plog_material_count = plog.get("material_count", 0)
		row.plog_name = plog.get("production_log", "")

		row.custom_fields = op_custom_fields.get(row.operation, [])
		row.custom_data = plog.get("custom_data", {})

	return jc_data


@frappe.whitelist()
def find_job_card_by_barcode(workplace, barcode):
	wp = _get_workplace(workplace)
	operations = [row.operation for row in wp.allowed_operations]
	if not operations:
		return []

	if frappe.db.exists("Job Card", barcode):
		jc = frappe.db.get_value(
			"Job Card",
			barcode,
			["name", "operation", "status", "production_item", "for_quantity"],
			as_dict=True,
		)
		if jc and jc.operation in operations and jc.status not in ("Completed", "Stopped"):
			return [jc]

	jc_by_serial = _find_job_cards_by_serial_no(barcode, operations)
	if jc_by_serial:
		return jc_by_serial

	item_code = _resolve_barcode_to_item(barcode)
	if item_code:
		return frappe.get_all(
			"Job Card",
			fields=["name", "operation", "status", "production_item", "for_quantity", "workstation"],
			filters={
				"production_item": item_code,
				"operation": ["in", operations],
				"docstatus": ("<", 2),
				"status": ["not in", ["Completed", "Stopped"]],
			},
			order_by="expected_start_date",
			limit=10,
		)

	return []


@frappe.whitelist()
def get_current_employee(workplace):
	wp = _get_workplace(workplace)
	user = frappe.session.user
	for row in wp.allowed_employees:
		if row.user == user:
			return row.employee

	return frappe.db.get_value("Employee", {"user_id": user}, "name")


@frappe.whitelist()
def assign_employee(job_card, employee):
	doc = frappe.get_doc("Job Card", job_card)
	for row in doc.employee:
		if row.employee == employee:
			return
	doc.append("employee", {"employee": employee})
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def unassign_employee(job_card, employee):
	doc = frappe.get_doc("Job Card", job_card)
	doc.employee = [row for row in doc.employee if row.employee != employee]
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def start_job(job_card, employee, start_time=None):
	doc = frappe.get_doc("Job Card", job_card)
	if not start_time:
		start_time = now_datetime()

	if not any(row.employee == employee for row in doc.employee):
		doc.append("employee", {"employee": employee})

	doc.append("time_logs", {
		"from_time": start_time,
		"employee": employee,
	})
	doc.db_set("status", "Work In Progress")
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def pause_job(job_card, end_time=None):
	doc = frappe.get_doc("Job Card", job_card)
	if not end_time:
		end_time = now_datetime()

	for row in doc.time_logs:
		if row.from_time and not row.to_time:
			row.to_time = end_time
			row.time_in_mins = time_diff_in_seconds(row.to_time, row.from_time) / 60
			row.db_update()

	doc.db_set("status", "On Hold")
	doc.db_set("is_paused", 1)


@frappe.whitelist()
def resume_job(job_card, employee=None, start_time=None):
	doc = frappe.get_doc("Job Card", job_card)
	if not start_time:
		start_time = now_datetime()

	if not employee:
		for row in doc.time_logs:
			if row.employee:
				employee = row.employee
				break

	doc.append("time_logs", {
		"from_time": start_time,
		"employee": employee,
	})
	doc.db_set("status", "Work In Progress")
	doc.db_set("is_paused", 0)
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def scan_raw_material(workplace, job_card, barcode, item_filter=""):
	plog = _get_or_create_production_log(workplace, job_card)
	employee = get_current_employee(workplace)

	scan_type, item_code, batch_no, serial_no = _resolve_material_barcode(barcode)

	if item_code and item_filter:
		try:
			filter_obj = item_filter if isinstance(item_filter, dict) else json.loads(item_filter) if item_filter else {}
		except (json.JSONDecodeError, TypeError):
			filter_obj = {}
		if filter_obj:
			filters = _parse_link_filters(filter_obj)
			if filters:
				item_doc = frappe.get_cached_doc("Item", item_code)
				for key, val in filters.items():
					actual = getattr(item_doc, key, None)
					if isinstance(val, list) and len(val) == 2:
						op, operand = val
						if op == "in" and actual not in operand:
							frappe.throw(f"Item {item_code}: {key} '{actual}' not in {operand}")
						elif op == "not in" and actual in operand:
							frappe.throw(f"Item {item_code}: {key} '{actual}' is excluded")
						elif op == "=" and actual != operand:
							frappe.throw(f"Item {item_code}: {key} is '{actual}', expected '{operand}'")
						elif op == "!=" and actual == operand:
							frappe.throw(f"Item {item_code}: {key} should not be '{operand}'")
						elif op == "like" and str(operand).replace("%", "") not in str(actual or ""):
							frappe.throw(f"Item {item_code}: {key} '{actual}' doesn't match '{operand}'")
					elif actual != val:
						frappe.throw(f"Item {item_code}: {key} is '{actual}', expected '{val}'")

	plog.append("materials", {
		"scan_barcode": barcode,
		"scan_type": scan_type,
		"raw_material_item": item_code,
		"batch_no": batch_no,
		"serial_no": serial_no,
		"supplier_label": barcode if scan_type == "Unknown Label" else "",
		"scanned_by": employee,
		"scan_datetime": now_datetime(),
	})
	plog.save(ignore_permissions=True)

	item_name = ""
	if item_code:
		item_name = frappe.get_cached_value("Item", item_code, "item_name") or ""

	label = item_name or item_code or barcode
	detail = f" (Batch: {batch_no})" if batch_no else f" (SN: {serial_no})" if serial_no else ""
	plog.add_comment("Info", f"Scanned: {label}{detail}")

	return {
		"scan_type": scan_type,
		"item_code": item_code,
		"item_name": item_name,
		"batch_no": batch_no,
		"serial_no": serial_no,
		"supplier_label": barcode if scan_type == "Unknown Label" else "",
		"material_count": len(plog.materials),
	}


@frappe.whitelist()
def set_workstation(workplace, job_card, workstation):
	plog = _get_or_create_production_log(workplace, job_card)
	old_ws = plog.workstation
	plog.workstation = workstation
	plog.save(ignore_permissions=True)
	if old_ws and old_ws != workstation:
		plog.add_comment("Info", f"Workstation: {old_ws} → {workstation}")
	else:
		plog.add_comment("Info", f"Workstation: {workstation}")
	return {"workstation": workstation}


@frappe.whitelist()
def save_custom_data(workplace, job_card, custom_data):
	plog = _get_or_create_production_log(workplace, job_card)
	if isinstance(custom_data, str):
		custom_data = json.loads(custom_data)

	operation = frappe.db.get_value("Job Card", job_card, "operation")
	op_fields = {}
	if operation:
		for f in frappe.get_all(
			"Operation Field",
			filters={"parent": operation, "parenttype": "Operation"},
			fields=["fieldname", "label", "fieldtype"],
		):
			op_fields[f.fieldname] = f

	existing = {r.operation_field: r for r in plog.readings}

	changes = []
	for fieldname, value in custom_data.items():
		str_value = str(value) if value is not None else ""
		field_def = op_fields.get(fieldname, {})

		if fieldname in existing:
			old_val = existing[fieldname].value or ""
			if str_value != old_val:
				if old_val:
					changes.append(f"{fieldname}: {old_val} → {str_value}")
				else:
					changes.append(f"{fieldname}: {str_value}")
			existing[fieldname].value = str_value
		else:
			if str_value:
				changes.append(f"{fieldname}: {str_value}")
			plog.append("readings", {
				"operation_field": fieldname,
				"label": field_def.get("label", fieldname),
				"fieldtype": field_def.get("fieldtype", "Data"),
				"value": str_value,
			})

	plog.custom_data = json.dumps(custom_data, ensure_ascii=False)
	plog.save(ignore_permissions=True)

	if changes:
		plog.add_comment("Info", ", ".join(changes))

	return {"ok": True}


@frappe.whitelist()
def resolve_workstation_barcode(barcode):
	if frappe.db.exists("Workstation", barcode):
		return {"workstation": barcode}

	ws = frappe.db.get_value("Workstation", {"workstation_name": barcode}, "name")
	if ws:
		return {"workstation": ws}

	ws = frappe.db.get_value("Workstation", {"custom_barcode": barcode}, "name")
	if ws:
		return {"workstation": ws}

	return {"workstation": None, "error": f"No workstation found for barcode: {barcode}"}


@frappe.whitelist()
def get_production_log(job_card):
	existing = frappe.db.get_value("Production Log", {"job_card": job_card}, "name")
	if not existing:
		return {"workstation": "", "materials": []}

	plog = frappe.get_doc("Production Log", existing)
	materials = []
	for m in plog.materials:
		materials.append({
			"scan_barcode": m.scan_barcode,
			"scan_type": m.scan_type,
			"raw_material_item": m.raw_material_item,
			"raw_material_item_name": m.raw_material_item_name,
			"batch_no": m.batch_no,
			"serial_no": m.serial_no,
			"supplier_label": m.supplier_label,
			"name": m.name,
		})
	return {
		"workstation": plog.workstation or "",
		"materials": materials,
		"production_log": plog.name,
	}


@frappe.whitelist()
def remove_scanned_material(job_card, row_name):
	existing = frappe.db.get_value("Production Log", {"job_card": job_card}, "name")
	if not existing:
		return

	plog = frappe.get_doc("Production Log", existing)
	plog.materials = [m for m in plog.materials if m.name != row_name]
	plog.save(ignore_permissions=True)
	return {"material_count": len(plog.materials)}


@frappe.whitelist()
def complete_job(workplace, job_card, qty, end_time=None):
	doc = frappe.get_doc("Job Card", job_card)
	qty = flt(qty)
	if not end_time:
		end_time = now_datetime()

	plog_name = frappe.db.get_value("Production Log", {"job_card": job_card}, "name")
	plog = frappe.get_doc("Production Log", plog_name) if plog_name else None

	op_fields = frappe.get_all(
		"Operation Field",
		filters={"parent": doc.operation, "parenttype": "Operation", "reqd": 1},
		fields=["label", "fieldname", "fieldtype", "link_doctype", "multiple"],
	)

	custom_data = {}
	if plog:
		for r in plog.readings:
			custom_data[r.operation_field] = r.value

	for f in op_fields:
		if f.fieldtype == "Link" and f.link_doctype == "Workstation" and not f.get("multiple"):
			if not plog or not plog.workstation:
				frappe.throw(f"'{f.label}' is required before completing this job")
		else:
			if not custom_data.get(f.fieldname):
				frappe.throw(f"'{f.label}' is required before completing this job")

	has_open = False
	for row in doc.time_logs:
		if row.from_time and not row.to_time:
			row.to_time = end_time
			row.time_in_mins = time_diff_in_seconds(row.to_time, row.from_time) / 60
			row.completed_qty = qty
			has_open = True
			break

	if not has_open and doc.time_logs:
		doc.time_logs[-1].completed_qty = qty

	doc.save(ignore_permissions=True)
	doc.submit()

	if doc.serial_no and plog_name:
		frappe.db.set_value("Production Log", plog_name, "finished_serial_no", doc.serial_no)


@frappe.whitelist()
def get_production_data_for_job_card(job_card):
	plog_name = frappe.db.get_value("Production Log", {"job_card": job_card}, "name")
	if not plog_name:
		return None

	plog = frappe.get_doc("Production Log", plog_name)

	readings = []
	for r in plog.readings:
		readings.append({
			"label": r.label or r.operation_field,
			"value": r.value,
			"fieldtype": r.fieldtype,
		})

	return {
		"production_log": plog.name,
		"workstation": plog.workstation or "",
		"workplace": plog.workplace or "",
		"finished_serial_no": plog.finished_serial_no or "",
		"readings": readings,
	}
