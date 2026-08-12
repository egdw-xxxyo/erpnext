import re

import frappe
from frappe import _
from frappe.model.document import Document

CODE_PREFIX_RE = re.compile(r"^([А-ЯІЇЄҐA-Z]{4})[.\s]")


class ESKDDocument(Document):
	def validate(self):
		self.document_code = (self.document_code or "").strip()
		self.set_organization_code()
		self.set_document_type()
		self.warn_on_duplicate()

	def set_organization_code(self):
		if self.organization_code:
			return
		match = CODE_PREFIX_RE.match(self.document_code)
		if match:
			self.organization_code = match.group(1)

	def set_document_type(self):
		if self.document_type or not self.document_code:
			return
		self.document_type = guess_document_type(self.document_code, self.document_name)

	def warn_on_duplicate(self):
		"""The same designation may legitimately be listed under several products,
		but never twice for the same product."""
		if not self.product:
			return
		twin = frappe.db.exists(
			"ESKD Document",
			{
				"document_code": self.document_code,
				"product": self.product,
				"name": ("!=", self.name),
			},
		)
		if twin:
			frappe.throw(
				_("{0} is already registered for product {1} as {2}").format(
					self.document_code, self.product, twin
				),
				title=_("Duplicate ЄСКД Document"),
			)


FALLBACK_DOCUMENT_TYPE = "Деталь"


def guess_document_type(document_code: str, document_name: str | None = None) -> str | None:
	"""Map a ЄСКД row onto an ESKD Document Type.

	First by the designation's trailing abbreviation (`УКРП.463145.005 ІК` -> `ІК`,
	longer abbreviations tried first so `СК` never swallows `С`), then by the row title
	(`Складальний кресленик "НСУ"` -> Складальний кресленик). Bare part designations
	such as `УКРП.741348.002` carry no marker at all and fall back to Деталь.
	"""
	code = (document_code or "").strip()
	if not code:
		return None
	if code.upper().startswith("ТУ"):
		return frappe.db.get_value("ESKD Document Type", {"abbreviation": "ТУ"}, "name")

	types = frappe.get_all("ESKD Document Type", fields=["name", "abbreviation"])
	for row in sorted(types, key=lambda r: len(r.abbreviation or ""), reverse=True):
		abbr = (row.abbreviation or "").strip()
		if not abbr:
			continue
		if code[-len(abbr) :].upper() == abbr.upper():
			return row.name

	title = (document_name or "").strip().lower()
	if title:
		for row in sorted(types, key=lambda r: len(r.name), reverse=True):
			if title.startswith(row.name.lower()):
				return row.name

	if frappe.db.exists("ESKD Document Type", FALLBACK_DOCUMENT_TYPE):
		return FALLBACK_DOCUMENT_TYPE
	return None
