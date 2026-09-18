# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Seed what the register cannot start empty with, and fill in what the prototype lacked.

Seeds only, never a re-sync: anything that already exists is left alone, so a section
renamed or a review period tuned in the desk survives the next migrate. The one exception
is the document-type dictionary, where existing rows get their new columns filled once —
the prototype's `Technical Document Type` had a single field, so every row is missing an
abbreviation and its extension flags, and there is nothing to preserve.

Sections are seeded as roots. Frappe's tree view is happy with several, and one artificial
"All Sections" root would put every `User Permission` a level away from the thing an
administrator actually wants to grant.
"""

import frappe

SECTIONS = (
	{"section_name": "Технічні умови", "is_group": 1, "naming_prefix": "ТУ-.YYYY.-"},
	{"section_name": "Договори", "is_group": 1, "naming_prefix": "ДОГ-.YYYY.-"},
	{"section_name": "Регламенти", "is_group": 1, "naming_prefix": "РЕГ-.YYYY.-"},
	{"section_name": "Інструкції", "is_group": 1, "naming_prefix": "ІНС-.YYYY.-"},
	{"section_name": "Інше", "is_group": 1, "naming_prefix": "ДОК-.YYYY.-"},
)

DOCUMENT_TYPES = (
	{
		"document_type": "Технічні умови",
		"abbreviation": "ТУ",
		"default_section": "Технічні умови",
		"has_product_classification": 1,
		"has_modifications": 1,
		"requires_completeness": 1,
	},
	{"document_type": "Інструкція", "abbreviation": "ІН", "default_section": "Інструкції"},
	{"document_type": "Методика випробувань", "abbreviation": "МВ"},
	{"document_type": "Програма випробувань", "abbreviation": "ПВ"},
	{"document_type": "Протокол випробувань", "abbreviation": "ПРВ"},
	{"document_type": "Акт випробувань", "abbreviation": "АКТ"},
	{"document_type": "Наказ", "abbreviation": "НАК"},
	{"document_type": "Інструкція з пакування", "abbreviation": "ІПАК", "default_section": "Інструкції"},
	{"document_type": "Інструкція з маркування", "abbreviation": "ІМАР", "default_section": "Інструкції"},
	{
		"document_type": "Інструкція з вибіркового контролю",
		"abbreviation": "ІВК",
		"default_section": "Інструкції",
	},
	{
		"document_type": "Інструкція з експлуатації",
		"abbreviation": "ІЕ",
		"default_section": "Інструкції",
	},
	{"document_type": "Паспорт", "abbreviation": "ПС"},
	{"document_type": "Сертифікат", "abbreviation": "СЕРТ"},
	{"document_type": "Документ кодифікації", "abbreviation": "ДК"},
	{"document_type": "Договір", "abbreviation": "ДОГ", "default_section": "Договори"},
	{"document_type": "Регламент", "abbreviation": "РЕГ", "default_section": "Регламенти"},
	{"document_type": "Інше", "abbreviation": "ІНШ", "default_section": "Інше"},
)

PRODUCT_TYPES = ("БпЛА", "НСУ", "Котушка", "Батарея", "РЕБ")

PRODUCT_SUBTYPES = (
	{"product_subtype": "Оптика", "product_type": "БпЛА", "active": 1},
	{"product_subtype": "Радіо", "product_type": "БпЛА", "active": 1},
	{"product_subtype": "Перехоплювач", "product_type": "БпЛА", "active": 1},
)


def execute():
	seed_sections()
	seed_document_types()
	seed("Product Type", [{"product_type": name} for name in PRODUCT_TYPES], "product_type")
	seed("Product Subtype", PRODUCT_SUBTYPES, "product_subtype")
	seed_naming_rules()


def seed_sections():
	for row in SECTIONS:
		if frappe.db.exists("Technical Document Section", row["section_name"]):
			continue

		frappe.get_doc({"doctype": "Technical Document Section", **row}).insert(ignore_permissions=True)


def seed_document_types():
	"""Insert missing types, and fill the columns the prototype's single-field version had none of."""
	for row in DOCUMENT_TYPES:
		name = row["document_type"]
		if not frappe.db.exists("Technical Document Type", name):
			frappe.get_doc({"doctype": "Technical Document Type", **row}).insert(ignore_permissions=True)
			continue

		blanks = {
			field: value
			for field, value in row.items()
			if field != "document_type" and not frappe.db.get_value("Technical Document Type", name, field)
		}
		if blanks:
			frappe.db.set_value("Technical Document Type", name, blanks, update_modified=False)


def seed(doctype, rows, name_field):
	for row in rows:
		if frappe.db.exists(doctype, row[name_field]):
			continue

		frappe.get_doc({"doctype": doctype, **row}).insert(ignore_permissions=True)


def seed_naming_rules():
	for section in SECTIONS:
		prefix = section["naming_prefix"]
		if frappe.db.exists(
			"Document Naming Rule", {"document_type": "Technical Document", "prefix": prefix}
		):
			continue

		frappe.get_doc(
			{
				"doctype": "Document Naming Rule",
				"document_type": "Technical Document",
				"prefix": prefix,
				"prefix_digits": 5,
				"priority": 1,
				"conditions": [{"field": "section", "condition": "=", "value": section["section_name"]}],
			}
		).insert(ignore_permissions=True)
