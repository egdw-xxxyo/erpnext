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

	def on_submit(self):
		if not self.items:
			frappe.throw(_("Cannot submit an empty Package. Add items first."))
		self.db_set("status", "Packed")

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
