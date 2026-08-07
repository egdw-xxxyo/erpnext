import frappe
from frappe import _
from frappe.model.document import Document


class VehicleTrip(Document):
	def validate(self):
		self.set_vehicle_info()
		self.validate_vehicle_availability()
		self.validate_odometer()
		self.calculate_distance()
		self.set_status()

	def on_submit(self):
		if not self.odometer_end:
			frappe.throw(_("Odometer End is required before submitting"))
		self.update_vehicle_odometer()

	def on_cancel(self):
		self.revert_vehicle_odometer()

	def validate_vehicle_availability(self):
		if not self.vehicle:
			return
		existing = frappe.db.exists(
			"Vehicle Trip",
			{
				"vehicle": self.vehicle,
				"status": "En Route",
				"docstatus": 0,
				"name": ("!=", self.name),
			},
		)
		if existing:
			frappe.throw(_("Vehicle {0} is already en route in trip {1}").format(self.vehicle, existing))

	def set_vehicle_info(self):
		if self.vehicle:
			vehicle = frappe.get_cached_doc("Vehicle", self.vehicle)
			self.last_odometer = vehicle.last_odometer
			self.vehicle_make_model = f"{vehicle.make} {vehicle.model}"
			self.fuel_type = vehicle.fuel_type
			self.fuel_uom = vehicle.uom

	def validate_odometer(self):
		if self.odometer_end and self.odometer_end < self.odometer_start:
			frappe.throw(_("Odometer End cannot be less than Odometer Start"))

		if self.odometer_start < self.last_odometer:
			frappe.throw(
				_("Odometer Start ({0}) cannot be less than last recorded reading ({1})").format(
					self.odometer_start, self.last_odometer
				)
			)

	def calculate_distance(self):
		if self.odometer_end and self.odometer_start:
			self.distance = self.odometer_end - self.odometer_start
		else:
			self.distance = 0

	def set_status(self):
		if self.docstatus == 0:
			self.status = "Completed" if self.odometer_end else "En Route"
		elif self.docstatus == 2:
			self.status = "Cancelled"

	def update_vehicle_odometer(self):
		frappe.db.set_value("Vehicle", self.vehicle, "last_odometer", self.odometer_end)

	def revert_vehicle_odometer(self):
		prev = frappe.db.sql(
			"""
			SELECT odometer_end FROM `tabVehicle Trip`
			WHERE vehicle = %s AND docstatus = 1 AND name != %s
			ORDER BY date DESC, creation DESC LIMIT 1
			""",
			(self.vehicle, self.name),
		)
		if prev:
			frappe.db.set_value("Vehicle", self.vehicle, "last_odometer", prev[0][0])
		else:
			frappe.msgprint(
				_("No previous trips found for this vehicle. Please update the odometer manually.")
			)
