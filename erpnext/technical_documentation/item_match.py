"""Matching Items to the ЄСКД designation they are made to.

An Item carries its shape as variant attributes («8S», «3P», «Денна аналогова»), a
modification carries the same shape as its own attributes, «Призначення» and name. Neither
is written to match the other, so the link is picked by a person — this module only puts the
plausible designations at the top of the list.
"""

import re

import frappe

MODIFICATION_DOCTYPE = "Product Modification"
WORD_RE = re.compile(r"[\w.\-/]+", re.UNICODE)
# Attributes whose values only repeat what every Item says
NOISE = {"серійний", "виріб", "шт", "мм", "км"}
SERIES_ATTRIBUTES = ("Конфігурація S", "Конфігурація P")


def _tokens(*values):
	tokens = set()
	for value in values:
		for word in WORD_RE.findall(str(value or "").lower()):
			word = word.strip(".,;:()«»\"'")
			if len(word) > 1 and word not in NOISE:
				tokens.add(word)
	return tokens


def _item_tokens(item):
	attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item.name, "parenttype": "Item"},
		fields=["attribute", "attribute_value"],
	)
	values = {row.attribute: row.attribute_value for row in attributes}
	tokens = _tokens(item.item_name, *values.values())

	# «8S» + «3P» is one designation in the catalog: «8S3P»
	series, parallel = (values.get(a) for a in SERIES_ATTRIBUTES)
	if series and parallel:
		tokens.add(f"{series}{parallel}".lower())
	return tokens


def _modification_tokens(modification, attribute_values):
	return _tokens(
		modification.modification_code,
		modification.full_name,
		modification.purpose,
		modification.note,
		*attribute_values,
	)


@frappe.whitelist()
def suggest_modifications(item: str, limit: int = 10, product_type: str | None = None):
	"""Designations whose words overlap the Item's, best first."""
	doc = frappe.db.get_value("Item", item, ["name", "item_name"], as_dict=True)
	if not doc:
		return []

	wanted = _item_tokens(doc)
	if not wanted:
		return []

	modifications = frappe.get_all(
		MODIFICATION_DOCTYPE,
		filters={"product_type": product_type} if product_type else None,
		fields=["name", "modification_code", "display_code", "full_name", "purpose", "note"],
	)
	attributes = {}
	for row in frappe.get_all(
		"Product Modification Attribute",
		filters={"parenttype": MODIFICATION_DOCTYPE},
		fields=["parent", "attribute_value"],
	):
		attributes.setdefault(row.parent, []).append(row.attribute_value)

	scored = []
	for modification in modifications:
		hits = wanted & _modification_tokens(modification, attributes.get(modification.name, []))
		if hits:
			scored.append((len(hits), sorted(hits), modification))

	scored.sort(key=lambda row: (-row[0], row[2].modification_code))
	return [
		{
			"name": modification.name,
			"code": modification.display_code or modification.modification_code,
			"full_name": modification.full_name,
			"purpose": modification.purpose,
			"matched": hits,
		}
		for _score, hits, modification in scored[: int(limit)]
	]


def _describe(full_name, purpose):
	"""The name, and the intended use when it says something the name does not."""
	parts = [full_name] if full_name else []
	if purpose and purpose not in (full_name or ""):
		parts.append(purpose)
	return parts


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def modification_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""The Item's Specification picker: the designation and what it is for, fitting ones first."""
	filters = filters or {}
	item, product_type = filters.get("item"), filters.get("product_type")
	suggested = (
		[row["name"] for row in suggest_modifications(item, limit=10, product_type=product_type)]
		if item
		else []
	)

	conditions = ["(modification_code LIKE %(like)s OR full_name LIKE %(like)s OR purpose LIKE %(like)s)"]
	if product_type:
		conditions.append("product_type = %(product_type)s")
	rows = frappe.db.sql(
		f"""
		SELECT name, modification_code, full_name, purpose
		FROM `tabProduct Modification`
		WHERE {" AND ".join(conditions)}
		ORDER BY modification_code
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"like": f"%{txt or ''}%",
			"product_type": product_type,
			"start": start,
			"page_len": page_len,
		},
	)
	ordered = sorted(rows, key=lambda row: (row[0] not in suggested, row[1]))
	return [
		[
			name,
			f"{'★ ' if name in suggested else ''}{code}",
			" · ".join(_describe(full_name, purpose)),
		]
		for name, code, full_name, purpose in ordered
	]
