import csv

import frappe
from frappe.utils import flt, getdate

TABLE = "custom_opening_earnings"
HEADERS = {
	"tax_id": ("рнокпп", "ipn", "tax_id"),
	"month": ("місяць", "month"),
	"earnings": ("заробіток", "earnings"),
}


def _rows(path):
	if path.lower().endswith(".csv"):
		with open(path, encoding="utf-8-sig", newline="") as handle:
			return [list(r) for r in csv.reader(handle)]

	from openpyxl import load_workbook

	book = load_workbook(path, read_only=True, data_only=True)
	return [["" if c is None else c for c in r] for r in book.worksheets[0].iter_rows(values_only=True)]


def _index(header):
	cells = [str(c).strip().lower() for c in header]
	return {key: next(i for i, c in enumerate(cells) if c in names) for key, names in HEADERS.items()}


def _month(value):
	if hasattr(value, "year"):
		return getdate(value).replace(day=1)

	text = str(value).strip()

	if "." in text:
		month, year = text.split(".")[-2:]
		return getdate(f"{year}-{int(month):02d}-01")

	return getdate(text).replace(day=1)


def parse(ctx):
	rows = _rows(ctx.file_path)
	ctx.progress(30, frappe._("Reading rows"))
	columns = _index(rows[0])
	out = []

	for row in rows[1:]:
		if not str(row[columns["tax_id"]]).strip():
			continue

		out.append(
			{
				"tax_id": str(row[columns["tax_id"]]).strip(),
				"month": str(_month(row[columns["month"]])),
				"earnings": flt(row[columns["earnings"]]),
			}
		)

	return {"header": {"rows": len(out)}, "rows": out, "warnings": []}


def plan(ctx, parsed):
	by_employee = {}

	for row in parsed["rows"]:
		by_employee.setdefault(row["tax_id"], []).append(row)

	result = []

	for tax_id, rows in by_employee.items():
		name = frappe.db.get_value("Employee", {"custom_tax_id": tax_id}, "name")

		if not name:
			result.append(
				{
					"doctype": "Employee",
					"name": None,
					"label": tax_id,
					"changes": [],
					"problem": frappe._("No employee with the tax number {0}").format(tax_id),
				}
			)
			continue

		frappe.has_permission("Employee", "write", doc=name, throw=True)
		employee = frappe.get_doc("Employee", name)
		existing = {getdate(r.month): r for r in employee.get(TABLE) or []}
		changes = []

		for row in rows:
			current = existing.get(getdate(row["month"]))

			if current and flt(current.earnings) == flt(row["earnings"]):
				continue

			changes.append(
				{
					"field": row["month"],
					"label": row["month"][:7],
					"old": current.earnings if current else None,
					"new": row["earnings"],
				}
			)

		result.append(
			{
				"doctype": "Employee",
				"name": name,
				"label": employee.employee_name,
				"changes": changes,
				"problem": None,
			}
		)

	return result


def apply(ctx, parsed, plan):
	ctx.stage = "import"
	touched = 0

	for index, item in enumerate(plan):
		if not item.get("name") or not item["changes"]:
			continue

		employee = frappe.get_doc("Employee", item["name"])
		existing = {getdate(r.month): r for r in employee.get(TABLE) or []}

		for change in item["changes"]:
			row = existing.get(getdate(change["field"]))

			if row:
				row.earnings = change["new"]
			else:
				employee.append(TABLE, {"month": change["field"], "earnings": change["new"]})

			touched += 1

		employee.save()
		ctx.progress(
			100 * (index + 1) / len(plan), frappe._("Employee {0} of {1}").format(index + 1, len(plan))
		)

	return {"months": touched}
