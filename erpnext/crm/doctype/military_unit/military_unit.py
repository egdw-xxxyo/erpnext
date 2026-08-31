# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document


class MilitaryUnit(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		military_unit_code: DF.Data
		name_of_military_unit: DF.Data | None
		note: DF.SmallText | None
		organization_type: DF.Literal[
			"Військова частина", "Бригада", "Батальйон", "Полк", "Центр", "Підрозділ", "Інше"
		]
		status: DF.Literal["Потенційна", "Активна", "Клієнт", "Неактивна", "Архів"]
	# end: auto-generated types

	def onload(self):
		"""Contacts and Addresses point at the unit through Dynamic Links, like any party."""
		load_address_and_contact(self)
