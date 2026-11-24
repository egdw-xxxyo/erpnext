import re

import frappe
from frappe.utils import cint, get_last_day, getdate

YEAR_X_MAX = 130
HEADER_ROW_GAP = 4
DATA_ROW_MAX_GAP = 18


def _lines(page):
	words = page.extract_words(x_tolerance=1.5, keep_blank_chars=False)
	rows = {}

	for word in words:
		rows.setdefault(round(word["top"]), []).append(word)

	return [sorted(row, key=lambda w: w["x0"]) for _top, row in sorted(rows.items())]


def _text(row):
	return " ".join(w["text"] for w in row)


def _center(word):
	return (word["x0"] + word["x1"]) / 2


def parse(ctx):
	import pdfplumber

	header = {"full_name": None, "card_number": None, "tax_id": None, "period_from": None, "period_to": None}
	months = {}
	year_totals = {}
	total_line = None

	with pdfplumber.open(ctx.file_path) as pdf:
		pages = len(pdf.pages)

		for index, page in enumerate(pdf.pages):
			ctx.progress(
				10 + 80 * index / max(pages, 1), frappe._("Reading page {0} of {1}").format(index + 1, pages)
			)
			rows = _lines(page)

			for position, row in enumerate(rows):
				line = _text(row)
				compact = line.replace(" ", "")

				if compact.startswith("Прізвище"):
					header["full_name"] = " ".join(w["text"] for w in row if w["x0"] > 270).strip()
				elif compact.startswith("Номеробліковоїкарткизастрахованої"):
					header["card_number"] = "".join(w["text"] for w in row if w["x0"] > 270)
				elif compact.startswith("Реєстраційнийномер"):
					header["tax_id"] = "".join(w["text"] for w in row if w["x0"] > 270)
				elif compact.startswith("Відомостізазвітнийперіод"):
					dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", line)

					if len(dates) == 2:
						header["period_from"], header["period_to"] = (
							getdate("-".join(reversed(d.split(".")))) for d in dates
						)
				elif compact.startswith("Страховийстажзагальний"):
					found = re.findall(r"\d+", line.split(":", 1)[-1])
					total_line = [int(n) for n in found[-3:]] if len(found) >= 3 else None
				elif compact.startswith("Страховийстажзазвітнийрік"):
					found = [int(n) for n in re.findall(r"\d+", line.split(":", 1)[-1])]

					if len(found) >= 2 and year_totals.get("_last") is not None:
						year_totals[year_totals.pop("_last")] = (found[0], found[1])

				first = row[0]

				if first["x0"] < YEAR_X_MAX and re.fullmatch(r"(19|20)\d{2}", first["text"]):
					year = int(first["text"])
					columns = {}

					for word in row[1:]:
						if word["text"].isdigit() and 1 <= int(word["text"]) <= 12:
							columns[int(word["text"])] = _center(word)

					if len(columns) != 12:
						continue

					year_totals["_last"] = year

					if position + 1 < len(rows):
						data = rows[position + 1]

						if data[0]["top"] - row[0]["top"] <= DATA_ROW_MAX_GAP:
							for word in data:
								if not word["text"].isdigit():
									continue

								month = min(columns, key=lambda m: abs(columns[m] - _center(word)))

								if abs(columns[month] - _center(word)) < 14:
									months[(year, month)] = cint(word["text"])

	year_totals.pop("_last", None)
	ctx.progress(95, frappe._("Checking totals"))

	warnings = _check(months, year_totals, total_line)
	rows = [{"year": year, "month": month, "days": days} for (year, month), days in sorted(months.items())]

	return {
		"header": {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in header.items()},
		"months": rows,
		"warnings": warnings,
		"declared_total": total_line,
	}


def _tenure(days_by_month):
	"""Місяць зараховується повністю, якщо днів не менше за його довжину; решта днів — по 30 = місяць."""
	full, rest = 0, 0

	for (year, month), days in days_by_month.items():
		length = get_last_day(f"{year}-{month:02d}-01").day

		if days >= length:
			full += 1
		else:
			rest += days

	return full + rest // 30, rest % 30


def _check(months, year_totals, total_line):
	warnings = []

	for year, declared in sorted(year_totals.items()):
		own = {k: v for k, v in months.items() if k[0] == year}
		counted = _tenure(own)

		if tuple(counted) != tuple(declared):
			warnings.append(
				frappe._("Year {0}: the file says {1} m {2} d, the table gives {3} m {4} d").format(
					year, declared[0], declared[1], counted[0], counted[1]
				)
			)

	if total_line:
		years, month_count, days = total_line
		counted = _tenure(months)
		declared_months = years * 12 + month_count

		if (counted[0], counted[1]) > (declared_months, days):
			warnings.append(
				frappe._("Total: the file says {0} m {1} d, the table gives more: {2} m {3} d").format(
					declared_months, days, counted[0], counted[1]
				)
			)

	return warnings


TABLE = "custom_insurance_months_table"


def _employee(header):
	tax_id = (header.get("tax_id") or "").strip()

	if tax_id:
		found = frappe.db.get_value("Employee", {"custom_tax_id": tax_id}, "name")

		if found:
			return found, None

	return None, frappe._("No employee with the tax number {0}").format(tax_id or "—")


def plan(ctx, parsed):
	header = parsed["header"]
	name, problem = _employee(header)

	if not name:
		return [
			{
				"doctype": "Employee",
				"name": None,
				"label": header.get("full_name"),
				"changes": [],
				"problem": problem,
			}
		]

	frappe.has_permission("Employee", "write", doc=name, throw=True)
	employee = frappe.get_doc("Employee", name)
	joining = getdate(employee.date_of_joining) if employee.date_of_joining else None
	existing = {getdate(r.period_start).replace(day=1): r for r in employee.get(TABLE) or []}
	changes, same = [], 0

	for row in parsed["months"]:
		start = getdate(f"{row['year']}-{row['month']:02d}-01")
		kind = "At Company" if joining and start >= joining.replace(day=1) else "Before Joining"
		current = existing.get(start)

		if current and current.days == row["days"] and current.period_kind == kind:
			same += 1
			continue

		changes.append(
			{
				"field": start.strftime("%Y-%m"),
				"label": f"{start.strftime('%m.%Y')} · {frappe._(kind)}",
				"old": current.days if current else None,
				"new": row["days"],
				"period_kind": kind,
			}
		)

	problem = (
		None
		if joining
		else frappe._("The employee has no joining date: every month is stored as before joining.")
	)

	return [
		{
			"doctype": "Employee",
			"name": name,
			"label": employee.employee_name,
			"changes": changes,
			"unchanged": same,
			"problem": problem,
		}
	]


def apply(ctx, parsed, plan):
	ctx.stage = "import"
	created = updated = 0

	for item in plan:
		if not item.get("name") or not item["changes"]:
			continue

		employee = frappe.get_doc("Employee", item["name"])
		existing = {getdate(r.period_start).replace(day=1): r for r in employee.get(TABLE) or []}
		total = len(item["changes"])

		for index, change in enumerate(item["changes"]):
			start = getdate(change["field"] + "-01")
			row = existing.get(start)

			if row:
				row.days = change["new"]
				row.period_kind = change["period_kind"]
				row.source = "Pension Fund Import"
				row.import_run = ctx.run
				updated += 1
			else:
				employee.append(
					TABLE,
					{
						"period_start": start,
						"days": change["new"],
						"period_kind": change["period_kind"],
						"source": "Pension Fund Import",
						"import_run": ctx.run,
					},
				)
				created += 1

			ctx.progress(
				100 * (index + 1) / total, frappe._("Writing month {0} of {1}").format(index + 1, total)
			)

		employee.save()

	return {"created": created, "updated": updated}
