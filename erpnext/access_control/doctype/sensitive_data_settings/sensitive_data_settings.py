import json

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.document import Document

from erpnext.access_control import sensitive
from erpnext.access_control import sensitive_rules as rules


class SensitiveDataSettings(Document):
	def validate(self):
		self.validate_objects()
		self.validate_fields()

	def validate_objects(self):
		seen = set()
		for row in self.objects:
			key = (row.object_type, row.object_name)
			if key in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, _(row.object_name)))
			seen.add(key)
			if row.object_type != "DocType":
				continue
			if row.object_name in rules.RESERVED_DOCTYPES:
				frappe.throw(
					_("Row {0}: system document type {1} cannot be protected").format(
						row.idx, _(row.object_name)
					)
				)
			if frappe.db.get_value("DocType", row.object_name, "istable"):
				frappe.throw(
					_("Row {0}: {1} is a child table, protect its document instead").format(
						row.idx, _(row.object_name)
					)
				)

	def validate_fields(self):
		for row in self.fields:
			field = frappe.get_meta(row.document_type).get_field(row.fieldname)
			if not field:
				frappe.throw(
					_("Row {0}: {1} has no field {2}").format(row.idx, _(row.document_type), row.fieldname)
				)
			row.label = field.label

	def on_update(self):
		sensitive.clear_config()
		self.track_views()
		sensitive.log("Settings Changed", frappe.session.user, details=json.dumps(self.changes()))
		sensitive.notify_managers(
			_("{0} changed the protected data settings").format(
				frappe.utils.get_fullname(frappe.session.user)
			),
			frappe.session.user,
		)

	def changes(self) -> dict:
		before = self.get_doc_before_save()
		after = self.as_dict()
		titles = dict(
			frappe.get_all(
				"Page",
				filters={
					"name": ["in", [row.object_name for row in self.objects if row.object_type == "Page"]]
				},
				fields=["name", "title"],
				as_list=True,
			)
		)
		for row in after.get("objects") or ():
			row["label"] = titles.get(row.object_name)
		return rules.settings_delta(before.as_dict() if before else None, after)

	def track_views(self):
		for row in self.objects:
			if row.object_type == "DocType" and not frappe.get_meta(row.object_name).track_views:
				make_property_setter(row.object_name, None, "track_views", 1, "Check", for_doctype=True)


@frappe.whitelist()
def protection_candidates(object_type: str) -> list[dict]:
	frappe.has_permission("Sensitive Data Settings", "write", throw=True)
	loaders = {"DocType": _doctype_candidates, "Report": _report_candidates, "Page": _page_candidates}
	if object_type not in loaders:
		frappe.throw(_("Unknown object type {0}").format(object_type))
	return loaders[object_type]()


def _doctype_candidates() -> list[dict]:
	rows = frappe.get_all("DocType", filters={"istable": 0}, fields=["name", "module"], order_by="name")
	return [
		{"name": row.name, "title": row.name, "module": row.module}
		for row in rows
		if row.name not in rules.RESERVED_DOCTYPES
	]


def _report_candidates() -> list[dict]:
	rows = frappe.get_all("Report", filters={"disabled": 0}, fields=["name", "module"], order_by="name")
	return [{"name": row.name, "title": row.name, "module": row.module} for row in rows]


def _page_candidates() -> list[dict]:
	service_modules = set(frappe.get_all("Module Def", filters={"app_name": "frappe"}, pluck="name"))
	rows = frappe.get_all("Page", fields=["name", "title", "module"], order_by="name")
	return [
		{"name": row.name, "title": row.title or row.name, "module": row.module}
		for row in rows
		if row.module not in service_modules
	]
