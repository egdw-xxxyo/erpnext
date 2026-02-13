#!/usr/bin/env python3
"""Apply final translations for the last 26 empty entries in uk.po."""
import re

PO_FILE = "erpnext/locale/uk.po"

# Unicode right single quotation mark (U+2019) used in source strings
RS = "\u2019"

SIMPLE_TRANSLATIONS = {
    f"Let{RS}s convert your first Sales Order against a Quotation":
        "Давайте перетворимо ваше перше замовлення на продаж за комерційною пропозицією",
    f"Let{RS}s create a Workstation":
        "Давайте створимо робочу станцію",
    f"Let{RS}s create a stock opening entry":
        "Давайте створимо початковий запис запасів",
    f"Let{RS}s create an Operation":
        "Давайте створимо операцію",
    f"Let{RS}s create your first  warehouse ":
        "Давайте створимо ваш перший склад",
    f"Let{RS}s create your first Customer":
        "Давайте створимо вашого першого клієнта",
    f"Let{RS}s create your first Material Request":
        "Давайте створимо ваш перший запит матеріалів",
    f"Let{RS}s create your first Purchase Invoice":
        "Давайте створимо ваш перший рахунок на придбання",
    f"Let{RS}s create your first Purchase Order":
        "Давайте створимо ваше перше замовлення на придбання",
    f"Let{RS}s create your first Quotation":
        "Давайте створимо вашу першу комерційну пропозицію",
    f"Let{RS}s create your first Supplier":
        "Давайте створимо вашого першого постачальника",
    f"Let{RS}s setup your first Letter Head":
        "Давайте налаштуємо ваш перший фірмовий бланк",
    f"Let{RS}s walk-through Selling Settings":
        "Давайте розглянемо налаштування продажів",
    f"Let{RS}s walk-through few Buying Settings":
        "Давайте розглянемо кілька налаштувань закупівель",
}

MULTILINE_TRANSLATIONS = {
    f"# Buying Settings\n\n\nBuying module{RS}s features are highly configurable as per your business needs. Buying Settings is the place where you can set your preferences for:\n\n- Supplier Naming\n- Purchase Order and Purchase Invoice related defaults\n- Purchase Return Settings": (
        f"# Налаштування закупівель\n\n\nФункції модуля закупівель у ERPNext гнучко налаштовуються відповідно до потреб вашого бізнесу. В налаштуваннях закупівель ви можете визначити свої вподобання для:\n\n- Назви постачальника\n- Стандартних значень для замовлень на закупівлю та рахунків на закупівлю\n- Налаштувань повернення закупівлі"
    ),
    f"# CRM Settings\n\nCRM module{RS}s features are configurable as per your business needs. CRM Settings is the place where you can set your preferences for:\n- Campaign\n- Lead\n- Opportunity": (
        "# Налаштування CRM\n\nФункції модуля CRM налаштовуються відповідно до потреб вашого бізнесу. В налаштуваннях CRM ви можете визначити свої вподобання для:\n- Кампанії\n- Лідів\n- Можливостей"
    ),
    f"# Selling Settings\n\nCRM and Selling module{RS}s features are configurable as per your business needs. Selling Settings is the place where you can set your preferences for:\n\n- Customer Naming\n- Campaign\n- Quotation and Order related defaults\n- Sales Return Settings": (
        f"# Налаштування продажів\n\nФункції CRM та модуля продажів налаштовуються відповідно до потреб вашого бізнесу. В налаштуваннях продажів ви можете визначити свої вподобання для:\n\n- Назви клієнта\n- Кампанії\n- Стандартних значень для комерційних пропозицій та замовлень\n- Налаштувань повернення продажів"
    ),
    f"# Review Manufacturing Settings\n\nIn ERPNext, the Manufacturing module{RS}s features are configurable as per your business needs. Manufacturing Settings is the place where you can set your preferences for the Manufacturing Module. Let{RS}s have a walk-through.": (
        "# Перегляд налаштувань виробництва\n\nВ ERPNext функції модуля виробництва налаштовуються відповідно до потреб вашого бізнесу. Налаштування виробництва — це місце, де ви можете задати свої вподобання для модуля виробництва. Давайте розглянемо їх."
    ),
    f"# Review Stock Settings\n\nIn ERPNext, the Stock module{RS}s features are configurable as per your business needs. Stock Settings is the place where you can set your preferences for the Stock Module.": (
        "# Перегляд налаштувань складу\n\nВ ERPNext функції модуля складу налаштовуються відповідно до потреб вашого бізнесу. Налаштування складу — це місце, де ви можете задати свої вподобання для модуля складу."
    ),
    f"# Create a Customer\n\nThe Customer master is at the heart of your sales transactions. Customers are linked in Quotations, Sales Orders, Invoices, and Payments. Customers can be either Individuals or companies. ERPNext allows you to track multiple contacts and addresses per Customer.": (
        "# Створення клієнта\n\nМайстер клієнтів є основою ваших продажів. Клієнти пов'язані в комерційних пропозиціях, замовленнях на продаж, рахунках-фактурах та платежах. Клієнти можуть бути як фізичними, так і юридичними особами. ERPNext дозволяє відстежувати кілька контактів та адрес для кожного клієнта."
    ),
    f"# Create a Quotation\n\nLet{RS}s get started with business transactions by creating your first Quotation. A Quotation can be submitted to your Customers or leads and is a legally non-binding estimate.": (
        "# Створення комерційної пропозиції\n\nДавайте почнемо з бізнес-транзакцій, створивши вашу першу комерційну пропозицію. Комерційна пропозиція може бути надана вашим клієнтам або лідам і є юридично необов'язковим кошторисом."
    ),
    f"# Create a Supplier\n\nAlso known as Vendor, is a master at the center of your purchase transactions. Suppliers are linked in Purchase Orders, Invoices, and Payments. ERPNext allows you to track multiple contacts and addresses per Supplier.": (
        "# Створення постачальника\n\nТакож відомий як Vendor, постачальник є основою ваших закупівель. Постачальники пов'язані в замовленнях на закупівлю, рахунках-фактурах та платежах. ERPNext дозволяє відстежувати кілька контактів та адрес для кожного постачальника."
    ),
    "# Manage Stock Movements\nStock entry allows you to register the movement of stock for various purposes like Material Receipt, Material Issue, Material Transfer, etc.": (
        "# Управління рухом запасів\nЗапис запасів дозволяє реєструвати рух запасів для різних цілей, таких як отримання матеріалів, видача матеріалів, переміщення матеріалів тощо."
    ),
    f"# Setup a Warehouse\nThe warehouse can be your location/godown/store where you maintain the item{RS}s inventory. ERPNext allows you to set up a Tree Structure for your warehouses. ERPNext also allows you to maintain a stock in your supplier{RS}s or customer{RS}s warehouse.": (
        "# Налаштування складу\nСклад може бути вашим місцем зберігання/складом, де ви зберігаєте інвентар товарів. ERPNext дозволяє налаштувати деревоподібну структуру для ваших складів. ERPNext також дозволяє підтримувати запаси на складах вашого постачальника або клієнта."
    ),
    f"# Update Stock Opening Balance\nIt{RS}s an entry to update the stock balance of an item, in a warehouse, on a particular date.": (
        "# Оновлення початкового залишку запасів\nЦе запис для оновлення залишку запасів товару на складі на певну дату."
    ),
    f"If this checkbox is enabled, then the system won{RS}t run the MRP for the available sub-assembly items.": (
        "Якщо цей прапорець увімкнено, система не запускатиме MRP для доступних компонентів підвузла."
    ),
}


def escape_po(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


def unescape_po(s):
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


def parse_msgid_lines(lines):
    parts = []
    for line in lines:
        s = line.strip()
        m = re.match(r'^(?:msgid)\s+"(.*)"$', s)
        if m:
            parts.append(unescape_po(m.group(1)))
            continue
        m2 = re.match(r'^"(.*)"$', s)
        if m2:
            parts.append(unescape_po(m2.group(1)))
    return "".join(parts)


def apply():
    all_translations = {}
    all_translations.update(SIMPLE_TRANSLATIONS)
    all_translations.update(MULTILINE_TRANSLATIONS)

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

            msgid_val = parse_msgid_lines(msgid_lines)

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
                if is_empty and msgid_val and msgid_val in all_translations:
                    uk_val = all_translations[msgid_val]
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
    apply()
