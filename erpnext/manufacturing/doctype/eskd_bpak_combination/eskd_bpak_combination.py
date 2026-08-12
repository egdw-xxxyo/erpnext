import frappe
from frappe import _
from frappe.model.document import Document


class ESKDBpAKCombination(Document):
	def validate(self):
		self.validate_unique_number()
		self.validate_unique_intersection()

	def validate_unique_number(self):
		twin = frappe.db.exists(
			"ESKD BpAK Combination",
			{
				"product": self.product,
				"modification_number": self.modification_number,
				"name": ("!=", self.name),
			},
		)
		if twin:
			frappe.throw(
				_("Modification {0} already exists for {1}").format(self.modification_number, self.product)
			)

	def validate_unique_intersection(self):
		"""A board and a ground station may be paired once per product — the whole point
		of the modification list is that every intersection is a distinct БпАК."""
		if not self.board_specification or not self.ground_station_specification:
			return
		twin = frappe.db.exists(
			"ESKD BpAK Combination",
			{
				"product": self.product,
				"board_specification": self.board_specification,
				"ground_station_specification": self.ground_station_specification,
				"name": ("!=", self.name),
			},
		)
		if twin:
			frappe.throw(
				_("{0} is already paired with {1} in modification {2}").format(
					self.board_specification, self.ground_station_specification, twin
				),
				title=_("Duplicate Intersection"),
			)
