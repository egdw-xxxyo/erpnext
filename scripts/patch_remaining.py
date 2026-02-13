#!/usr/bin/env python3
"""Patch remaining empty entries using direct string replacement in uk.po."""

PO_FILE = "erpnext/locale/uk.po"
RS = "\u2019"  # RIGHT SINGLE QUOTATION MARK

with open(PO_FILE, encoding="utf-8") as f:
    content = f.read()

patches = [
    # Format: (unique_text_in_msgid_block, new_msgstr_value)
    # Simple single-line entries with curly apostrophes
    (f'msgid "Let{RS}s convert your first Sales Order against a Quotation"',
     "Давайте перетворимо ваше перше замовлення на продаж за комерційною пропозицією"),
    (f'msgid "Let{RS}s create a Workstation"',
     "Давайте створимо робочу станцію"),
    (f'msgid "Let{RS}s create a stock opening entry"',
     "Давайте створимо початковий запис запасів"),
    (f'msgid "Let{RS}s create an Operation"',
     "Давайте створимо операцію"),
    (f'msgid "Let{RS}s create your first  warehouse "',
     "Давайте створимо ваш перший склад"),
    (f'msgid "Let{RS}s create your first Customer"',
     "Давайте створимо вашого першого клієнта"),
    (f'msgid "Let{RS}s create your first Material Request"',
     "Давайте створимо ваш перший запит матеріалів"),
    (f'msgid "Let{RS}s create your first Purchase Invoice"',
     "Давайте створимо ваш перший рахунок на придбання"),
    (f'msgid "Let{RS}s create your first Purchase Order"',
     "Давайте створимо ваше перше замовлення на придбання"),
    (f'msgid "Let{RS}s create your first Quotation"',
     "Давайте створимо вашу першу комерційну пропозицію"),
    (f'msgid "Let{RS}s create your first Supplier"',
     "Давайте створимо вашого першого постачальника"),
    (f'msgid "Let{RS}s setup your first Letter Head"',
     "Давайте налаштуємо ваш перший фірмовий бланк"),
    (f'msgid "Let{RS}s walk-through Selling Settings"',
     "Давайте розглянемо налаштування продажів"),
    (f'msgid "Let{RS}s walk-through few Buying Settings"',
     "Давайте розглянемо кілька налаштувань закупівель"),
    # "If this checkbox..."
    (f'msgid ""\n"If this checkbox is enabled, then the system won{RS}t run the MRP for the "\n"available sub-assembly items."',
     "Якщо цей прапорець увімкнено, система не запускатиме MRP для доступних компонентів підвузла."),
    # Multi-line markdown entries - matched by their unique first line
    ('"# Buying Settings\\n"\n"\\n"\n"\\n"',
     f"# Налаштування закупівель\n\n\nФункції модуля закупівель у ERPNext гнучко налаштовуються відповідно до потреб вашого бізнесу. Налаштування закупівель — це місце, де ви можете визначити свої вподобання для:\n\n- Назви постачальника\n- Стандартних значень для замовлень на закупівлю та рахунків-фактур\n- Налаштувань повернення закупівлі"),
    ('"# CRM Settings\\n"\n"\\n"\n"CRM module',
     "# Налаштування CRM\n\nФункції модуля CRM налаштовуються відповідно до потреб вашого бізнесу. Налаштування CRM — це місце, де ви можете визначити свої вподобання для:\n- Кампанії\n- Лідів\n- Можливостей"),
    ('"# Create a Customer\\n"',
     "# Створення клієнта\n\nМайстер клієнтів є основою ваших продажів. Клієнти пов'язані в комерційних пропозиціях, замовленнях на продаж, рахунках-фактурах та платежах. Клієнти можуть бути як фізичними, так і юридичними особами. ERPNext дозволяє відстежувати кілька контактів та адрес для кожного клієнта."),
    ('"# Create a Quotation\\n"',
     "# Створення комерційної пропозиції\n\nДавайте почнемо з бізнес-транзакцій, створивши вашу першу комерційну пропозицію. Комерційна пропозиція може бути надана вашим клієнтам або лідам і є юридично необов'язковим кошторисом."),
    ('"# Create a Supplier\\n"',
     "# Створення постачальника\n\nТакож відомий як Постачальник — він є основою ваших закупівель. Постачальники пов'язані в замовленнях на закупівлю, рахунках-фактурах та платежах. ERPNext дозволяє відстежувати кілька контактів та адрес для кожного постачальника."),
    ('"# Manage Stock Movements\\n"',
     "# Управління рухом запасів\nЗапис запасів дозволяє реєструвати рух запасів для різних цілей, таких як переміщення, отримання, видача матеріалів, виробнича видача тощо."),
    ('"# Review Manufacturing Settings\\n"',
     "# Перегляд налаштувань виробництва\n\nВ ERPNext функції модуля виробництва налаштовуються відповідно до потреб вашого бізнесу. Налаштування виробництва — це місце, де ви можете задати свої вподобання для модуля виробництва."),
    ('"# Review Stock Settings\\n"',
     "# Перегляд налаштувань складу\n\nВ ERPNext функції модуля складу налаштовуються відповідно до потреб вашого бізнесу. Налаштування складу — це місце, де ви можете задати свої вподобання для модуля складу."),
    ('"# Selling Settings\\n"\n"\\n"\n"CRM and Selling module',
     "# Налаштування продажів\n\nФункції CRM та модуля продажів налаштовуються відповідно до потреб вашого бізнесу. Налаштування продажів — це місце, де ви можете визначити свої вподобання для:\n\n- Назви клієнта\n- Кампанії\n- Стандартних значень для комерційних пропозицій та замовлень\n- Налаштувань повернення продажів"),
    ('"# Setup a Warehouse\\n"',
     "# Налаштування складу\nСклад може бути вашим місцем зберігання, де ви підтримуєте інвентар товарів та отримуєте поставки. ERPNext дозволяє налаштувати деревоподібну структуру для ваших складів."),
    ('"# Update Stock Opening Balance\\n"',
     "# Оновлення початкового залишку запасів\nЦе запис для оновлення залишку запасів товару на складі на певну дату та час."),
]


def escape_po(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


patched = 0
for search_text, translation in patches:
    # For simple single-line msgid entries
    if search_text.startswith('msgid "'):
        old = f'{search_text}\nmsgstr ""\n'
        new = f'{search_text}\nmsgstr "{escape_po(translation)}"\n'
        if old in content:
            content = content.replace(old, new, 1)
            patched += 1
        else:
            print(f"NOT FOUND: {search_text[:60]!r}")
    else:
        # Multi-line: find the containing block
        # The search_text identifies a unique substring in the msgid block
        # Find "msgstr ""\n" that immediately follows a block containing search_text
        idx = content.find(search_text)
        if idx == -1:
            print(f"NOT FOUND: {search_text[:60]!r}")
            continue
        # Find the msgstr "" after this point
        msgstr_idx = content.find('\nmsgstr ""\n', idx)
        if msgstr_idx == -1:
            print(f"NO EMPTY MSGSTR after: {search_text[:60]!r}")
            continue
        # Make sure no other msgid comes between idx and msgstr_idx
        next_msgid = content.find('\nmsgid ', idx + 1)
        if next_msgid != -1 and next_msgid < msgstr_idx:
            print(f"MSGID INTERVENES: {search_text[:60]!r}")
            continue
        old = '\nmsgstr ""\n'
        new = f'\nmsgstr "{escape_po(translation)}"\n'
        content = content[:msgstr_idx] + new + content[msgstr_idx + len(old):]
        patched += 1

with open(PO_FILE, "w", encoding="utf-8") as f:
    f.write(content)
print(f"\nPatched {patched} entries")
