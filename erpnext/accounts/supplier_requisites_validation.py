import io
import re

import frappe
from frappe import _

from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
	get_supplier_invoice_files,
)

SUPPORTED_DOCTYPES = {"Purchase Invoice", "Payment Request", "Payment Entry"}
SUPPLIER_UPDATE_DOCTYPE = "Purchase Invoice"
MANUAL_CONFIRMATION_FIELD = "custom_supplier_requisites_manual_confirmation"
SUPPLIER_FIELD_BY_CHECK = {"tax_id": "tax_id", "edrpou": "edrpou"}
MANUAL_VERIFICATION_STATUSES = {"mismatched", "ambiguous", "unreadable", "missing_reference"}

CHECK_DEFINITIONS = {
	"tax_id": {
		"label": "Tax ID",
		"labels": (r"ІПН", r"ИПН", r"РНОКПП", r"ІНН", r"ИНН", r"податков(?:ий|ого)\s+номер"),
		"lengths": (10, 12),
	},
	"edrpou": {
		"label": "EDRPOU Code",
		"labels": (r"ЄДРПОУ", r"ЕДРПОУ", r"код\s+підприємства"),
		"lengths": (8,),
	},
	"iban": {"label": "IBAN"},
}


@frappe.whitelist()
def get_supplier_requisites_validation(doc):
	doc = frappe.get_doc(frappe.parse_json(doc))
	_check_document_permission(doc)
	return validate_supplier_requisites(doc)


@frappe.whitelist(methods=["POST"])
def update_supplier_requisites_from_pdf(doc, values):
	doc = frappe.get_doc(frappe.parse_json(doc))
	_check_document_permission(doc)
	if doc.doctype != SUPPLIER_UPDATE_DOCTYPE:
		frappe.throw(
			_("Supplier details can only be updated from a Purchase Invoice."),
			title=_("Supplier Details Verification"),
		)
	values = frappe.parse_json(values) or {}
	result = validate_supplier_requisites(doc)
	if not result["applicable"]:
		frappe.throw(_("Supplier details verification is not available for this document."))
	manual_entry = bool(frappe.utils.cint(values.get("manual_entry")))
	if manual_entry and not result.get("allow_manual_supplier_update"):
		frappe.throw(
			_(
				"Manual entry is only available for supplier details that are missing from both the supplier record and the PDF."
			),
			title=_("Supplier Details Verification"),
		)

	checks = {check["key"]: check for check in result["checks"]}
	supplier_doc = frappe.get_doc("Supplier", result["supplier"])
	supplier_doc.check_permission("write")
	updated = {}
	for key, fieldname in SUPPLIER_FIELD_BY_CHECK.items():
		selected = _digits(values.get(key))
		if not selected:
			continue
		_validate_requisite_format(key, selected)
		if checks.get(key, {}).get("status") == "not_applicable":
			frappe.throw(
				_(
					"EDRPOU Code cannot be updated because the supplier or the PDF indicates an individual entrepreneur."
				)
			)
		if manual_entry:
			_validate_manual_selection(checks.get(key))
		else:
			_validate_detected_selection(checks.get(key), selected)
		if supplier_doc.get(fieldname) and _digits(supplier_doc.get(fieldname)) != selected:
			frappe.throw(
				_(
					"{0} is already specified in the supplier record and cannot be replaced from the PDF."
				).format(_(CHECK_DEFINITIONS[key]["label"]))
			)
		supplier_doc.set(fieldname, selected)
		updated[key] = selected

	if "is_vat_payer" in values:
		supplier_doc.custom_is_vat_payer = frappe.utils.cint(values["is_vat_payer"])
		updated["is_vat_payer"] = supplier_doc.custom_is_vat_payer
	if updated:
		supplier_doc.save()

	bank_account = None
	iban = _normalize_iban(values.get("iban"))
	if iban:
		_validate_requisite_format("iban", iban)
		if manual_entry:
			_validate_manual_selection(checks.get("iban"))
		else:
			_validate_detected_selection(checks.get("iban"), iban)
		bank_account = _ensure_supplier_bank_account(supplier_doc, iban, values.get("bank"))
		updated["iban"] = iban

	return {"updated": updated, "bank_account": bank_account}


@frappe.whitelist()
def get_iban_bank_suggestion(doc, iban):
	doc = frappe.get_doc(frappe.parse_json(doc))
	_check_document_permission(doc)
	if doc.doctype != SUPPLIER_UPDATE_DOCTYPE:
		frappe.throw(_("Bank suggestions are only available from a Purchase Invoice."))
	iban = _normalize_iban(iban)
	_validate_requisite_format("iban", iban)
	return _get_iban_bank_suggestions([iban])[iban]


def validate_before_submit(doc, method=None):
	result = validate_supplier_requisites(doc)
	if not result["applicable"] or not result["requires_manual_confirmation"]:
		return
	if doc.get(MANUAL_CONFIRMATION_FIELD):
		return

	details = "<br>".join(
		frappe.utils.escape_html(check["message"])
		for check in result["checks"]
		if check["status"] != "matched"
	)
	frappe.throw(
		_("Supplier details in the invoice PDF require manual verification. {0}").format(
			f"<br>{details}" if details else ""
		),
		title=_("Supplier Details Verification"),
	)


def validate_supplier_requisites(doc):
	context = _get_validation_context(doc)
	if not context:
		return {
			"applicable": False,
			"checks": [],
			"files": [],
			"requires_manual_confirmation": False,
		}

	groups = _get_invoice_file_groups(doc, context)
	if not groups:
		return {
			"applicable": False,
			"checks": [],
			"files": [],
			"requires_manual_confirmation": False,
		}
	files = _flatten_invoice_files(groups, context["supplier"])
	file_texts = []
	read_errors = []
	for file in files:
		try:
			file_texts.append({**file, "text": _extract_pdf_text(file["file_url"])})
		except Exception:
			frappe.log_error(
				title="Supplier invoice requisites extraction failed",
				message=frappe.get_traceback(),
			)
			read_errors.append(file["file_url"])

	text = "\n".join(file["text"] for file in file_texts if file["text"].strip())
	expected = _get_expected_values(context)
	checks = [_compare_value(key, expected.get(key) or [], text) for key in ("tax_id", "edrpou", "iban")]
	_apply_supplier_type_rules(checks, context, expected, text)
	for check in checks:
		check["matched_files"] = _get_matching_files(
			check["key"], expected.get(check["key"]) or [], file_texts
		)

	if not files or not text:
		for check in checks:
			if check["status"] not in {"missing_reference", "not_applicable"}:
				check.update(
					status="unreadable",
					detected=[],
					message=_("{0}: could not be read from the PDF. Check manually.").format(
						_(check["label"])
					),
				)

	has_detected_requisites = any(check.get("detected") for check in checks)
	allow_manual_supplier_update = bool(
		doc.doctype == SUPPLIER_UPDATE_DOCTYPE
		and files
		and any(check["status"] == "missing_reference" and not check.get("detected") for check in checks)
	)
	return {
		"applicable": True,
		"supplier": context["supplier"],
		"allow_supplier_update": doc.doctype == SUPPLIER_UPDATE_DOCTYPE,
		"is_vat_payer": frappe.utils.cint(
			frappe.db.get_value("Supplier", context["supplier"], "custom_is_vat_payer")
		),
		"allow_manual_supplier_update": allow_manual_supplier_update,
		"files": files,
		"checks": checks,
		"has_detected_requisites": has_detected_requisites,
		"read_errors": read_errors,
		"iban_bank_suggestions": _get_iban_bank_suggestions(
			next((check["detected"] for check in checks if check["key"] == "iban"), [])
		),
		"requires_manual_confirmation": any(
			check["status"] in MANUAL_VERIFICATION_STATUSES for check in checks
		),
	}


def _apply_supplier_type_rules(checks, context, expected, text=""):
	if expected.get("edrpou"):
		return
	if context.get("supplier_type") != "Individual" and not _looks_like_individual_entrepreneur(text):
		return
	edrpou_check = next((check for check in checks if check["key"] == "edrpou"), None)
	if not edrpou_check:
		return
	edrpou_check.update(
		status="not_applicable",
		message=_(
			"EDRPOU Code: not applicable to an individual entrepreneur. Values found in the PDF may belong to the recipient or another party and will not be saved to the supplier record."
		),
	)


def _looks_like_individual_entrepreneur(text):
	patterns = (
		r"\bФОП\b",
		r"\bФЛП\b",
		r"\bСПД[\s\-–—]*ФО\b",
		r"фізичн\w*\s+особ\w*[\s\-–—]+підприєм\w*",
		r"физическ\w*\s+лиц\w*[\s\-–—]+предпринимател\w*",
	)
	return any(re.search(pattern, text or "", flags=re.IGNORECASE) for pattern in patterns)


def _get_matching_files(key, expected_values, file_texts):
	return [
		{"file_name": file.get("file_name"), "file_url": file.get("file_url")}
		for file in file_texts
		if _compare_value(key, expected_values, file["text"])["status"] in {"matched", "ambiguous"}
	]


def _validate_detected_selection(check, selected):
	if not check or selected not in check.get("detected", []):
		frappe.throw(
			_("The selected value was not found in the attached PDF. Refresh the document and try again.")
		)


def _validate_manual_selection(check):
	if not check or check.get("status") != "missing_reference" or check.get("detected"):
		frappe.throw(
			_("This supplier detail cannot be entered manually for the current PDF verification result.")
		)


def _validate_requisite_format(key, value):
	if key in SUPPLIER_FIELD_BY_CHECK:
		lengths = CHECK_DEFINITIONS[key]["lengths"]
		if len(value) in lengths:
			return
		frappe.throw(
			_("{0} must contain {1} digits.").format(
				_(CHECK_DEFINITIONS[key]["label"]),
				"/".join(str(length) for length in lengths),
			)
		)
	if key == "iban" and re.fullmatch(r"UA\d{27}", value):
		return
	frappe.throw(_("Enter a valid Ukrainian IBAN containing 29 characters."))


def _ensure_supplier_bank_account(supplier_doc, iban, bank):
	existing = frappe.get_all(
		"Bank Account",
		filters={"iban": iban, "disabled": 0},
		fields=["name", "party_type", "party"],
		limit=2,
	)
	for account in existing:
		if account.party_type == "Supplier" and account.party == supplier_doc.name:
			return account.name
	if existing:
		frappe.throw(_("IBAN {0} is already linked to another bank account.").format(frappe.bold(iban)))
	if not bank:
		frappe.throw(_("Select a bank before creating the supplier bank account."))
	bank_doc = frappe.get_doc("Bank", bank)
	bank_doc.check_permission("read")
	_sync_bank_code_from_iban(bank_doc, iban)
	frappe.has_permission("Bank Account", "create", throw=True)
	account_name = f"{supplier_doc.get('supplier_name') or supplier_doc.name} {iban[-4:]}"
	bank_account = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": account_name,
			"bank": bank,
			"party_type": "Supplier",
			"party": supplier_doc.name,
			"iban": iban,
			"is_company_account": 0,
			"is_default": int(
				not frappe.db.exists(
					"Bank Account",
					{
						"party_type": "Supplier",
						"party": supplier_doc.name,
						"disabled": 0,
					},
				)
			),
		}
	).insert()
	return bank_account.name


def _sync_bank_code_from_iban(bank_doc, iban):
	bank_code = _get_ukrainian_bank_code(iban)
	if not bank_code or not bank_doc.meta.has_field("custom_nbu_code"):
		return
	current_code = _digits(bank_doc.get("custom_nbu_code"))
	if current_code and current_code != bank_code:
		frappe.throw(
			_("The selected bank has NBU code {0}, but the IBAN contains code {1}.").format(
				frappe.bold(current_code), frappe.bold(bank_code)
			)
		)
	if not current_code:
		bank_doc.check_permission("write")
		bank_doc.custom_nbu_code = bank_code
		bank_doc.save()


def _get_iban_bank_suggestions(ibans):
	has_bank_code = frappe.get_meta("Bank").has_field("custom_nbu_code")
	suggestions = {}
	for iban in ibans:
		bank_code = _get_ukrainian_bank_code(iban)
		banks = (
			frappe.get_all("Bank", filters={"custom_nbu_code": bank_code}, pluck="name", limit=2)
			if bank_code and has_bank_code
			else []
		)
		suggestions[iban] = {
			"bank_code": bank_code,
			"bank": banks[0] if len(banks) == 1 else None,
		}
	return suggestions


def _check_document_permission(doc):
	if doc.is_new():
		frappe.has_permission(doc.doctype, "create", throw=True)
	else:
		doc.check_permission("read")


def _get_validation_context(doc):
	if doc.doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Supplier details verification is not supported for {0}.").format(doc.doctype))

	if doc.doctype == "Purchase Invoice":
		supplier = doc.get("supplier")
	elif doc.doctype == "Payment Request":
		supplier = doc.get("party") if doc.get("party_type") == "Supplier" else None
	else:
		supplier = (
			doc.get("party")
			if doc.get("party_type") == "Supplier" and doc.get("payment_type") == "Pay"
			else None
		)

	if not supplier:
		return None
	supplier_type = frappe.db.get_value("Supplier", supplier, "supplier_type")
	return {
		"supplier": supplier,
		"supplier_type": supplier_type,
		"bank_accounts": _get_expected_bank_accounts(doc, supplier),
	}


def _get_expected_bank_accounts(doc, supplier):
	selected_bank_account = None
	if doc.doctype == "Payment Request":
		selected_bank_account = doc.get("bank_account")
	elif doc.doctype == "Payment Entry":
		selected_bank_account = doc.get("party_bank_account")

	filters = {
		"party_type": "Supplier",
		"party": supplier,
		"is_company_account": 0,
		"disabled": 0,
	}
	if selected_bank_account:
		filters["name"] = selected_bank_account

	return frappe.get_all("Bank Account", filters=filters, fields=["name", "iban"])


def _get_invoice_file_groups(doc, context):
	if doc.doctype == "Purchase Invoice":
		return get_supplier_invoice_files(
			consolidated_order=doc.get("custom_consolidated_purchase_order"),
			supplier=context["supplier"],
		)
	if doc.doctype == "Payment Request":
		return get_supplier_invoice_files(
			references=[
				{
					"reference_doctype": doc.get("reference_doctype"),
					"reference_name": doc.get("reference_name"),
				}
			]
		)
	references = [
		row.as_dict() if hasattr(row, "as_dict") else dict(row) for row in (doc.get("references") or [])
	]
	return get_supplier_invoice_files(references=references)


def _flatten_invoice_files(groups, supplier):
	files = []
	seen_urls = set()
	for group in groups:
		if group.get("supplier") != supplier:
			continue
		for file in group.get("files", []):
			if file.get("file_url") in seen_urls:
				continue
			seen_urls.add(file.get("file_url"))
			files.append(file)
	return files


def _get_expected_values(context):
	supplier = frappe.db.get_value("Supplier", context["supplier"], ["tax_id", "edrpou"], as_dict=True) or {}
	return {
		"tax_id": [_digits(supplier.get("tax_id"))] if supplier.get("tax_id") else [],
		"edrpou": [_digits(supplier.get("edrpou"))] if supplier.get("edrpou") else [],
		"iban": [_normalize_iban(account.iban) for account in context["bank_accounts"] if account.iban],
	}


def _extract_pdf_text(file_url):
	try:
		import pdfplumber
	except ImportError:
		frappe.throw(
			_("PDF verification requires the 'pdfplumber' library to be installed."),
			title=_("Missing Dependency"),
		)

	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		raise frappe.DoesNotExistError(file_url)
	file_doc = frappe.get_doc("File", file_name)
	file_doc.check_permission("read")
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		return "\n".join((page.extract_text() or "") for page in pdf.pages[:50])


def _compare_value(key, expected_values, text):
	definition = CHECK_DEFINITIONS[key]
	label = definition["label"]
	expected_values = list(dict.fromkeys(value for value in expected_values if value))
	detected = _extract_detected_values(key, text, definition, expected_values)
	if not expected_values:
		return {
			"key": key,
			"label": label,
			"status": "missing_reference",
			"expected": [],
			"detected": detected,
			"message": (
				_(
					"{0}: not specified in the supplier record. Values found in PDF: {1}. Select the correct value or check manually."
				).format(_(label), ", ".join(detected))
				if detected
				else _("{0}: not specified in the supplier record. Check manually.").format(_(label))
			),
		}

	matches = set(expected_values) & set(detected)

	if matches:
		if len(detected) > 1:
			return {
				"key": key,
				"label": label,
				"status": "ambiguous",
				"expected": expected_values,
				"detected": detected,
				"matched": sorted(matches),
				"message": _(
					"{0}: multiple values were found in the PDF ({1}); {2} matches the supplier record. Check manually."
				).format(_(label), ", ".join(detected), ", ".join(sorted(matches))),
			}
		return {
			"key": key,
			"label": label,
			"status": "matched",
			"expected": expected_values,
			"detected": sorted(matches),
			"matched": sorted(matches),
			"message": _("{0}: matches the supplier record.").format(_(label)),
		}
	if detected:
		return {
			"key": key,
			"label": label,
			"status": "mismatched",
			"expected": expected_values,
			"detected": detected,
			"message": _("{0}: does not match the supplier record. Check manually.").format(_(label)),
		}
	return {
		"key": key,
		"label": label,
		"status": "unreadable",
		"expected": expected_values,
		"detected": [],
		"message": _("{0}: could not be read from the PDF. Check manually.").format(_(label)),
	}


def _extract_detected_values(key, text, definition, expected_values=()):
	if key == "iban":
		return _extract_ibans(text)
	detected = set(_extract_labeled_numbers(text, definition["labels"], definition["lengths"]))
	detected.update(value for value in expected_values if _number_occurs(text, value))
	return sorted(detected)


def _extract_ibans(text):
	return sorted(
		{
			_normalize_iban(match.group(0))
			for match in re.finditer(r"(?<![A-Z0-9])UA(?:[\s\-]*\d){27}(?!\d)", text.upper())
		}
	)


def _extract_labeled_numbers(text, labels, lengths):
	result = set()
	label_pattern = "|".join(labels)
	for length in lengths:
		pattern = rf"(?:{label_pattern})[^\d]{{0,30}}((?:\d[\s.\-/]*){{{length}}})(?!\d)"
		for match in re.finditer(pattern, text, flags=re.IGNORECASE):
			value = _digits(match.group(1))
			if len(value) == length:
				result.add(value)
	return sorted(result)


def _number_occurs(text, value):
	if not value:
		return False
	separator = r"[\s.\-/]*"
	pattern = r"(?<!\d)" + separator.join(re.escape(char) for char in value) + r"(?!\d)"
	return re.search(pattern, text) is not None


def _digits(value):
	return re.sub(r"\D", "", str(value or ""))


def _normalize_iban(value):
	return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _get_ukrainian_bank_code(iban):
	iban = _normalize_iban(iban)
	return iban[4:10] if re.fullmatch(r"UA\d{27}", iban) else None
