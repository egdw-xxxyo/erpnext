import re

import frappe
from frappe.utils import cint, flt, getdate, nowdate

TENURE_TABLE = "custom_insurance_months_table"
EARNINGS_TABLE = "custom_opening_earnings"
SOURCE = "Pension Fund Import"
DECIMAL = re.compile(r"-?\d+\.\d{2}")
DAYS_PAIR = re.compile(r"(\d+)\s+(?:Так|Ні)")
CODE = re.compile(r"\d{8}")
HEADER_WORDS = (
	"Код",
	"Філія",
	"Правонаступник",
	"Орган",
	"ПФУ",
	"ДФС",
	"За рішенням",
	"суду",
	"Найменування страхувальника",
)


def _label(line, start):
	return line.split(":", 1)[1].strip() if line.startswith(start) and ":" in line else None


def _names(lines):
	"""Назву, що не вмістилась в один рядок, дописуємо з наступних рядків до наступного коду."""
	result, current = {}, None

	for line in lines:
		match = re.match(r"(\d{8})\s*(.*)", line)

		if match:
			code, rest = match.groups()
			tokens = rest.split()

			while tokens and tokens[0].isdigit() and len(tokens[0]) <= 5:
				tokens.pop(0)

			current = code

			if not result.get(code):
				result[code] = " ".join(tokens)
				result[("open", code)] = True
			else:
				result[("open", code)] = False
		elif current and result.get(("open", current)) and not any(line.startswith(w) for w in HEADER_WORDS):
			result[current] = f"{result[current]} {line.strip()}".strip()

	return {k: v for k, v in result.items() if isinstance(k, str)}


def parse_lines(lines):
	header = {"full_name": None, "card_number": None, "tax_id": None, "formed_on": None}
	table_lines, years = [], {}
	year = None
	in_table = False
	last_code = None
	pending = None
	declared = {}

	for line in lines:
		line = line.strip()

		if not line:
			continue

		if line.startswith("Прізвище"):
			header["full_name"] = _label(line, "Прізвище")
		elif line.startswith("Номер облікової картки застрахованої"):
			header["card_number"] = _label(line, "Номер облікової картки")
		elif line.startswith("Реєстраційний номер облікової картки"):
			header["tax_id"] = (_label(line, "Реєстраційний номер") or "").replace(" ", "")
		elif line.startswith("Відомості про страхувальників"):
			in_table = True
			continue

		match = re.match(r"Звітний рік:\s*(\d{4})", line)

		if match:
			in_table = False
			year = int(match.group(1))
			years.setdefault(year, {"rows": [], "tenure": None})
			last_code, pending = None, None
			continue

		if in_table:
			table_lines.append(line)
			continue

		if year is None:
			continue

		total = re.match(r"Усього за рік:\s*([\d.]+)\s*грн", line)

		if total:
			declared[year] = flt(total.group(1))
			continue

		if line.startswith("Страховий стаж"):
			numbers = [cint(n) for n in re.findall(r"\d+", line[len("Страховий стаж") :])]

			if len(numbers) == 12:
				years[year]["tenure"] = numbers

			continue

		if line.startswith(("Усього", "Для пенсії")):
			continue

		amounts = DECIMAL.findall(line)

		if len(amounts) == 12:
			first = line.split()[0]
			code = first if CODE.fullmatch(first) else last_code

			if code:
				pending = {"code": code, "earnings": [flt(a) for a in amounts], "days": None}
				years[year]["rows"].append(pending)
				last_code = code

			continue

		pairs = DAYS_PAIR.findall(line)

		if len(pairs) == 12 and pending and pending["days"] is None:
			pending["days"] = [cint(d) for d in pairs]
			continue

		match = re.fullmatch(r"(\d{8})(?:\s+\d{1,2})?", line)

		if match:
			last_code = match.group(1)

	insurers = _names(table_lines)
	months = {}

	for y, data in years.items():
		for month in range(1, 13):
			earnings, best, best_key = 0.0, None, (-1, -1.0)

			for row in data["rows"]:
				money = row["earnings"][month - 1]
				worked = (row["days"] or [0] * 12)[month - 1]
				earnings += money

				if (worked, money) > best_key and (worked or money):
					best, best_key = row["code"], (worked, money)

			days = (data["tenure"] or [0] * 12)[month - 1]

			if days or earnings:
				months[(y, month)] = {"days": days, "earnings": round(earnings, 2), "insurer": best}

	warnings = []

	for y, total in sorted(declared.items()):
		summed = round(sum(row["earnings"][m] for row in years[y]["rows"] for m in range(12)), 2)

		if abs(summed - total) > 0.01:
			warnings.append(
				frappe._("Year {0}: the file says {1}, the table gives {2}").format(y, total, summed)
			)

	return header, insurers, months, warnings


def parse(ctx):
	import pdfplumber

	lines = []

	with pdfplumber.open(ctx.file_path) as pdf:
		pages = len(pdf.pages)

		for index, page in enumerate(pdf.pages):
			ctx.progress(
				10 + 80 * index / max(pages, 1), frappe._("Reading page {0} of {1}").format(index + 1, pages)
			)
			lines.extend((page.extract_text() or "").splitlines())

	ctx.progress(95, frappe._("Checking totals"))
	header, insurers, months, warnings = parse_lines(lines)

	return {
		"header": header,
		"insurers": [{"code": code, "name": name} for code, name in insurers.items()],
		"months": [
			{
				"year": year,
				"month": month,
				"days": data["days"],
				"earnings": data["earnings"],
				"insurer": data["insurer"],
				"insurer_name": insurers.get(data["insurer"]),
			}
			for (year, month), data in sorted(months.items())
		],
		"warnings": warnings,
	}


def _employee(header):
	tax_id = (header.get("tax_id") or "").strip()

	if tax_id:
		found = frappe.db.get_value("Employee", {"custom_tax_id": tax_id}, "name")

		if found:
			return found, None

	return None, frappe._("No employee with the tax number {0}").format(tax_id or "—")


def _first_of_month(year, month):
	return getdate(f"{year}-{month:02d}-01")


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
	existing = {getdate(r.period_start).replace(day=1): r for r in employee.get(TENURE_TABLE) or []}
	earned = {getdate(r.month).replace(day=1): r for r in employee.get(EARNINGS_TABLE) or []}
	earnings_from = getdate(nowdate()).year - 1
	known = set(frappe.get_all("Insurer", pluck="name"))
	changes, same = [], 0

	for row in parsed["months"]:
		start = _first_of_month(row["year"], row["month"])
		kind = "At Company" if joining and start >= joining.replace(day=1) else "Before Joining"
		current = existing.get(start)

		if row["days"]:
			unchanged = (
				current
				and current.days == row["days"]
				and current.period_kind == kind
				and (not row["insurer"] or current.get("insurer") == row["insurer"])
			)

			if unchanged:
				same += 1
			else:
				changes.append(
					{
						"field": start.strftime("%Y-%m"),
						"label": f"{start.strftime('%m.%Y')} · {frappe._(kind)}",
						"old": current.days if current else None,
						"new": row["days"],
						"table": "tenure",
						"period_kind": kind,
						"insurer": row["insurer"],
					}
				)

		if row["year"] >= earnings_from and flt(row["earnings"]) > 0:
			current_earning = earned.get(start)

			if not current_earning or flt(current_earning.earnings) != flt(row["earnings"]):
				changes.append(
					{
						"field": f"earnings:{start.strftime('%Y-%m')}",
						"label": f"{start.strftime('%m.%Y')} · {frappe._('Earnings Before ERP')}",
						"old": current_earning.earnings if current_earning else None,
						"new": row["earnings"],
						"table": "earnings",
					}
				)

	result = [
		{
			"doctype": "Employee",
			"name": name,
			"label": employee.employee_name,
			"changes": changes,
			"unchanged": same,
			"problem": None
			if joining
			else frappe._("The employee has no joining date: every month is stored as before joining."),
		}
	]
	missing = [i for i in parsed["insurers"] if i["code"] not in known]

	if missing:
		frappe.has_permission("Insurer", "create", throw=True)
		result.append(
			{
				"doctype": "Insurer",
				"name": None,
				"label": frappe._("New insurers"),
				"changes": [
					{
						"field": i["code"],
						"label": f"{i['code']} · {i['name'] or '—'}",
						"old": None,
						"new": i["name"],
					}
					for i in missing
				],
				"problem": None,
			}
		)

	return result


def apply(ctx, parsed, plan):
	ctx.stage = "import"
	created = updated = earnings = insurers = 0
	names = {i["code"]: i["name"] for i in parsed["insurers"]}

	for item in plan:
		if item["doctype"] != "Insurer":
			continue

		for change in item["changes"]:
			frappe.get_doc(
				{"doctype": "Insurer", "code": change["field"], "insurer_name": names.get(change["field"])}
			).insert()
			insurers += 1

	for item in plan:
		if item["doctype"] != "Employee" or not item.get("name") or not item["changes"]:
			continue

		employee = frappe.get_doc("Employee", item["name"])
		existing = {getdate(r.period_start).replace(day=1): r for r in employee.get(TENURE_TABLE) or []}
		earned = {getdate(r.month).replace(day=1): r for r in employee.get(EARNINGS_TABLE) or []}
		total = len(item["changes"])

		for index, change in enumerate(item["changes"]):
			if change["table"] == "earnings":
				month = getdate(change["field"].split(":", 1)[1] + "-01")
				row = earned.get(month)

				if row:
					row.earnings = change["new"]
				else:
					employee.append(EARNINGS_TABLE, {"month": month, "earnings": change["new"]})

				earnings += 1
			else:
				start = getdate(change["field"] + "-01")
				row = existing.get(start)
				values = {
					"days": change["new"],
					"period_kind": change["period_kind"],
					"source": SOURCE,
					"import_run": ctx.run,
				}

				if change.get("insurer"):
					values["insurer"] = change["insurer"]

				if row:
					row.update(values)
					updated += 1
				else:
					employee.append(TENURE_TABLE, {"period_start": start, **values})
					created += 1

			ctx.progress(
				100 * (index + 1) / total, frappe._("Writing month {0} of {1}").format(index + 1, total)
			)

		employee.save()

	return {"created": created, "updated": updated, "earnings": earnings, "insurers": insurers}
