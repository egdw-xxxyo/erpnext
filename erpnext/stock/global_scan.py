import frappe

from erpnext.stock.utils import _get_keyboard_layout_variants, scan_barcode


@frappe.whitelist()
def global_scan(barcode: str) -> dict:
	if not barcode:
		return {"type": None}

	barcode = barcode.strip()
	for candidate in _get_keyboard_layout_variants(barcode):
		result = _resolve(candidate)
		if result:
			return result

	return {"type": None, "barcode": barcode}


def _resolve(value: str) -> dict | None:
	return (
		_resolve_workplace(value)
		or _resolve_employee(value)
		or _resolve_serial_no(value)
		or _resolve_package(value)
		or _resolve_fallback(value)
	)


def _resolve_workplace(value: str) -> dict | None:
	if not frappe.db.has_column("Workplace", "barcode"):
		return None
	name = frappe.db.get_value("Workplace", {"barcode": value, "is_active": 1}, "name")
	if not name:
		name = frappe.db.get_value("Workplace", value, "name")
	if not name:
		return None
	doc = frappe.get_cached_doc("Workplace", name)
	return {
		"type": "workplace",
		"barcode": value,
		"doc": {
			"name": doc.name,
			"workplace_name": doc.workplace_name,
			"company": doc.company,
			"description": doc.description,
			"operations": [op.operation for op in (doc.allowed_operations or []) if getattr(op, "operation", None)],
			"employees": [
				emp.employee_name or emp.employee
				for emp in (doc.allowed_employees or [])
				if getattr(emp, "employee", None)
			],
		},
		"route": f"/app/workplace/{doc.name}",
	}


def _resolve_employee(value: str) -> dict | None:
	fields = ["name", "employee_name", "designation", "department", "company", "status", "image"]
	emp = frappe.db.get_value("Employee", value, fields, as_dict=True)
	if not emp:
		emp = frappe.db.get_value("Employee", {"attendance_device_id": value}, fields, as_dict=True)
	if not emp:
		emp = frappe.db.get_value("Employee", {"employee_number": value}, fields, as_dict=True)
	if not emp:
		return None
	return {
		"type": "employee",
		"barcode": value,
		"doc": emp,
		"route": f"/app/employee/{emp['name']}",
	}


def _resolve_serial_no(value: str) -> dict | None:
	sn = frappe.db.get_value(
		"Serial No",
		value,
		[
			"name",
			"item_code",
			"item_name",
			"batch_no",
			"warehouse",
			"status",
			"purchase_document_no",
		],
		as_dict=True,
	)
	if not sn:
		return None

	pr_info = None
	if sn.purchase_document_no:
		pr_info = frappe.db.get_value(
			"Purchase Receipt",
			sn.purchase_document_no,
			["name", "posting_date", "supplier", "supplier_name"],
			as_dict=True,
		)

	if not pr_info:
		pr_row = frappe.db.sql(
			"""
			SELECT pr.name, pr.posting_date, pr.supplier, pr.supplier_name
			FROM `tabPurchase Receipt Item` pri
			INNER JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
			WHERE pr.docstatus = 1
			  AND (pri.serial_no LIKE %(s)s OR pri.serial_no = %(v)s)
			ORDER BY pr.posting_date DESC
			LIMIT 1
			""",
			{"s": f"%{value}%", "v": value},
			as_dict=True,
		)
		if pr_row:
			pr_info = pr_row[0]

	qi_rows = frappe.db.sql(
		"""
		SELECT name, status, inspection_type, report_date, inspected_by
		FROM `tabQuality Inspection`
		WHERE docstatus < 2
		  AND (item_serial_no = %(v)s OR item_serial_no LIKE %(s)s)
		ORDER BY report_date DESC, modified DESC
		LIMIT 5
		""",
		{"v": value, "s": f"%{value}%"},
		as_dict=True,
	)

	pkg_info = None
	pkg_row = frappe.db.sql(
		"""
		SELECT pi.parent AS name, p.status, p.delivery_note, p.sales_order, p.shipment
		FROM `tabPackage Item` pi
		INNER JOIN `tabPackage` p ON p.name = pi.parent
		WHERE p.docstatus IN (0, 1)
		  AND (pi.serial_no = %(v)s OR pi.serial_no LIKE %(s)s)
		ORDER BY p.modified DESC
		LIMIT 1
		""",
		{"v": value, "s": f"%{value}%"},
		as_dict=True,
	)
	if pkg_row:
		pkg_info = pkg_row[0]

	return {
		"type": "serial_no",
		"barcode": value,
		"doc": sn,
		"route": f"/app/serial-no/{sn['name']}",
		"purchase_receipt": pr_info,
		"package": pkg_info,
		"quality_inspections": qi_rows,
	}


def _resolve_package(value: str) -> dict | None:
	name = frappe.db.get_value(
		"Package",
		{"box_barcode": value, "docstatus": ["in", [0, 1]]},
		"name",
	)
	if not name:
		return None
	doc = frappe.get_doc("Package", name)
	items = []
	for row in doc.items:
		items.append({
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": row.qty,
			"serial_no": row.serial_no,
			"batch_no": row.batch_no,
		})
	return {
		"type": "package",
		"barcode": value,
		"doc": {
			"name": doc.name,
			"status": doc.status,
			"box_template": doc.box_template,
			"sales_order": doc.sales_order,
			"delivery_note": doc.delivery_note,
			"shipment": doc.shipment,
			"purchase_receipt": getattr(doc, "purchase_receipt", None),
		},
		"items": items,
		"route": f"/app/package/{doc.name}",
	}


def _resolve_fallback(value: str) -> dict | None:
	data = scan_barcode(value)
	if not data:
		return None

	if data.get("serial_no"):
		return _resolve_serial_no(data["serial_no"])
	if data.get("package_name"):
		return _resolve_package_by_name(data["package_name"])
	if data.get("batch_no"):
		return {
			"type": "batch",
			"barcode": value,
			"doc": data,
			"route": f"/app/batch/{data['batch_no']}",
		}
	if data.get("warehouse"):
		return {
			"type": "warehouse",
			"barcode": value,
			"doc": data,
			"route": f"/app/warehouse/{data['warehouse']}",
		}
	if data.get("item_code"):
		item_name = frappe.db.get_value("Item", data["item_code"], "item_name")
		return {
			"type": "item",
			"barcode": value,
			"doc": {**data, "item_name": item_name},
			"route": f"/app/item/{data['item_code']}",
		}

	return None


def _resolve_package_by_name(name: str) -> dict | None:
	box_barcode = frappe.db.get_value("Package", name, "box_barcode")
	if not box_barcode:
		return None
	return _resolve_package(box_barcode)
