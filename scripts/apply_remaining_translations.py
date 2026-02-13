#!/usr/bin/env python3
"""Apply manual translations for the remaining 67 empty entries in uk.po."""
import re

PO_FILE = "erpnext/locale/uk.po"

TRANSLATIONS = {
    "From Lead": "Від ліду",
    "From Opportunity": "Від можливості",
    "Full Name": "Повне ім'я",
    "Gender": "Стать",
    "General": "Загальне",
    "Get Items From Purchase Receipts": "Отримати товари з товарних чеків",
    "Homepage Slideshow": "Слайд-шоу головної сторінки",
    "Query Options": "Параметри запиту",
    "Queued": "В черзі",
    "Quickbooks Company ID": "Ідентифікатор компанії Quickbooks",
    "Random": "Випадково",
    "Rate Difference with Purchase Invoice": "Різниця ставки з рахунком на придбання",
    "Rating": "Рейтинг",
    "Raw Materials Warehouse": "Склад сировини",
    "Read Only": "Лише для читання",
    "Recipient": "Одержувач",
    "Recipients": "Одержувачі",
    "Report Filters": "Фільтри звіту",
    "Report Type": "Тип звіту",
    "Repost Required": "Потрібне перепроведення",
    "Role Allowed to Set Frozen Accounts and Edit Frozen Entries": "Роль, яка може налаштовувати заморожені рахунки та редагувати заморожені записи",
    "Route": "Маршрут",
    "Let's convert your first Sales Order against a Quotation": "Давайте перетворимо ваше перше замовлення на продаж за комерційною пропозицією",
    "Let's create a Workstation": "Давайте створимо робочу станцію",
    "Let's create a stock opening entry": "Давайте створимо початковий запис запасів",
    "Let's create an Operation": "Давайте створимо операцію",
    "Let's create your first  warehouse ": "Давайте створимо ваш перший склад",
    "Let's create your first Customer": "Давайте створимо вашого першого клієнта",
    "Let's create your first Material Request": "Давайте створимо ваш перший запит матеріалів",
    "Let's create your first Purchase Invoice": "Давайте створимо ваш перший рахунок на придбання",
    "Let's create your first Purchase Order": "Давайте створимо ваше перше замовлення на придбання",
    "Let's create your first Quotation": "Давайте створимо вашу першу комерційну пропозицію",
    "Let's create your first Supplier": "Давайте створимо вашого першого постачальника",
    "Let's setup your first Letter Head": "Давайте налаштуємо ваш перший фірмовий бланк",
    "Let's walk-through Selling Settings": "Давайте розглянемо налаштування продажів",
    "Let's walk-through few Buying Settings": "Давайте розглянемо кілька налаштувань закупівель",
    "If this checkbox is enabled, then the system won\\'t run the MRP for the available stock to consider for the production of the sub-assembly item.": "Якщо цей прапорець увімкнено, система не запускатиме MRP для наявних запасів, які слід врахувати при виробництві компонента підвузла.",
}


def escape_po(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


def unescape_po(s):
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


def apply(translations):
    with open(PO_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    filled = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid "):
            msgid_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid_lines.append(lines[i])
                i += 1

            # Parse msgid value
            parts = []
            for ml in msgid_lines:
                s = ml.strip()
                m = re.match(r'^(?:msgid)\s+"(.*)"$', s)
                if m:
                    parts.append(unescape_po(m.group(1)))
                    continue
                m2 = re.match(r'^"(.*)"$', s)
                if m2:
                    parts.append(unescape_po(m2.group(1)))
            msgid_val = "".join(parts)

            inter = []
            while i < len(lines) and not lines[i].startswith("msgstr ") and not lines[i].startswith("msgid "):
                inter.append(lines[i])
                i += 1

            if i < len(lines) and lines[i].startswith("msgstr "):
                msgstr_line = lines[i]
                i += 1
                msgstr_cont = []
                while i < len(lines) and lines[i].startswith('"'):
                    msgstr_cont.append(lines[i])
                    i += 1

                is_empty = msgstr_line.strip() == 'msgstr ""' and not msgstr_cont
                if is_empty and msgid_val and msgid_val in translations:
                    uk_val = translations[msgid_val]
                    out.extend(msgid_lines)
                    out.extend(inter)
                    out.append(f'msgstr "{escape_po(uk_val)}"\n')
                    filled += 1
                else:
                    out.extend(msgid_lines)
                    out.extend(inter)
                    out.append(msgstr_line)
                    out.extend(msgstr_cont)
            else:
                out.extend(msgid_lines)
                out.extend(inter)
        else:
            out.append(line)
            i += 1

    with open(PO_FILE, "w", encoding="utf-8") as f:
        f.write("".join(out))
    print(f"Filled {filled} entries")


if __name__ == "__main__":
    apply(TRANSLATIONS)
