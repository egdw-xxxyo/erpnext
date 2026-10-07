"""Зарплата двома частинами: офіційна (нарахована) і готівкова.

Джерело істини — картка працівника: `custom_official_salary` + `custom_cash_salary`. Усе інше
робиться автоматично:

* при збереженні Employee створюється поданий Salary Structure Assignment, де
  `base` = сума обох частин, а `variable` = офіційна частина;
* при перерахунку Salary Slip відрахування «До виплати готівкою» забирає все нарахування понад
  офіційну суму — тобто пропорцію відпрацьованих днів і премії з `custom_pay_in_cash`;
* з офіційної частини утримуються ПДФО 18% і військовий збір 5%, а ЄСВ 22% додається окремим
  статистичним рядком — це витрата роботодавця, а не утримання (див. `payroll_tax`).

Офіційна сума за місяць фіксована: скільки б днів людина не відпрацювала, нараховується рівно
вона (аванс на картку + решта на картку), а на картку йде 77% від неї. Виняток один — якщо
нарахування менше за офіційну суму, готівки просто немає, і офіційною вважається все нарахування.

У підсумку `net_pay` листка = те, що йде на картку (після податків), а залишок рахунку
«ЗП готівкою до виплати» = те, що видається з каси.
"""

import datetime

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, money_in_words, nowdate, rounded

from erpnext.hr import payroll_tax

CASH_COMPONENT = "До виплати готівкою"
CASH_ADVANCE_COMPONENT = "Аванс готівкою"
STRUCTURE_BY_COMPANY = "Структура ЗП офіц+готівка - {company}"


def sync_salary_structure_assignment(doc, method=None):
	"""Employee.on_update: тримає Salary Structure Assignment у згоді з карткою працівника."""
	try:
		_sync_assignment(doc)
	except Exception:
		frappe.log_error(
			title=f"Не вдалося синхронізувати призначення структури ЗП: {doc.name}",
			message=frappe.get_traceback(),
		)


def _sync_assignment(doc):
	if doc.status != "Active":
		return

	official = flt(doc.get("custom_official_salary"))
	cash = flt(doc.get("custom_cash_salary"))

	if not (official + cash):
		return

	effective = _effective_from(doc)
	structure = STRUCTURE_BY_COMPANY.format(company=doc.company)

	if frappe.db.get_value("Salary Structure", structure, "is_active") != "Yes":
		frappe.msgprint(
			_("Active Salary Structure {0} not found, the assignment was not created.").format(structure),
			indicator="orange",
			alert=True,
		)
		return

	# Картка тримає оклад повної ставки, а призначення — те, що людина справді заробляє:
	# при неповній зайнятості обидві частини множаться на ставку. Далі аванс, відомість і
	# листок читають призначення й нічого про ставку знати не мусять.
	rate = employment_rate(doc)
	paid_official = flt(official * rate, 2)
	paid_cash = flt(cash * rate, 2)
	total = paid_official + paid_cash
	plain = {
		"custom_plain_official": official,
		"custom_plain_cash": cash,
		"custom_employment_rate": rate,
		"custom_official_bonus": 0,
	}

	# Дата → (base, variable, довідкові поля). Оклад із картки діє з `effective`; офіційна
	# доплата живе рівно місяць, тож на її місяць стає окреме призначення, а з наступного —
	# знову оклад.
	wanted = {effective: (total, paid_official, plain)}
	period = bonus_period(doc, effective)

	if period:
		start, following, bonus = period
		wanted[start] = (
			paid_official + bonus + cash_with_bonus(paid_official, paid_cash, bonus),
			paid_official + bonus,
			{**plain, "custom_official_bonus": bonus},
		)
		wanted[following] = (total, paid_official, plain)

	# Картка — джерело правди від `effective` і далі: пізніші призначення лишилися від знятої
	# чи перенесеної доплати або від попередньої ставки, тож вертаються до окладу з картки.
	# Інакше, скажімо, людина на пів ставки з наступного місяця знову отримала б повний оклад.
	later = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": doc.name, "docstatus": 1, "from_date": (">", effective)},
		pluck="from_date",
	)

	for from_date in later:
		wanted.setdefault(getdate(from_date), (total, paid_official, plain))

	for from_date in sorted(wanted):
		_ensure_assignment(doc, structure, from_date, *wanted[from_date])

	# CTC оновлюємо лише разом із призначенням, щоб картка не показувала суму,
	# за якою насправді ніхто не рахує зарплату.
	if flt(doc.ctc) != total:
		doc.db_set("ctc", total, update_modified=False)


# Довідкові поля призначення: оклад повної ставки, ставка й доплата. Суми для розрахунку —
# `base` і `variable`; ці поля лише дають розкласти їх назад (див. `base_salary_parts_on`).
ASSIGNMENT_META = (
	"custom_plain_official",
	"custom_plain_cash",
	"custom_employment_rate",
	"custom_official_bonus",
)


def _ensure_assignment(doc, structure, from_date, base, variable, meta):
	"""Подане призначення структури на дату з рівно такими сумами — або нічого, якщо місяць
	уже порахований."""
	existing = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": doc.name, "from_date": from_date, "docstatus": 1},
		["name", "base", "variable", *ASSIGNMENT_META],
		as_dict=True,
	)
	# Призначення, створені до появи ставки й доплати, довідкових полів не мають — і поки
	# людина на повній ставці без доплати, вони й не потрібні.
	needs_meta = flt(meta["custom_employment_rate"]) != 1 or flt(meta["custom_official_bonus"])

	if (
		existing
		and flt(existing.base) == flt(base)
		and flt(existing.variable) == flt(variable)
		and (
			all(flt(existing.get(field)) == flt(meta[field]) for field in ASSIGNMENT_META)
			or not (needs_meta or flt(existing.custom_employment_rate))
		)
	):
		return

	if _has_submitted_slip(doc.name, from_date):
		frappe.msgprint(
			_(
				"Salary is already processed for the period starting {0}, the assignment was left untouched."
			).format(frappe.format(from_date, {"fieldtype": "Date"})),
			indicator="orange",
			alert=True,
		)
		return

	if existing:
		frappe.get_doc("Salary Structure Assignment", existing.name).cancel()

	assignment = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment",
			"employee": doc.name,
			"salary_structure": structure,
			"from_date": from_date,
			"company": doc.company,
			"currency": doc.get("salary_currency")
			or frappe.get_cached_value("Company", doc.company, "default_currency"),
			"base": base,
			"variable": variable,
			**meta,
		}
	)
	assignment.insert(ignore_permissions=True)
	assignment.submit()


# Тип зайнятості, при якому діє ставка: людина працює частину дня й отримує частину окладу.
PART_TIME = "Part-time"


def employment_rate(doc) -> float:
	"""Ставка зайнятості: 0.5 — пів дня й половина окладу. Усім, крім неповної зайнятості, — 1;
	порожня ставка теж означає повну."""
	if doc.get("employment_type") != PART_TIME:
		return 1.0

	rate = flt(doc.get("custom_employment_rate"), 2)

	return rate if 0 < rate <= 1 else 1.0


def employment_rate_on(employee, on_date) -> float:
	"""Ставка, з якою рахувався оклад на дату — з чинного призначення, а не з картки: картка
	знає лише сьогоднішню."""
	rate = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date)]},
		"custom_employment_rate",
		order_by="from_date desc",
	)

	return flt(rate) or 1.0


def _validate_employment_rate(doc):
	if doc.get("employment_type") != PART_TIME:
		return

	rate = flt(doc.get("custom_employment_rate"), 2)

	if rate < 0 or rate > 1:
		frappe.throw(_("Employment Rate must be between 0 and 1."))

	doc.custom_employment_rate = rate


def _effective_from(doc):
	"""З якої дати діє оклад із картки: не раніше дня прийняття."""
	effective = getdate(doc.get("custom_salary_effective_from") or get_first_day(nowdate()))

	if doc.get("date_of_joining") and effective < getdate(doc.get("date_of_joining")):
		effective = getdate(doc.get("date_of_joining"))

	return effective


def bonus_period(doc, effective=None):
	"""Місяць офіційної доплати: (з якої дати, перше число наступного місяця, сума) або None.

	Доплата рахується як офіційна зарплата, але поле «Оф. ЗП» не міняє й діє один місяць.
	Місяць, раніший за дату окладу в картці, уже минув разом зі старим окладом — така доплата
	лишається в картці лише як запис і нічого не перераховує.
	"""
	bonus = flt(doc.get("custom_official_bonus"))
	month = doc.get("custom_official_bonus_month")

	if not bonus or not month:
		return None

	effective = effective or _effective_from(doc)
	start = getdate(month).replace(day=1)

	if start < effective.replace(day=1):
		return None

	return max(start, effective), getdate(add_months(start, 1)), bonus


def cash_with_bonus(official, cash, bonus) -> float:
	"""Готівка в місяці доплати: на руки людина отримує стільки ж, тож усе, що доплата
	додала на картку, знімається з готівки."""
	shift = payroll_tax.net(flt(official) + flt(bonus)) - payroll_tax.net(official)

	return max(flt(flt(cash) - shift, 2), 0)


def set_card_amount(doc, method=None):
	"""Employee.validate: скільки з офіційної суми дійде до картки і скільки лишається готівкою.

	Домовляються з людиною про суму на руки, тож вводять її («Разом ЗП») та офіційну частину,
	а готівка — те, чого бракує до суми на руки після того, як офіційна дійшла до картки.
	Обидва розраховані поля тільки для читання: рахувати 77% в голові — зайвий привід помилитися.
	"""
	net = payroll_tax.net(doc.get("custom_official_salary"))
	doc.custom_official_salary_net = net
	_set_bonus_month(doc)
	_validate_employment_rate(doc)
	_warn_below_reservation(doc)

	total = flt(doc.get("custom_total_salary"))

	if not total:
		# Картка без суми на руки (заведена раніше або через API) — виводимо її з двох частин.
		doc.custom_total_salary = flt(net + flt(doc.get("custom_cash_salary")), 2)
		return

	cash = flt(total - net, 2)

	if cash < 0:
		frappe.throw(
			_("Total Salary cannot be less than the amount accrued to the card ({0}).").format(
				frappe.format_value(net, {"fieldtype": "Currency"})
			),
			title=_("Total Salary Is Too Low"),
		)

	doc.custom_cash_salary = cash


def _set_bonus_month(doc):
	"""Доплата завжди прив'язана до місяця: без нього — до поточного або до місяця окладу."""
	bonus = flt(doc.get("custom_official_bonus"))

	if bonus < 0:
		frappe.throw(_("Official Bonus cannot be negative."))

	if not bonus:
		doc.custom_official_bonus_month = None
		return

	month = doc.get("custom_official_bonus_month") or max(getdate(nowdate()), _effective_from(doc))
	doc.custom_official_bonus_month = getdate(month).replace(day=1)


def _warn_below_reservation(doc):
	"""Попереджаємо лише про тих, кому оклад має відповідати мінімуму бронювання."""
	if not doc.get("custom_reservation_salary") or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	minimum = payroll_tax.reservation_minimum()
	# Бронюють за тим, що справді нараховано, — при неповній зайнятості це частина окладу.
	official = flt(flt(doc.get("custom_official_salary")) * employment_rate(doc), 2)
	period = bonus_period(doc)

	# Доплата рятує бронювання лише у своєму місяці — минула вже не рахується.
	if period and period[1] > getdate(nowdate()):
		official += period[2]

	if official >= minimum:
		return

	frappe.msgprint(
		_(
			"The official salary is below the reservation minimum of {0} — the employee cannot be reserved."
		).format(frappe.format_value(minimum, {"fieldtype": "Currency"})),
		indicator="orange",
		alert=True,
	)


# Поля картки, які тримають оклад: їх міняє лише керівник працівника (або «Зміна окладу»,
# яка від його імені й затверджується).
SALARY_FIELDS = (
	"custom_total_salary",
	"custom_official_salary",
	"custom_cash_salary",
	"custom_salary_effective_from",
	"custom_official_bonus",
	"custom_official_bonus_month",
	"custom_employment_rate",
)


def restrict_salary_editing(doc, method=None):
	"""Employee.validate: оклад у картці міняє лише керівник цього працівника.

	Вибірка та сама, що й у табелі та зарплатних документах (`erpnext.hr.team`), тож право
	на оклад іде за правом вести людину, а не за роллю. Адміністратор лишається винятком:
	без нього нікому було б виправити картку керівника, який пішов. Менеджер з персоналу
	також веде оклад будь-кого.
	"""
	from erpnext.hr.team import visible_employees

	if doc.is_new() or frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_install:
		return

	if frappe.session.user == "Administrator":
		return

	before = frappe.db.get_value("Employee", doc.name, SALARY_FIELDS, as_dict=True) or {}
	changed = [
		field for field in SALARY_FIELDS if _salary_value(doc.get(field)) != _salary_value(before.get(field))
	]

	if not changed:
		return

	if "HR Manager" in frappe.get_roles():
		return

	if doc.name in visible_employees(doc.company):
		return

	frappe.throw(
		_("Only the manager of {0} may change the salary.").format(doc.employee_name or doc.name),
		title=_("Salary Is Not Yours to Change"),
	)


def _salary_value(value):
	"""Дати й суми з бази й з форми приходять різними типами — порівнюємо їх однаково."""
	if value in (None, ""):
		return None

	if isinstance(value, datetime.date) or (
		isinstance(value, str) and not value.replace(".", "", 1).replace("-", "", 1).isdigit()
	):
		return str(getdate(value))

	return flt(value)


def salary_parts_on(employee, on_date) -> tuple:
	"""Дві частини окладу, чинні на дату: (офіційна, готівкова).

	Читаємо чинне призначення структури, а не картку працівника: картка тримає лише останній
	затверджений оклад, і після «Зміни окладу» на майбутній місяць вона вже показує майбутню
	суму. Картка лишається запасним джерелом — для тих, кому призначення ще не створили.
	"""
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date)]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if assignment:
		return flt(assignment.variable), flt(assignment.base) - flt(assignment.variable)

	official, cash = frappe.db.get_value(
		"Employee", employee, ["custom_official_salary", "custom_cash_salary"]
	) or (0, 0)

	return flt(official), flt(cash)


def base_salary_parts_on(employee, on_date) -> tuple:
	"""Оклад повної ставки без доплати на дату: (офіційна, готівкова, доплата цього місяця).

	Призначення структури тримає вже помножене на ставку, а в місяці доплати — ще й доплату
	всередині офіційної суми та зменшену готівку. Документ, який міняє оклад, має бачити
	вихідні числа — інакше разова доплата чи пів ставки тихо стали б постійним окладом.
	"""
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date)]},
		["base", "variable", *ASSIGNMENT_META],
		order_by="from_date desc",
		as_dict=True,
	)

	if not assignment:
		official, cash = salary_parts_on(employee, on_date)
		return official, cash, 0.0

	# Довідкових полів немає в призначеннях, створених раніше: там повна ставка без доплати.
	if not flt(assignment.custom_employment_rate):
		return flt(assignment.variable), flt(assignment.base) - flt(assignment.variable), 0.0

	return (
		flt(assignment.custom_plain_official),
		flt(assignment.custom_plain_cash),
		flt(assignment.custom_official_bonus),
	)


def apply_salary_to_employee(employee, official, cash, effective_from, bonus=None) -> bool:
	"""Кладе оклад у картку працівника; звідти хук `on_update` створює призначення структури.

	`bonus` — офіційна доплата на місяць `effective_from`; `None` лишає доплату в картці як є.

	Повертає False, якщо в картці вже стоїть рівно те саме — щоб повторне затвердження не
	перестворювало призначення.
	"""
	doc = frappe.get_doc("Employee", employee)
	official, cash = flt(official), flt(cash)
	effective_from = getdate(effective_from)
	bonus_month = effective_from.replace(day=1)
	same_bonus = bonus is None or (
		flt(doc.get("custom_official_bonus")) == flt(bonus)
		and (not flt(bonus) or getdate(doc.get("custom_official_bonus_month") or "1900-01-01") == bonus_month)
	)

	if (
		flt(doc.get("custom_official_salary")) == official
		and flt(doc.get("custom_cash_salary")) == cash
		and getdate(doc.get("custom_salary_effective_from") or "1900-01-01") == effective_from
		and same_bonus
	):
		return False

	doc.custom_total_salary = flt(payroll_tax.net(official) + cash, 2)
	doc.custom_official_salary = official
	doc.custom_cash_salary = cash
	doc.custom_salary_effective_from = effective_from

	if bonus is not None:
		doc.custom_official_bonus = flt(bonus)
		doc.custom_official_bonus_month = bonus_month if flt(bonus) else None

	doc.flags.ignore_mandatory = True
	doc.save()

	return True


def has_submitted_slip(employee, date) -> bool:
	return bool(_has_submitted_slip(employee, date))


def _has_submitted_slip(employee, date):
	return frappe.db.exists(
		"Salary Slip",
		{"employee": employee, "docstatus": 1, "start_date": ["<=", date], "end_date": [">=", date]},
	)


def apply_cash_split(doc, method=None):
	"""Salary Slip.validate: наповнює відрахування «До виплати готівкою».

	Рахується з нуля, тому хук ідемпотентний і не залежить від того, що вже лежить у рядку.
	"""
	if not doc.employee or not doc.start_date:
		return

	if not frappe.db.exists("Salary Component", CASH_COMPONENT):
		return

	# Призначення шукаємо по кінцю періоду, а не по початку: у працівника, прийнятого всередині
	# місяця, воно діє з дати прийняття, і по `start_date` ми б його не знайшли.
	assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": doc.employee, "docstatus": 1, "from_date": ["<=", doc.end_date]},
		["base", "variable"],
		order_by="from_date desc",
		as_dict=True,
	)

	if not assignment:
		return

	# Офіційна сума не ділиться на відпрацьовані дні: за домовленістю за місяць має нарахуватися
	# рівно вона (аванс на картку + решта на картку). Пропорцію відпрацьованих днів і всі премії
	# поглинає готівкова частина — вона ж лишок нарахування понад офіційну суму.
	official = flt(assignment.variable) + _official_bonuses(doc)

	# Готівкову виплату зменшують лише ті відрахування, які й видані готівкою (аванс з каси,
	# задаток). Відрахування без прапорця пішли з рахунку, тож вони зменшують офіційну частину.
	cash_amount = flt(doc.gross_pay) - official - _cash_deductions(doc)
	_set_component_row(doc, CASH_COMPONENT, flt(max(cash_amount, 0), doc.precision("amount", "deductions")))

	# Оподатковується лише те, що справді нараховано: у неповному місяці без готівкової частини
	# нарахування менше за офіційну суму, і податок з неіснуючих грошей утримувати нема з чого.
	_set_tax_rows(doc, min(official, flt(doc.gross_pay)))
	_recalculate_totals(doc)


def _set_tax_rows(doc, taxable):
	"""ПДФО і військовий збір — утримання, ЄСВ — статистичний рядок вартості для компанії.

	Ставку ЄСВ вибирає картка працівника: з групою інвалідності вона пільгова.
	"""
	taxes = payroll_tax.split(taxable, doc.employee)

	for component, amount, statistical in (
		(payroll_tax.PIT_COMPONENT, taxes.pit, 0),
		(payroll_tax.MILITARY_COMPONENT, taxes.military, 0),
		(payroll_tax.SSC_COMPONENT, taxes.ssc, 1),
	):
		if not frappe.db.exists("Salary Component", component):
			continue

		_set_component_row(doc, component, amount, statistical=statistical)


def _official_bonuses(doc):
	"""Премії та надбавки без прапорця «Виплата готівкою» — вони збільшують виплату на картку."""
	total = 0.0

	for row in doc.get("earnings") or []:
		if not row.get("additional_salary"):
			continue

		if not frappe.db.get_value("Additional Salary", row.additional_salary, "custom_pay_in_cash"):
			total += flt(row.amount)

	return total


def _cash_deductions(doc):
	"""Відрахування, видані готівкою: аванс з каси, задаток тощо."""
	total = 0.0

	for row in doc.get("deductions") or []:
		if row.salary_component == CASH_COMPONENT:
			continue

		if row.salary_component == CASH_ADVANCE_COMPONENT:
			total += flt(row.amount)
			continue

		if not row.get("additional_salary"):
			continue

		if frappe.db.get_value("Additional Salary", row.additional_salary, "custom_pay_in_cash"):
			total += flt(row.amount)

	return total


def _set_component_row(doc, component, amount, statistical=0):
	existing = [row for row in doc.get("deductions") or [] if row.salary_component == component]

	if not amount:
		for row in existing:
			doc.remove(row)
		return

	if existing:
		existing[0].amount = amount
		existing[0].default_amount = amount
		return

	meta = frappe.get_cached_doc("Salary Component", component)
	doc.append(
		"deductions",
		{
			"salary_component": component,
			"abbr": meta.salary_component_abbr,
			"amount": amount,
			"default_amount": amount,
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
			"statistical_component": statistical,
			"do_not_include_in_total": statistical,
		},
	)


def _recalculate_totals(doc):
	# Статистичні рядки (ЄСВ) видно в листку, але жодної суми вони не зменшують.
	doc.total_deduction = sum(
		flt(row.amount)
		for row in doc.get("deductions") or []
		if not (row.get("statistical_component") or row.get("do_not_include_in_total"))
	)
	doc.net_pay = flt(doc.gross_pay) - flt(doc.total_deduction)
	doc.rounded_total = rounded(doc.net_pay)
	doc.total_in_words = money_in_words(doc.rounded_total, doc.currency)


def backfill_from_assignments(company=None, dry_run=True):
	"""Разово розкладає наявні призначення на дві суми в картці працівника.

	bench --site frontend execute erpnext.hr.salary_split.backfill_from_assignments \
	    --kwargs "{'dry_run': False}"
	"""
	filters = {"status": "Active"}

	if company:
		filters["company"] = company

	employees = frappe.get_all("Employee", filters=filters, pluck="name")
	updated = skipped = 0

	for employee in employees:
		assignment = frappe.db.get_value(
			"Salary Structure Assignment",
			{"employee": employee, "docstatus": 1},
			["base", "variable", "from_date"],
			order_by="from_date desc",
			as_dict=True,
		)

		if not assignment or not flt(assignment.base):
			skipped += 1
			continue

		official = flt(assignment.variable)
		cash = flt(assignment.base) - official
		print(f"  {employee}: офіційна {official}, готівкова {cash}, з {assignment.from_date}")

		if dry_run:
			continue

		frappe.db.set_value(
			"Employee",
			employee,
			{
				"custom_official_salary": official,
				"custom_cash_salary": cash,
				"custom_salary_effective_from": assignment.from_date,
				"ctc": flt(assignment.base),
			},
			update_modified=False,
		)
		updated += 1

	if not dry_run:
		frappe.db.commit()

	print(f"Оброблено: {len(employees)}, оновлено: {updated}, пропущено без призначення: {skipped}")
