import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

FORBIDDEN = ("ignore_permissions", "frappe.db.sql", "subprocess", "os.system")


class ImportScript(Document):
	def validate(self):
		for token in FORBIDDEN:
			if token in (self.code or ""):
				frappe.throw(frappe._("The script must not use {0}.").format(token))

		try:
			compile(self.code or "", self.title or "import_script", "exec")
		except SyntaxError as e:
			frappe.throw(frappe._("Syntax error in the script: {0}").format(e))

		if self.preview_config:
			try:
				frappe.parse_json(self.preview_config)
			except Exception:
				frappe.throw(frappe._("Preview Layout is not valid JSON."))

		before = self.get_doc_before_save()

		if not before or before.code != self.code:
			self.version = (self.version or 0) + 1
			self.append(
				"versions",
				{
					"version": self.version,
					"saved_on": now_datetime(),
					"saved_by": frappe.session.user,
					"code": self.code,
				},
			)
