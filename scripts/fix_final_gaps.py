#!/usr/bin/env python3
"""Fix the final 33 gaps in uk.po by directly patching the file."""

import polib
import sys

po = polib.POFile()
po = polib.pofile('erpnext/locale/uk.po')

# Load the Russian translations for reference
ru = polib.pofile('erpnext/locale/ru.po')
ru_dict = {e.msgid: e.msgstr for e in ru if e.msgstr}

# Define translations for the 33 remaining gaps
# Key = substring to match in msgid, Value = Ukrainian translation
translations = {}

# 1. SN-01::10
for e in po:
    if e.msgid.startswith('"SN-01::10"') and not e.msgstr:
        e.msgstr = '"СН-01::10" від "SN-01" до "SN-10\\'
        print(f"  1. Fixed: SN-01::10")
        break

# 2. Jinja tags Note (process_statement_of_accounts)
for e in po:
    if 'Jinja tags</a> in <b>Subject</b>' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            '<h4>Note</h4>', '<h4>Примітка</h4>'
        ).replace(
            'You can use', 'Ви можете використовувати'
        ).replace(
            'Jinja tags', 'теги Jinja'
        ).replace(
            'in <b>Subject</b> and <b>Body</b> fields for dynamic values.',
            'у полях <b>Тема</b> та <b>Тіло</b> для динамічних значень.'
        ).replace(
            'All fields in this doctype are available under the <b>doc</b> object and all fields for the customer to whom the mail will go to is available under the  <b>customer</b> object.',
            'Усі поля цього типу документа доступні через об\'єкт <b>doc</b>, а всі поля клієнта, якому буде надіслано лист, доступні через об\'єкт <b>customer</b>.'
        ).replace(
            '<h4> Examples</h4>', '<h4> Приклади</h4>'
        ).replace(
            '<b>Subject</b>:', '<b>Тема</b>:'
        ).replace(
            'Statement Of Accounts for', 'Виписка по рахунках для'
        ).replace(
            '<b>Body</b>:', '<b>Тіло</b>:'
        ).replace(
            'Hello', 'Вітаємо,'
        ).replace(
            ',\\nPFA your Statement Of Accounts from',
            '\\nДодаємо вашу виписку по рахунках з'
        ).replace(
            ' to {{ doc.to_date }}.', ' по {{ doc.to_date }}.'
        )
        print(f"  2. Fixed: Jinja tags Note")
        break

# 3. Other Details
for e in po:
    if e.msgid == '<div class=\\"columnHeading\\">Other Details</div>' and not e.msgstr:
        e.msgstr = '<div class=\\"columnHeading\\">Інші деталі</div>'
        print(f"  3. Fixed: Other Details")
        break

# 4. No Matching Bank Transactions Found
for e in po:
    if 'No Matching Bank Transactions Found' in e.msgid and not e.msgstr:
        e.msgstr = '<div class=\\"text-muted text-center\\">Відповідних банківських транзакцій не знайдено</div>'
        print(f"  4. Fixed: No Matching Bank Transactions")
        break

# 5. {0} div
for e in po:
    if e.msgid == '<div class=\\"text-muted text-center\\">{0}</div>' and not e.msgstr:
        e.msgstr = '<div class=\\"text-muted text-center\\">{0}</div>'
        print(f"  5. Fixed: {{0}} div")
        break

# 6. All dimensions in centimeter
for e in po:
    if 'All dimensions in centimeter only' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace('All dimensions in centimeter only', 'Усі розміри лише в сантиметрах')
        print(f"  6. Fixed: All dimensions in centimeter")
        break

# 7. About Product Bundle
for e in po:
    if '<h3>About Product Bundle</h3>' in e.msgid and not e.msgstr:
        e.msgstr = (
            '<h3>Про комплект продуктів</h3>\\n\\n'
            '<p>Групування <b>позицій</b> в іншу <b>позицію</b>. Це корисно, якщо ви об\'єднуєте певні <b>позиції</b> в пакет і ведете облік запасів окремих <b>позицій</b>, а не агрегованої <b>позиції</b>.</p>\\n'
            '<p>Пакетна <b>позиція</b> матиме <code>Є складською позицією</code> зі значенням <b>Ні</b> та <code>Є товарною позицією</code> зі значенням <b>Так</b>.</p>\\n'
            '<h4>Приклад:</h4>\\n'
            '<p>Якщо ви продаєте ноутбуки та рюкзаки окремо і маєте спеціальну ціну при купівлі обох товарів разом, то \\"Ноутбук + Рюкзак\\" буде новою позицією комплекту продуктів.</p>'
        )
        print(f"  7. Fixed: About Product Bundle")
        break

# 8. Currency Exchange Settings Help
for e in po:
    if '<h3>Currency Exchange Settings Help</h3>' in e.msgid and not e.msgstr:
        e.msgstr = (
            '<h3>Довідка з налаштувань обміну валют</h3>\\n'
            '<p>Є 3 змінні, які можна використовувати в кінцевій точці, ключі результату та у значеннях параметра.</p>\\n'
            '<p>Курс обміну між {from_currency} та {to_currency} на {transaction_date} отримується через API.</p>\\n'
            '<p>Приклад: якщо ваша кінцева точка — exchange.com/2021-08-01, то вам потрібно ввести exchange.com/{transaction_date}</p>'
        )
        print(f"  8. Fixed: Currency Exchange Settings Help")
        break

# 9. Body Text and Closing Text Example (Dunning)
for e in po:
    if '<h4>Body Text and Closing Text Example</h4>' in e.msgid and not e.msgstr:
        e.msgstr = (
            '<h4>Приклад основного тексту та заключного тексту</h4>\\n\\n'
            '<div>Ми помітили, що ви ще не оплатили рахунок {{sales_invoice}} на суму {{frappe.db.get_value(\\"Currency\\", currency, \\"symbol\\")}} {{outstanding_amount}}. Це дружнє нагадування про те, що рахунок мав бути сплачений {{due_date}}. Будь ласка, сплатіть заборгованість негайно, щоб уникнути подальших витрат на нагадування.</div>\\n\\n'
            '<h4>Як отримати назви полів</h4>\\n\\n'
            '<p>Назви полів, які ви можете використовувати у своєму шаблоні, — це поля документа. Ви можете дізнатися поля будь-якого документа через Налаштування &gt; Налаштувати вигляд форми та вибрати тип документа (наприклад, Рахунок-фактура)</p>\\n\\n'
            '<h4>Шаблонізація</h4>\\n\\n'
            '<p>Шаблони компілюються за допомогою мови шаблонів Jinja. Щоб дізнатися більше про Jinja, <a class=\\"strong\\" href=\\"http://jinja.pocoo.org/docs/dev/templates/\\">прочитайте цю документацію.</a></p>'
        )
        print(f"  9. Fixed: Dunning Body Text")
        break

# 10. Contract Template Example
for e in po:
    if '<h4>Contract Template Example</h4>' in e.msgid and not e.msgstr:
        e.msgstr = (
            '<h4>Приклад шаблону договору</h4>\\n\\n'
            '<pre>Договір для клієнта {{ party_name }}\\n\\n'
            '- Дійсний з : {{ start_date }} \\n'
            '- Дійсний до : {{ end_date }}\\n'
            '</pre>\\n\\n'
            '<h4>Як отримати назви полів</h4>\\n\\n'
            '<p>Назви полів, які ви можете використовувати у вашому шаблоні договору, — це поля договору, для якого ви створюєте шаблон. Ви можете дізнатися поля будь-якого документа через Налаштування &gt; Налаштувати вигляд форми та вибрати тип документа (наприклад, Договір)</p>\\n\\n'
            '<h4>Шаблонізація</h4>\\n\\n'
            '<p>Шаблони компілюються за допомогою мови шаблонів Jinja. Щоб дізнатися більше про Jinja, <a class=\\"strong\\" href=\\"http://jinja.pocoo.org/docs/dev/templates/\\">прочитайте цю документацію.</a></p>'
        )
        print(f" 10. Fixed: Contract Template Example")
        break

# 11. Standard Terms and Conditions Example
for e in po:
    if '<h4>Standard Terms and Conditions Example</h4>' in e.msgid and not e.msgstr:
        e.msgstr = (
            '<h4>Приклад стандартних правил та умов</h4>\\n\\n'
            '<pre>Умови доставки для замовлення номер {{ name }}\\n\\n'
            '- Дата замовлення : {{ transaction_date }} \\n'
            '- Очікувана дата доставки : {{ delivery_date }}\\n'
            '</pre>\\n\\n'
            '<h4>Як отримати назви полів</h4>\\n\\n'
            '<p>Назви полів, які ви можете використовувати у шаблоні листа, — це поля документа, з якого ви надсилаєте лист. Ви можете дізнатися поля будь-якого документа через Налаштування &gt; Налаштувати вигляд форми та вибрати тип документа (наприклад, Рахунок-фактура)</p>\\n\\n'
            '<h4>Шаблонізація</h4>\\n\\n'
            '<p>Шаблони компілюються за допомогою мови шаблонів Jinja. Щоб дізнатися більше про Jinja, <a class=\\"strong\\" href=\\"http://jinja.pocoo.org/docs/dev/templates/\\">прочитайте цю документацію.</a></p>'
        )
        print(f" 11. Fixed: Standard Terms and Conditions")
        break

# 12-14. Label settings
label_translations = {
    'Account Number Settings': 'Налаштування номера рахунку',
    'Amount In Words': 'Сума прописом',
    'Date Settings': 'Налаштування дати',
}
count = 12
for e in po:
    for en_text, uk_text in label_translations.items():
        if en_text in e.msgid and 'control-label' in e.msgid and not e.msgstr:
            e.msgstr = e.msgid.replace(en_text, uk_text)
            print(f" {count}. Fixed: {en_text}")
            count += 1
            break

# 15. Email Template RFQ variables
for e in po:
    if 'In your <b>Email Template</b>, you can use the following special variables' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'In your <b>Email Template</b>, you can use the following special variables:',
            'У вашому <b>Шаблоні електронного листа</b> ви можете використовувати такі спеціальні змінні:'
        ).replace(
            'A link where your supplier can set a new password to log into your portal.',
            'Посилання, за яким ваш постачальник може встановити новий пароль для входу на ваш портал.'
        ).replace(
            'A link to this RFQ in your supplier portal.',
            'Посилання на цей запит пропозиції на вашому порталі постачальників.'
        ).replace(
            'The company name of your supplier.',
            'Назва компанії вашого постачальника.'
        ).replace(
            'The contact person of your supplier.',
            'Контактна особа вашого постачальника.'
        ).replace(
            'Your full name.',
            'Ваше повне ім\'я.'
        ).replace(
            'Apart from these, you can access all values in this RFQ, like',
            'Окрім цього, ви можете отримати доступ до всіх значень у цьому запиті пропозиції, наприклад'
        ).replace(
            ' or ', ' або '
        )
        print(f" 15. Fixed: Email Template RFQ")
        break

# 16. Payment Gateway Account message example
for e in po:
    if 'Thank You for being a part of {{ doc.company }}' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'Message Example', 'Приклад повідомлення'
        ).replace(
            'Thank You for being a part of', 'Дякуємо, що ви є частиною'
        ).replace(
            '! We hope you are enjoying the service.', '! Сподіваємося, вам подобається обслуговування.'
        ).replace(
            'Please find enclosed the E Bill statement. The outstanding amount is',
            'Додаємо виписку по рахунку. Непогашена сума становить'
        ).replace(
            "We don't want you to be spending time running around in order to pay for your Bill.",
            'Ми не хочемо, щоб ви витрачали час на біганину заради оплати рахунку.'
        ).replace(
            'After all, life is beautiful and the time you have in hand should be spent to enjoy it!',
            'Зрештою, життя прекрасне, і час, який у вас є, варто витрачати на насолоду ним!'
        ).replace(
            'So here are our little ways to help you get more time for life!',
            'Ось наші маленькі способи допомогти вам отримати більше часу для життя!'
        ).replace(
            'click here to pay', 'натисніть тут, щоб оплатити'
        )
        print(f" 16. Fixed: Payment Gateway message")
        break

# 17. Payment Request message example
for e in po:
    if 'Dear {{ doc.contact_person }}' in e.msgid and 'Requesting payment' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'Message Example', 'Приклад повідомлення'
        ).replace(
            'Dear', 'Шановний'
        ).replace(
            'Requesting payment for', 'Запит на оплату за'
        ).replace(
            ' for {{ doc.grand_total }}.', ' на суму {{ doc.grand_total }}.'
        ).replace(
            'click here to pay', 'натисніть тут, щоб оплатити'
        )
        print(f" 17. Fixed: Payment Request message")
        break

# 18-23. Span headers
span_translations = {
    'Masters &amp; Reports': 'Довідники та звіти',
    'Quick Access': 'Швидкий доступ',
    'Reports &amp; Masters': 'Звіти та довідники',
    'Subcontracting Inward and Outward': 'Внутрішній та зовнішній субпідряд',
}
count = 18
for e in po:
    for en_text, uk_text in span_translations.items():
        if en_text in e.msgid and 'span class' in e.msgid and not e.msgstr:
            e.msgstr = e.msgid.replace(en_text, uk_text)
            print(f" {count}. Fixed: {en_text}")
            count += 1
            break

# Your Shortcuts (2 variants)
for e in po:
    if 'Your Shortcuts' in e.msgid and 'span class' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace('Your Shortcuts', 'Ваші ярлики')
        print(f" {count}. Fixed: Your Shortcuts")
        count += 1

# 24. Inventory Dimension table
for e in po:
    if 'Child Document</th>' in e.msgid and 'Non Child Document' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'Child Document', 'Дочірній документ'
        ).replace(
            'Non Child Document', 'Недочірній документ'  # Note: Недочірній is one replacement
        ).replace(
            'To access parent document field use parent.fieldname and to access child table document field use doc.fieldname',
            'Для доступу до поля батьківського документа використовуйте parent.fieldname, а для доступу до поля документа дочірньої таблиці використовуйте doc.fieldname'
        ).replace(
            'To access document field use doc.fieldname',
            'Для доступу до поля документа використовуйте doc.fieldname'
        ).replace(
            '<b>Example: </b>', '<b>Приклад: </b>'
        )
        # Fix the "Non Дочірній документ" → "Недочірній документ"
        e.msgstr = e.msgstr.replace('Non Дочірній документ', 'Недочірній документ')
        print(f" 24. Fixed: Inventory Dimension table")
        break

# 25. If "Months" is selected
for e in po:
    if 'If "Months" is selected, a fixed amount' in e.msgid and not e.msgstr:
        e.msgstr = 'Якщо вибрано «Місяці», фіксована сума буде записана як відкладений дохід або витрата за кожен місяць незалежно від кількості днів у місяці. Вона буде пропорційно розподілена, якщо відкладений дохід або витрата не записані за повний місяць'
        print(f" 25. Fixed: If Months is selected")
        break

# 26. Advance Payment reconciliation
for e in po:
    if 'If <b>Enabled</b> - Reconciliation happens on the <b>Advance Payment posting date</b>' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'If <b>Enabled</b> - Reconciliation happens on the <b>Advance Payment posting date</b>',
            'Якщо <b>Увімкнено</b> — звірка відбувається на <b>дату проведення авансового платежу</b>'
        ).replace(
            'If <b>Disabled</b> - Reconciliation happens on oldest of 2 Dates: <b>Invoice Date</b> or the <b>Advance Payment posting date</b>',
            'Якщо <b>Вимкнено</b> — звірка відбувається за найранішою з 2 дат: <b>дата рахунку</b> або <b>дата проведення авансового платежу</b>'
        )
        print(f" 26. Fixed: Advance Payment reconciliation")
        break

# 27. Auto Serial / Batch Bundle
for e in po:
    if 'do not update serial / batch values in the stock transactions' in e.msgid and not e.msgstr:
        e.msgstr = 'Якщо увімкнено, не оновлювати значення серійних номерів / партій у складських операціях при створенні автоматичного пакету серійних номерів / партій. '
        print(f" 27. Fixed: Auto Serial / Batch Bundle")
        break

# 28. Qty to Order formula
for e in po:
    if 'formula for <b>Qty to Order</b>' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'If enabled, formula for <b>Qty to Order</b>:',
            'Якщо увімкнено, формула для <b>Кількості для замовлення</b>:'
        ).replace(
            'Projected Qty</a>.', 'Прогнозована кількість</a>.'
        ).replace(
            'This helps avoid over-ordering.', 'Це допомагає уникнути надмірного замовлення.'
        )
        print(f" 28. Fixed: Qty to Order formula")
        break

# 29. Required Qty formula
for e in po:
    if 'formula for <b>Required Qty</b>' in e.msgid and not e.msgstr:
        e.msgstr = e.msgid.replace(
            'If enabled, formula for <b>Required Qty</b>:',
            'Якщо увімкнено, формула для <b>Необхідної кількості</b>:'
        ).replace(
            'Projected Qty</a>.', 'Прогнозована кількість</a>.'
        ).replace(
            'This helps avoid over-ordering.', 'Це допомагає уникнути надмірного замовлення.'
        )
        print(f" 29. Fixed: Required Qty formula")
        break

# 30. Free Item
for e in po:
    if 'treated as "Free Item' in e.msgid and not e.msgstr:
        e.msgstr = 'Якщо ставка дорівнює нулю, товар буде вважатися «Безкоштовним товаром»'
        print(f" 30. Fixed: Free Item")
        break

# 31. Stock Ledgers won't be reposted
for e in po:
    if 'won\u2019t be reposted' in e.msgid and not e.msgstr:
        e.msgstr = 'Складські книги не будуть повторно опубліковані.'
        print(f" 31. Fixed: Stock Ledgers won't be reposted")
        break

# 32. Over Billing Allowance
for e in po:
    if 'Over Billing Allowance' in e.msgid and 'To allow over billing' in e.msgid and not e.msgstr:
        e.msgstr = 'Щоб дозволити перевищення оплати, оновіть «Допустиме перевищення оплати» в Налаштуваннях обліку або у Позиції.'
        print(f" 32. Fixed: Over Billing Allowance")
        break

# 33. Over Receipt/Delivery Allowance
for e in po:
    if 'Over Receipt/Delivery Allowance' in e.msgid and not e.msgstr:
        e.msgstr = 'Щоб дозволити перевищення приймання / доставки, оновіть «Допустиме перевищення приймання/доставки» у Налаштуваннях запасів або у Позиції.'
        print(f" 33. Fixed: Over Receipt/Delivery Allowance")
        break

po.save('erpnext/locale/uk.po')

# Final stats
translated = sum(1 for e in po if e.msgstr and not e.obsolete and not e.fuzzy)
total = sum(1 for e in po if not e.obsolete)
print(f"\nFinal stats: {translated}/{total} translated ({100*translated/total:.1f}%)")
