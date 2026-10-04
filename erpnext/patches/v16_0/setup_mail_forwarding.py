import frappe

RECIPIENTS = (
	("ОД", "Операційний директор", "Діма"),
	("ФІН", "Начальник фінансового відділу", "Наталія"),
	("КАД", "Начальник відділу кадрів", "Вікторія"),
	("ПРОД", "Відділ продажів", None),
	("ЗАК", "Відділ закупівель", None),
)

RULES = (
	("ПУМБ", "@pumb.ua @fuib.com info@pumb-pro-business.com.ua", ("ФІН",)),
	("А-Банк, корпоративний відділ", "msb@a-bank.com.ua", ("ФІН",)),
	("Сенс Банк", "@sensebank.com.ua", ("ФІН",)),
	("Банк Кредит Дніпро", "@creditdnepr.com", ("ФІН",)),
	("Е-кабінет ДПС", "e.cabinet@tax.gov.ua", ("ФІН",)),
	("Вчасно, M.E.Doc", "@vchasno.ua @vchasno.com.ua edo_notify@send.medoc.ua", ("ФІН",)),
	("Універ (брокерський рахунок)", "@univer.ua", ("ФІН",)),
	("Нова Пошта (бізнес-кабінет)", "@novaposhta.ua", ("ФІН",)),
	("Дія (бронювання, реєстр військовозобов'язаних)", "noreply@diia.gov.ua", ("КАД",)),
	("Електронний суд", "@court.gov.ua e.court@cabinet.court.gov.ua", ("ФІН", "КАД")),
	("Агенція оборонних закупівель", "official@dot.gov.ua", ("ОД",)),
	("АОЗ, закупівлі", "procurement@dot.gov.ua", ("ОД",)),
	("Держспецзв'язку (ДСЗИ)", "dz@cip.gov.ua", ("ОД",)),
	("ГУЗСЖЦ ОВТ (кодифікація)", "mdalc@mil.gov.ua", ("ОД",)),
	("AMT Logistics (ВМД)", "@amtl.com.ua", ("ОД",)),
	("LOGO-SVIT (ВМД)", "@logo-svit.com.ua", ("ОД",)),
	("Nova Poshta Global", "@novaposhtaglobal.ua", ("ОД",)),
	("DHL", "@dhl.com", ("ОД",)),
	("Народні депутати", "@rada.gov.ua", ("ОД",)),
	("Військові частини, МОУ", "@post.mil.gov.ua", ("ОД",)),
	("Закупівлі.Про: запрошення до закупівель", "noreply@zakupivli.pro support@zakupivli.pro", ("ПРОД",)),
	("ДЗО: процедури Prozorro", "dzo.com.ua", ("ПРОД",)),
	("Defence Sourcing Portal (UK MoD)", "dsp@jaggaer.com", ("ПРОД",)),
	("ДПСУ: запити КП", "@dpsu.gov.ua", ("ПРОД",)),
	("Brave1: закупівлі, зустрічі з виробниками", "info@brave1.gov.ua", ("ПРОД",)),
	("K Exports: проформи, замовлення", "@kexports.us", ("ЗАК",)),
	("Janusorion: рахунки, компенсації витрат", "orders@janusorion.eu", ("ЗАК",)),
	(
		"Постачальники інструменту й обладнання",
		"info@grn-tools.com.ua info@led.kiev.ua support@dnipro-m.ua bn@comfy.ua",
		("ЗАК",),
	),
)


def execute():
	seed_recipients()
	seed_rules()


def seed_recipients():
	missing = [row for row in RECIPIENTS if not frappe.db.exists("Mail Forward Recipient", row[0])]
	for code, role, full_name in missing:
		frappe.get_doc(
			{"doctype": "Mail Forward Recipient", "code": code, "role": role, "full_name": full_name}
		).insert(ignore_permissions=True)


def seed_rules():
	if frappe.db.count("Mail Forward Rule"):
		return
	for description, patterns, codes in RULES:
		frappe.get_doc(
			{
				"doctype": "Mail Forward Rule",
				"description": description,
				"sender_patterns": patterns,
				"recipients": [{"recipient": code} for code in codes],
			}
		).insert(ignore_permissions=True)
