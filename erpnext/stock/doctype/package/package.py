import frappe
from frappe import _
from frappe.model.document import Document


class Package(Document):
	def after_insert(self):
		self.db_set("box_barcode", self.name)

	def validate(self):
		self.validate_duplicate_serial_nos()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		if not self.items:
			frappe.throw(_("Cannot submit an empty Package. Add items first."))
		self._validate_qc_and_operation()

	def _validate_qc_and_operation(self):
		missing_qi = []
		missing_jc = []
		for row in self.items:
			if not row.serial_no:
				continue
			if self.auto_pass_qc:
				qi_match = frappe.db.sql(
					"""SELECT 1 FROM `tabQI Serial Entry` qse
					   JOIN `tabQuality Inspection` qi ON qi.name = qse.parent
					   WHERE qse.serial_no=%s AND qi.docstatus=0
					     AND qi.reference_type='Purchase Receipt' LIMIT 1""",
					row.serial_no,
				)
				if not qi_match:
					missing_qi.append(row.serial_no)
			if self.operation:
				jc_match = frappe.db.exists(
					"Job Card",
					{"serial_no": row.serial_no, "operation": self.operation, "docstatus": 0},
				)
				if not jc_match:
					missing_jc.append(row.serial_no)

		if missing_qi:
			frappe.throw(
				_("Auto-pass QC is enabled but no draft Quality Inspection exists for serials: {0}").format(
					", ".join(missing_qi)
				)
			)
		if missing_jc:
			frappe.throw(
				_("No open Job Card with operation {0} found for serials: {1}").format(
					self.operation, ", ".join(missing_jc)
				)
			)

	def on_submit(self):
		if self.auto_pass_qc:
			self._apply_qc_pass()
		if self.operation:
			self._finish_operations()
		self.db_set("status", "Packed")

	def _apply_qc_pass(self):
		touched_qis = set()
		source_prs = set()

		for row in self.items:
			if not row.serial_no:
				continue
			match = frappe.db.sql(
				"""
				SELECT qse.name AS entry_name, qi.name AS qi_name, qi.reference_name AS pr_name
				FROM `tabQI Serial Entry` qse
				JOIN `tabQuality Inspection` qi ON qi.name = qse.parent
				WHERE qse.serial_no = %s
				  AND qi.docstatus = 0
				  AND qi.reference_type = 'Purchase Receipt'
				LIMIT 1
				""",
				row.serial_no,
				as_dict=True,
			)
			if not match:
				frappe.msgprint(
					_("No draft Quality Inspection found for serial {0}").format(row.serial_no),
					indicator="orange",
					alert=True,
				)
				continue
			m = match[0]
			frappe.db.set_value("QI Serial Entry", m.entry_name, {"scanned": 1, "status": "Pass"})
			row.db_set("quality_inspection", m.qi_name, update_modified=False)
			row.db_set("purchase_receipt", m.pr_name, update_modified=False)
			touched_qis.add(m.qi_name)
			if m.pr_name:
				source_prs.add(m.pr_name)

		if len(source_prs) == 1:
			pr_name = next(iter(source_prs))
			self.db_set("purchase_receipt", pr_name)
			self._link_to_purchase_receipt(pr_name)

		for qi_name in touched_qis:
			pending = frappe.db.count(
				"QI Serial Entry", {"parent": qi_name, "scanned": 0}
			)
			if pending == 0:
				try:
					qi = frappe.get_doc("Quality Inspection", qi_name)
					qi.submit()
				except Exception as e:
					frappe.log_error(title="Auto-submit QI from Package", message=str(e))

	def _finish_operations(self):
		from frappe.utils import now_datetime, add_to_date
		for row in self.items:
			if not row.serial_no:
				continue
			jc_name = frappe.db.get_value(
				"Job Card",
				{"serial_no": row.serial_no, "operation": self.operation, "docstatus": 0},
				"name",
			)
			if not jc_name:
				continue
			try:
				jc = frappe.get_doc("Job Card", jc_name)
				to_time = now_datetime()
				from_time = add_to_date(to_time, minutes=-1)
				remaining = (jc.for_quantity or 0) - (jc.total_completed_qty or 0)
				if remaining <= 0:
					remaining = jc.for_quantity or 1
				jc.append("time_logs", {
					"from_time": from_time,
					"to_time": to_time,
					"completed_qty": remaining,
					"time_in_mins": 1,
				})
				jc.save(ignore_permissions=True)
				jc.submit()
			except Exception as e:
				frappe.log_error(title="Auto-finish Job Card from Package", message=str(e))

	def _link_to_purchase_receipt(self, pr_name):
		exists = frappe.db.exists(
			"Purchase Receipt Package",
			{"parent": pr_name, "parenttype": "Purchase Receipt", "package": self.name},
		)
		if exists:
			return
		max_idx = frappe.db.sql(
			"""SELECT COALESCE(MAX(idx), 0) FROM `tabPurchase Receipt Package`
			   WHERE parent=%s AND parenttype='Purchase Receipt' AND parentfield='packages'""",
			pr_name,
		)[0][0]
		row = frappe.get_doc({
			"doctype": "Purchase Receipt Package",
			"parent": pr_name,
			"parenttype": "Purchase Receipt",
			"parentfield": "packages",
			"idx": max_idx + 1,
			"package": self.name,
		})
		row.db_insert()

	def on_cancel(self):
		if self.shipment:
			frappe.throw(
				_("Cannot cancel a Package linked to Shipment {0}").format(self.shipment)
			)
		self.db_set("status", "Cancelled")

	def validate_duplicate_serial_nos(self):
		serial_nos = [row.serial_no for row in self.items if row.serial_no]
		if not serial_nos:
			return

		seen = set()
		for sn in serial_nos:
			if sn in seen:
				frappe.throw(_("Duplicate serial number {0} in this package").format(sn))
			seen.add(sn)

		existing = frappe.db.sql(
			"""
			SELECT pbi.serial_no, pb.name
			FROM `tabPackage Item` pbi
			JOIN `tabPackage` pb ON pb.name = pbi.parent
			WHERE pbi.serial_no IN %(serial_nos)s
			AND pb.name != %(current)s
			AND pb.docstatus = 1
			AND pb.status != 'Cancelled'
			""",
			{"serial_nos": serial_nos, "current": self.name or ""},
			as_dict=True,
		)

		if existing:
			msg = ", ".join([f"{e.serial_no} (in {e.name})" for e in existing])
			frappe.throw(_("Serial numbers already packed: {0}").format(msg))


@frappe.whitelist()
def get_package_details(box_barcode):
	pkg_name = frappe.db.get_value(
		"Package",
		{"box_barcode": box_barcode, "docstatus": 1},
		"name",
	)
	if not pkg_name:
		frappe.throw(_("No submitted Package found for barcode {0}").format(box_barcode))

	pkg = frappe.get_doc("Package", pkg_name)
	return {
		"name": pkg.name,
		"box_template": pkg.box_template,
		"length": pkg.length,
		"width": pkg.width,
		"height": pkg.height,
		"gross_weight": pkg.gross_weight or pkg.tare_weight,
		"status": pkg.status,
		"shipment": pkg.shipment,
		"items": [
			{"item_code": r.item_code, "serial_no": r.serial_no, "qty": r.qty}
			for r in pkg.items
		],
	}


@frappe.whitelist()
def add_package_to_purchase_receipt(package_name, purchase_receipt):
	if not frappe.db.exists("Package", package_name):
		resolved = frappe.db.get_value("Package", {"box_barcode": package_name}, "name")
		if not resolved:
			frappe.throw(_("No Package found for {0}").format(package_name))
		package_name = resolved

	pkg = frappe.get_doc("Package", package_name)
	if pkg.docstatus != 1:
		frappe.throw(_("Package {0} must be submitted first").format(package_name))

	if not frappe.db.exists("Purchase Receipt", purchase_receipt):
		frappe.throw(_("Purchase Receipt {0} not found").format(purchase_receipt))

	if frappe.db.exists(
		"Purchase Receipt Package",
		{"parent": purchase_receipt, "parenttype": "Purchase Receipt", "package": package_name},
	):
		return {"message": _("Package {0} already linked to {1}").format(package_name, purchase_receipt)}

	max_idx = frappe.db.sql(
		"""SELECT COALESCE(MAX(idx), 0) FROM `tabPurchase Receipt Package`
		   WHERE parent=%s AND parenttype='Purchase Receipt' AND parentfield='packages'""",
		purchase_receipt,
	)[0][0]
	row = frappe.get_doc({
		"doctype": "Purchase Receipt Package",
		"parent": purchase_receipt,
		"parenttype": "Purchase Receipt",
		"parentfield": "packages",
		"idx": max_idx + 1,
		"package": package_name,
	})
	row.db_insert()
	if not pkg.purchase_receipt:
		pkg.db_set("purchase_receipt", purchase_receipt)
	return {"message": _("Package {0} added to {1}").format(package_name, purchase_receipt)}


@frappe.whitelist()
def add_package_to_shipment(package_name, shipment_name):
	if not frappe.db.exists("Package", package_name):
		resolved = frappe.db.get_value("Package", {"box_barcode": package_name}, "name")
		if not resolved:
			frappe.throw(_("No Package found for {0}").format(package_name))
		package_name = resolved

	pkg = frappe.get_doc("Package", package_name)
	if pkg.docstatus != 1:
		frappe.throw(_("Package {0} must be submitted first").format(package_name))
	if pkg.shipment:
		frappe.throw(
			_("Package {0} is already linked to Shipment {1}").format(
				package_name, pkg.shipment
			)
		)

	shipment = frappe.get_doc("Shipment", shipment_name)
	if shipment.docstatus != 0:
		frappe.throw(_("Shipment {0} must be in Draft to add packages").format(shipment_name))

	shipment.append(
		"shipment_parcel",
		{
			"length": pkg.length,
			"width": pkg.width,
			"height": pkg.height,
			"weight": pkg.gross_weight or pkg.tare_weight or 0,
			"count": 1,
		},
	)
	shipment.save()

	pkg.db_set("shipment", shipment_name)
	pkg.db_set("status", "Shipped")

	return {"message": _("Package {0} added to Shipment {1}").format(package_name, shipment_name)}
