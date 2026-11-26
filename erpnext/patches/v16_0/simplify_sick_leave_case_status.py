import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabSick Leave Case`
		set status = case
			when docstatus = 2 then 'Cancelled'
			when docstatus = 1 then 'Closed'
			else 'Open'
		end
		"""
	)
