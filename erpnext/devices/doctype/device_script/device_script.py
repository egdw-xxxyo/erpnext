import json

import frappe
from frappe.model.document import Document


def _capture_working_copy(doc):
	return {"script": doc.script or ""}


def _load_snapshot(row):
	try:
		return json.loads(row.snapshot or "{}")
	except Exception:
		return {}


def _resolve_default_snapshot(doc):
	row = next((v for v in (doc.versions or []) if v.is_default), None)
	if not row:
		return _capture_working_copy(doc)
	return _load_snapshot(row)


class DeviceScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		default_version: DF.Data | None
		is_active: DF.Check
		script: DF.Code | None
		script_name: DF.Data | None
		script_type: DF.Literal["Scanner"]
		viewing_version: DF.Data | None

	def validate(self):
		if not self.script_type:
			self.script_type = "Scanner"

		if not self.versions:
			self.append(
				"versions",
				{
					"version": "v1",
					"is_default": 1,
					"snapshot": json.dumps(_capture_working_copy(self)),
					"created_on": frappe.utils.now_datetime(),
				},
			)
			self.default_version = "v1"
			self.viewing_version = "v1"

		defaults = [v for v in self.versions if v.is_default]
		if len(defaults) == 0:
			self.versions[0].is_default = 1
			defaults = [self.versions[0]]
		elif len(defaults) > 1:
			frappe.throw("Exactly one version must be marked as default")

		self.default_version = defaults[0].version

		if not self.viewing_version:
			self.viewing_version = self.default_version
		target = next((v for v in self.versions if v.version == self.viewing_version), None)
		if target is None:
			frappe.throw(f"Viewing version {self.viewing_version} not found")
		target.snapshot = json.dumps(_capture_working_copy(self))


def get_active_scripts(script_type: str = "Scanner"):
	"""Return active Device Scripts of the given type with the script body from each default version snapshot.

	Only `Scanner` remains. These are libraries, not handlers: `_build_scripts_namespace`
	execs each one into the `scripts.*` namespace that Workplace Scripts call, which is why
	they have no entry point and no trigger event.
	"""
	filters = {"is_active": 1, "script_type": script_type}
	names = frappe.get_all(
		"Device Script",
		filters=filters,
		pluck="name",
	)
	out = []
	for name in names:
		doc = frappe.get_cached_doc("Device Script", name)
		snap = _resolve_default_snapshot(doc)
		out.append(
			frappe._dict(
				{
					"script_name": doc.script_name,
					"script_type": doc.script_type,
					"script": snap.get("script", "") or "",
				}
			)
		)
	return out


def get_active_scanner_scripts():
	"""Backwards-compatible alias used by scanner_api during the transition."""
	return get_active_scripts("Scanner")
