"""Типові скрипти імпорту: код живе у файлах репозиторію й оновлюється на кожній міграції."""

import json
from pathlib import Path

import frappe

SCRIPTS_DIR = Path(__file__).parent / "scripts"

SEEDS = [
	{
		"title": "Pension Fund: Individual Insured Person Data",
		"file": "pension_fund_insurance.py",
		"file_types": "pdf",
		"priority": 10,
		"description": "Insurance record by month from the Pension Fund statement (insurwrkex): stored in the employee card, the employee is found by the tax number.",
		"markers": [
			("Text", "Contains", "ІНДИВІДУАЛЬНІ ВІДОМОСТІ ПРО ЗАСТРАХОВАНУ ОСОБУ"),
			("Text", "Contains", "Дані про трудовий та страховий стаж"),
		],
		"permissions": [("Employee", "read"), ("Employee", "write")],
		"change_fields": [
			("Employee", "custom_insurance_months_table", "Insurance Tenure by Month", "Create")
		],
		"preview": {
			"sections": [
				{
					"kind": "key_value",
					"title": "Insured Person",
					"source": "header",
					"columns": [
						{"key": "full_name", "label": "Full Name"},
						{"key": "card_number", "label": "Insurance Card Number"},
						{"key": "tax_id", "label": "Tax Number"},
						{"key": "period_from", "label": "Period From"},
						{"key": "period_to", "label": "Period To"},
					],
				},
				{"kind": "grid", "title": "Insured Days by Month", "source": "months"},
			]
		},
	},
	{
		"title": "Pension Fund: Form OK-5",
		"file": "pension_fund_ok5.py",
		"file_types": "pdf",
		"priority": 10,
		"description": "Form OK-5 statement: insurance record by month with the insurer of each month (new insurers are added), and the earnings of the current and the previous year into Earnings Before ERP. The employee is found by the tax number.",
		"markers": [
			("Text", "Contains", "ІНДИВІДУАЛЬНІ ВІДОМОСТІ ПРО ЗАСТРАХОВАНУ ОСОБУ"),
			("Text", "Contains", "Форма ОК-5"),
		],
		"permissions": [("Employee", "read"), ("Employee", "write"), ("Insurer", "create")],
		"change_fields": [
			("Employee", "custom_insurance_months_table", "Insurance Tenure by Month", "Create"),
			("Employee", "custom_opening_earnings", "Earnings Before ERP", "Update"),
			("Insurer", "code", "Insurer", "Create"),
		],
		"preview": {
			"sections": [
				{
					"kind": "key_value",
					"title": "Insured Person",
					"source": "header",
					"columns": [
						{"key": "full_name", "label": "Full Name"},
						{"key": "card_number", "label": "Insurance Card Number"},
						{"key": "tax_id", "label": "Tax Number"},
					],
				},
				{
					"kind": "table",
					"title": "Insurers",
					"source": "insurers",
					"max_rows": 30,
					"columns": [
						{"key": "code", "label": "Insurer Code"},
						{"key": "name", "label": "Insurer Name"},
					],
				},
				{
					"kind": "table",
					"title": "Insured Days and Earnings by Month",
					"source": "months",
					"max_rows": 60,
					"columns": [
						{"key": "year", "label": "Year"},
						{"key": "month", "label": "Month"},
						{"key": "days", "label": "Insured Days"},
						{"key": "earnings", "label": "Official Earnings"},
						{"key": "insurer_name", "label": "Insurer"},
					],
				},
			]
		},
	},
	{
		"title": "Earnings Before ERP: Spreadsheet",
		"file": "employee_opening_earnings_sheet.py",
		"file_types": "xlsx",
		"priority": 5,
		"description": "Official earnings of past months (columns: РНОКПП, Місяць, Заробіток) into Earnings Before ERP of the employee.",
		"markers": [("Sheet Cell", "Contains", "РНОКПП"), ("Sheet Cell", "Contains", "Заробіток")],
		"permissions": [("Employee", "read"), ("Employee", "write")],
		"change_fields": [("Employee", "custom_opening_earnings", "Earnings Before ERP", "Update")],
		"preview": {
			"sections": [
				{
					"kind": "table",
					"title": "Rows",
					"source": "rows",
					"max_rows": 30,
					"columns": [
						{"key": "tax_id", "label": "Tax Number"},
						{"key": "month", "label": "Month"},
						{"key": "earnings", "label": "Official Earnings"},
					],
				}
			]
		},
	},
]


def seed_import_scripts():
	for seed in SEEDS:
		code = (SCRIPTS_DIR / seed["file"]).read_text(encoding="utf-8")
		doc = (
			frappe.get_doc("Import Script", seed["title"])
			if frappe.db.exists("Import Script", seed["title"])
			else frappe.new_doc("Import Script")
		)
		doc.title = seed["title"]
		doc.file_types = seed["file_types"]
		doc.priority = seed["priority"]
		doc.description = seed["description"]
		doc.preview_config = json.dumps(seed["preview"], ensure_ascii=False, indent=1)
		doc.code = code

		if doc.is_new():
			doc.enabled = 1
			doc.set("markers", [])
			doc.set("required_permissions", [])
			doc.set("change_fields", [])

			for where, kind, value in seed["markers"]:
				doc.append("markers", {"where": where, "kind": kind, "value": value})

			for reference_doctype, ptype in seed["permissions"]:
				doc.append("required_permissions", {"reference_doctype": reference_doctype, "ptype": ptype})

			for reference_doctype, fieldname, label, mode in seed["change_fields"]:
				doc.append(
					"change_fields",
					{
						"reference_doctype": reference_doctype,
						"fieldname": fieldname,
						"label": label,
						"mode": mode,
					},
				)

		doc.save(ignore_permissions=True)
