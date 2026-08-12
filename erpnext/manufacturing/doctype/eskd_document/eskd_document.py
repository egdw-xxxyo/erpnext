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
		self.document_type = guess_document_type(self.document_code)

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


def guess_document_type(document_code: str) -> str | None:
	"""Map a ЄСКД designation onto an ESKD Document Type by its trailing abbreviation.

	`УКРП.463145.005 ІК` -> the type whose abbreviation is `ІК`.
	Longer abbreviations are tried first so that `СК` never swallows `С`.
	"""
	code = (document_code or "").strip()
	if not code:
		return None
	if code.upper().startswith("ТУ"):
		return frappe.db.get_value("ESKD Document Type", {"abbreviation": "ТУ"}, "name")

	abbrs = frappe.get_all(
		"ESKD Document Type",
		filters={"abbreviation": ("!=", "")},
		fields=["name", "abbreviation"],
	)
	for row in sorted(abbrs, key=lambda r: len(r.abbreviation or ""), reverse=True):
		abbr = (row.abbreviation or "").strip()
		if not abbr:
			continue
		tail = code[-len(abbr) :]
		if tail.upper() != abbr.upper():
			continue
		# `.001` must not match a type abbreviated `1`; require a non-digit boundary
		before = code[: -len(abbr)].rstrip()
		if before and before[-1].isdigit() and abbr.isdigit():
			continue
		return row.name
	return None
