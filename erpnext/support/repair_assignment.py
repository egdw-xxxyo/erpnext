import frappe
from frappe import _


class RepairAssignmentRule:
	def role_users(self, doc=None):
		role = self.get("custom_repair_assignee_role")
		members = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
		users = (
			frappe.get_all(
				"User",
				filters={"name": ["in", members], "enabled": 1, "user_type": "System User"},
				pluck="name",
				order_by="name",
			)
			if members
			else []
		)
		return [user for user in users if frappe.has_permission("Repair Unit", "write", doc=doc, user=user)]

	def validate(self):
		if self.document_type != "Repair Unit":
			self.custom_repair_assignee_role = None
		if self.document_type == "Repair Unit" and self.get("custom_repair_assignee_role"):
			if self.rule not in {"Round Robin", "Load Balancing"}:
				frappe.throw(_("Role-based repair assignment supports Round Robin or Load Balancing."))
			users = self.role_users()
			if not users:
				frappe.throw(_("Give the repair role to an enabled user before saving this assignment rule."))
			self.set("users", [{"user": user} for user in users])
		super().validate()

	def apply_assign(self, doc):
		if self.document_type == "Repair Unit" and (
			not doc.get("received_on")
			or not doc.get("warehouse")
			or doc.get("status") not in {"Received", "In Repair", "Waiting for Parts", "Waiting for Customer"}
		):
			return False
		return super().apply_assign(doc)

	def get_user(self, doc):
		if self.document_type == "Repair Unit" and self.get("custom_repair_assignee_role"):
			users = self.role_users(frappe.get_doc("Repair Unit", doc.name))
			if not users:
				return None
			self.set("users", [{"user": user} for user in users])
		return super().get_user(doc)

	def safe_eval(self, fieldname, doc):
		# Standard assignment rules can reopen closed tasks on subsequent saves.
		# A cancelled receipt must leave no active workshop assignment behind.
		if (
			self.document_type == "Repair Unit"
			and fieldname == "close_condition"
			and (
				not doc.get("received_on")
				or not doc.get("warehouse")
				or doc.get("status")
				not in {"Received", "In Repair", "Waiting for Parts", "Waiting for Customer"}
			)
		):
			return True
		return super().safe_eval(fieldname, doc)
