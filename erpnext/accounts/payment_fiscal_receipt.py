from urllib.parse import urlsplit

import frappe

from frappe import _


PAYMENT_ENTRY_DOCTYPE = "Payment Entry"
PAYMENT_REQUEST_DOCTYPE = "Payment Request"
RECEIPT_FIELD = "custom_fiscal_receipt"
RECEIPT_STATUS_FIELD = "custom_fiscal_receipt_status"
RECEIPT_ADDED = "Додано"
RECEIPT_MISSING = "Відсутній"
RECEIPT_PARTIAL = "Частково"
ALLOWED_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
CLIENT_SCRIPT_NAME = "Payments: попередження про відсутній фіскальний чек"
LIST_CLIENT_SCRIPT_NAME = "Payments: колір статусу фіскального чека"
PAYMENT_REQUEST_LIST_CLIENT_SCRIPT_NAME = "Payments: статус фіскального чека у запитах"

CLIENT_SCRIPT = r'''
frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		if (frm.__payments_receipt_submit_warning_installed) {
			return;
		}

		const standardSubmit = frm.savesubmit.bind(frm);
		frm.savesubmit = function (btn, callback, onError) {
			if (frm.doc.custom_fiscal_receipt) {
				return standardSubmit(btn, callback, onError);
			}

			const standardConfirm = frappe.confirm;
			frappe.confirm = function (message, ifYes, ifNo) {
				frappe.confirm = standardConfirm;
				const warning = `
					<div class="alert alert-warning mt-3 mb-0" role="alert">
						<div class="flex align-start">
							<div class="mr-2" style="font-size: 1.25rem; line-height: 1;">&#9888;</div>
							<div>
								<strong>Фіскальний чек не додано</strong><br>
								<span class="text-muted">Оплату можна провести без чека та додати його пізніше.</span>
							</div>
						</div>
					</div>`;
				return standardConfirm(`${message}${warning}`, ifYes, ifNo);
			};

			try {
				return standardSubmit(btn, callback, onError);
			} finally {
				frappe.confirm = standardConfirm;
			}
		};
		frm.__payments_receipt_submit_warning_installed = true;
	},
});
'''.strip()

LIST_CLIENT_SCRIPT = r'''
const paymentEntryListSettings = frappe.listview_settings["Payment Entry"] || {};
paymentEntryListSettings.formatters = paymentEntryListSettings.formatters || {};
paymentEntryListSettings.formatters.custom_fiscal_receipt_status = function (value) {
	const receiptStatus = value || "Відсутній";
	const colour = receiptStatus === "Додано" ? "green" : "gray";
	const escapedStatus = frappe.utils.escape_html(receiptStatus);
	return `
		<span class="filterable indicator-pill ${colour} ellipsis"
			data-filter="custom_fiscal_receipt_status,=,${escapedStatus}">
			<span class="ellipsis">${__(receiptStatus)}</span>
		</span>`;
};
frappe.listview_settings["Payment Entry"] = paymentEntryListSettings;
'''.strip()

PAYMENT_REQUEST_LIST_CLIENT_SCRIPT = r'''
const paymentRequestListSettings = frappe.listview_settings["Payment Request"] || {};
paymentRequestListSettings.formatters = paymentRequestListSettings.formatters || {};
paymentRequestListSettings.formatters.custom_fiscal_receipt_status = function (value) {
	const receiptStatus = value || "Відсутній";
	const colour = receiptStatus === "Додано" ? "green" : receiptStatus === "Частково" ? "orange" : "gray";
	const escapedStatus = frappe.utils.escape_html(receiptStatus);
	return `
		<span class="filterable indicator-pill ${colour} ellipsis"
			data-filter="custom_fiscal_receipt_status,=,${escapedStatus}">
			<span class="ellipsis">${__(receiptStatus)}</span>
		</span>`;
};
frappe.listview_settings["Payment Request"] = paymentRequestListSettings;
'''.strip()


def validate_payment_entry_receipt(doc, method=None):
	"""Validate the dedicated receipt and keep the Payment Entry list status current."""
	file_url = (doc.get(RECEIPT_FIELD) or "").strip()
	if file_url:
		_validate_file_extension(file_url)
		_validate_private_file(file_url)

	doc.set(RECEIPT_STATUS_FIELD, RECEIPT_ADDED if file_url else RECEIPT_MISSING)


def sync_payment_entry_receipt(doc, method=None):
	"""Aggregate receipt availability onto all linked standard Payment Requests."""
	for payment_request in _get_linked_payment_requests(doc.name):
		_update_payment_request_receipt_status(payment_request)


def sync_existing_fiscal_receipt_statuses():
	"""Backfill list indicators after install or migrate without changing accounting data."""
	if not frappe.db.has_column("Payment Entry", RECEIPT_FIELD):
		return

	for row in frappe.get_all(
		PAYMENT_ENTRY_DOCTYPE,
		fields=["name", RECEIPT_FIELD],
	):
		status = RECEIPT_ADDED if row.get(RECEIPT_FIELD) else RECEIPT_MISSING
		frappe.db.set_value(
			PAYMENT_ENTRY_DOCTYPE,
			row.name,
			RECEIPT_STATUS_FIELD,
			status,
			update_modified=False,
		)

	for payment_request in frappe.get_all(PAYMENT_REQUEST_DOCTYPE, pluck="name"):
		_update_payment_request_receipt_status(payment_request)

	frappe.clear_cache(doctype=PAYMENT_ENTRY_DOCTYPE)
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


def sync_fiscal_receipt_configuration():
	"""Install the form warning and backfill receipt indicators."""
	_ensure_client_scripts()
	sync_existing_fiscal_receipt_statuses()


def _get_linked_payment_requests(payment_entry):
	return set(
		frappe.get_all(
			"Payment Entry Reference",
			filters={
				"parent": payment_entry,
				"parenttype": PAYMENT_ENTRY_DOCTYPE,
				"payment_request": ["is", "set"],
			},
			pluck="payment_request",
		)
	)


def _update_payment_request_receipt_status(payment_request):
	payment_request_status = frappe.db.get_value(
		PAYMENT_REQUEST_DOCTYPE,
		payment_request,
		"status",
	)
	if payment_request_status != "Paid":
		status = ""
	else:
		payment_entries = set(
			frappe.get_all(
				"Payment Entry Reference",
				filters={
					"payment_request": payment_request,
					"parenttype": PAYMENT_ENTRY_DOCTYPE,
					"docstatus": 1,
				},
				pluck="parent",
			)
		)
		receipt_count = (
			frappe.db.count(
				PAYMENT_ENTRY_DOCTYPE,
				{
					"name": ["in", payment_entries],
					"docstatus": 1,
					RECEIPT_FIELD: ["is", "set"],
				},
			)
			if payment_entries
			else 0
		)
		if not receipt_count:
			status = RECEIPT_MISSING
		elif receipt_count == len(payment_entries):
			status = RECEIPT_ADDED
		else:
			status = RECEIPT_PARTIAL

	frappe.db.set_value(
		PAYMENT_REQUEST_DOCTYPE,
		payment_request,
		RECEIPT_STATUS_FIELD,
		status,
		update_modified=False,
	)


def _validate_file_extension(file_url):
	path = urlsplit(file_url).path.lower()
	extension = next((suffix for suffix in ALLOWED_RECEIPT_EXTENSIONS if path.endswith(suffix)), None)
	if extension:
		return

	frappe.throw(
		_("Фіскальний чек має бути файлом PDF, JPG, JPEG або PNG."),
		title=_("Непідтримуваний формат файла"),
	)


def _validate_private_file(file_url):
	file_record = frappe.db.get_value(
		"File",
		{"file_url": file_url},
		["name", "is_private"],
		as_dict=True,
	)
	if not file_record:
		frappe.throw(_("Не вдалося знайти завантажений фіскальний чек."))
	if not file_record.is_private:
		frappe.throw(
			_("Фіскальний чек має бути завантажений як приватний файл."),
			title=_("Потрібен приватний файл"),
		)


def _ensure_client_scripts():
	_upsert_client_script(CLIENT_SCRIPT_NAME, "Form", CLIENT_SCRIPT)
	_upsert_client_script(LIST_CLIENT_SCRIPT_NAME, "List", LIST_CLIENT_SCRIPT)
	_upsert_client_script(
		PAYMENT_REQUEST_LIST_CLIENT_SCRIPT_NAME,
		"List",
		PAYMENT_REQUEST_LIST_CLIENT_SCRIPT,
		PAYMENT_REQUEST_DOCTYPE,
	)


def _upsert_client_script(name, view, script, doctype=PAYMENT_ENTRY_DOCTYPE):
	if frappe.db.exists("Client Script", name):
		doc = frappe.get_doc("Client Script", name)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = name

	doc.dt = doctype
	doc.view = view
	doc.enabled = 1
	doc.script = script
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
