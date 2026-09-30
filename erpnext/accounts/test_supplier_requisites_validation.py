from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.supplier_requisites_validation import (
	_apply_supplier_type_rules,
	_compare_value,
	_extract_ibans,
	_get_invoice_file_groups,
	_get_ukrainian_bank_code,
	_looks_like_individual_entrepreneur,
	_sync_bank_code_from_iban,
	update_supplier_requisites_from_pdf,
	validate_before_submit,
	validate_supplier_requisites,
)


class TestSupplierRequisitesValidation(IntegrationTestCase):
	@patch("erpnext.accounts.supplier_requisites_validation.validate_supplier_requisites")
	@patch("erpnext.accounts.supplier_requisites_validation.frappe.get_doc")
	def test_detected_missing_tax_id_can_update_supplier(self, get_doc, validate):
		form_doc = MagicMock()
		form_doc.doctype = "Purchase Invoice"
		form_doc.is_new.return_value = False
		supplier_doc = MagicMock(name="SUPPLIER-A")
		supplier_doc.get.return_value = None
		get_doc.side_effect = [form_doc, supplier_doc]
		validate.return_value = {
			"applicable": True,
			"supplier": "SUPPLIER-A",
			"checks": [
				{"key": "tax_id", "detected": ["1234567890"]},
				{"key": "edrpou", "detected": []},
				{"key": "iban", "detected": []},
			],
		}

		result = update_supplier_requisites_from_pdf({}, {"tax_id": "1234567890"})

		form_doc.check_permission.assert_called_once_with("read")
		supplier_doc.check_permission.assert_called_once_with("write")
		supplier_doc.set.assert_called_once_with("tax_id", "1234567890")
		supplier_doc.save.assert_called_once_with()
		self.assertEqual(result["updated"], {"tax_id": "1234567890"})

	@patch("erpnext.accounts.supplier_requisites_validation.frappe.get_doc")
	def test_supplier_cannot_be_updated_from_payment_request(self, get_doc):
		form_doc = MagicMock()
		form_doc.doctype = "Payment Request"
		form_doc.is_new.return_value = False
		get_doc.return_value = form_doc

		with self.assertRaises(frappe.ValidationError):
			update_supplier_requisites_from_pdf({}, {"tax_id": "1234567890"})

	def test_formatted_supplier_details_match_pdf_text(self):
		text = "ІПН 123 456 789 0\nКод ЄДРПОУ: 12-34-56-78\nIBAN UA12 345678 901234 567890 1234567"

		tax_id = _compare_value("tax_id", ["1234567890"], text)
		edrpou = _compare_value("edrpou", ["12345678"], text)
		iban = _compare_value("iban", ["UA123456789012345678901234567"], text)

		self.assertEqual(tax_id["status"], "matched")
		self.assertEqual(edrpou["status"], "matched")
		self.assertEqual(iban["status"], "matched")

	def test_labeled_different_value_is_reported_as_mismatch(self):
		result = _compare_value("edrpou", ["12345678"], "ЄДРПОУ: 87654321")

		self.assertEqual(result["status"], "mismatched")
		self.assertEqual(result["detected"], ["87654321"])

	def test_multiple_tax_ids_require_manual_verification_even_when_one_matches(self):
		result = _compare_value(
			"tax_id",
			["1234567890"],
			"ІПН 1234567890\nІПН 9999999999",
		)

		self.assertEqual(result["status"], "ambiguous")
		self.assertEqual(result["detected"], ["1234567890", "9999999999"])
		self.assertEqual(result["matched"], ["1234567890"])

	def test_missing_supplier_value_keeps_pdf_candidates(self):
		result = _compare_value("edrpou", [], "ЄДРПОУ 12345678\nЄДРПОУ 87654321")

		self.assertEqual(result["status"], "missing_reference")
		self.assertEqual(result["detected"], ["12345678", "87654321"])

	def test_edrpou_found_for_individual_supplier_is_not_applicable(self):
		checks = [_compare_value("edrpou", [], "ЄДРПОУ 12345678")]

		_apply_supplier_type_rules(
			checks,
			{"supplier_type": "Individual"},
			{"edrpou": []},
		)

		self.assertEqual(checks[0]["status"], "not_applicable")
		self.assertEqual(checks[0]["detected"], ["12345678"])

	def test_edrpou_found_in_fop_invoice_is_not_applicable(self):
		checks = [_compare_value("edrpou", [], "ФОП Іваненко Іван\nЄДРПОУ 12345678")]

		_apply_supplier_type_rules(
			checks,
			{"supplier_type": "Company"},
			{"edrpou": []},
			"ФОП Іваненко Іван\nЄДРПОУ 12345678",
		)

		self.assertEqual(checks[0]["status"], "not_applicable")

	def test_individual_entrepreneur_markers_are_detected(self):
		self.assertTrue(_looks_like_individual_entrepreneur("ФОП Петренко"))
		self.assertTrue(_looks_like_individual_entrepreneur("Фізична особа-підприємець Петренко"))
		self.assertFalse(_looks_like_individual_entrepreneur("ТОВ Петренко"))

	def test_ukrainian_iban_is_normalized(self):
		self.assertEqual(
			_extract_ibans("Рахунок: UA12 345678 901234 567890 1234567"),
			["UA123456789012345678901234567"],
		)

	def test_ukrainian_bank_code_is_read_from_iban(self):
		self.assertEqual(_get_ukrainian_bank_code("UA12 345678 901234 567890 1234567"), "345678")
		self.assertIsNone(_get_ukrainian_bank_code("DE89370400440532013000"))

	def test_selected_bank_learns_missing_nbu_code(self):
		bank = MagicMock()
		bank.meta.has_field.return_value = True
		bank.get.return_value = None

		_sync_bank_code_from_iban(bank, "UA12 345678 901234 567890 1234567")

		bank.check_permission.assert_called_once_with("write")
		self.assertEqual(bank.custom_nbu_code, "345678")
		bank.save.assert_called_once_with()

	def test_selected_bank_with_different_nbu_code_is_rejected(self):
		bank = MagicMock()
		bank.meta.has_field.return_value = True
		bank.get.return_value = "111111"

		with self.assertRaises(frappe.ValidationError):
			_sync_bank_code_from_iban(bank, "UA12 345678 901234 567890 1234567")

	@patch("erpnext.accounts.supplier_requisites_validation.get_supplier_invoice_files")
	def test_payment_entry_references_are_converted_to_dictionaries(self, get_files):
		get_files.return_value = []
		reference = MagicMock()
		reference.as_dict.return_value = {
			"reference_doctype": "Purchase Invoice",
			"reference_name": "ACC-PINV-TEST",
			"payment_request": "ACC-PRQ-TEST",
		}
		doc = frappe._dict(doctype="Payment Entry", references=[reference])

		_get_invoice_file_groups(doc, {"supplier": "SUPPLIER-A"})

		get_files.assert_called_once_with(
			references=[
				{
					"reference_doctype": "Purchase Invoice",
					"reference_name": "ACC-PINV-TEST",
					"payment_request": "ACC-PRQ-TEST",
				}
			]
		)

	@patch("erpnext.accounts.supplier_requisites_validation._get_expected_values")
	@patch("erpnext.accounts.supplier_requisites_validation._extract_pdf_text")
	@patch("erpnext.accounts.supplier_requisites_validation._get_invoice_file_groups")
	@patch("erpnext.accounts.supplier_requisites_validation._get_validation_context")
	def test_all_three_details_match(self, get_context, get_file_groups, extract_text, get_expected_values):
		get_context.return_value = {"supplier": "SUPPLIER-A", "bank_accounts": []}
		get_file_groups.return_value = [
			{
				"supplier": "SUPPLIER-A",
				"files": [{"file_name": "invoice.pdf", "file_url": "/files/invoice.pdf"}],
			}
		]
		extract_text.return_value = "ІПН 1234567890 ЄДРПОУ 12345678 IBAN UA123456789012345678901234567"
		get_expected_values.return_value = {
			"tax_id": ["1234567890"],
			"edrpou": ["12345678"],
			"iban": ["UA123456789012345678901234567"],
		}

		result = validate_supplier_requisites(frappe._dict(doctype="Purchase Invoice"))

		self.assertFalse(result["requires_manual_confirmation"])
		self.assertTrue(result["allow_supplier_update"])
		self.assertTrue(result["has_detected_requisites"])
		self.assertEqual([check["status"] for check in result["checks"]], ["matched"] * 3)

	@patch("erpnext.accounts.supplier_requisites_validation._get_expected_values")
	@patch("erpnext.accounts.supplier_requisites_validation._extract_pdf_text")
	@patch("erpnext.accounts.supplier_requisites_validation._get_invoice_file_groups")
	@patch("erpnext.accounts.supplier_requisites_validation._get_validation_context")
	def test_irrelevant_pdf_has_no_detected_requisites(
		self, get_context, get_file_groups, extract_text, get_expected_values
	):
		get_context.return_value = {
			"supplier": "SUPPLIER-A",
			"supplier_type": "Company",
			"bank_accounts": [],
		}
		get_file_groups.return_value = [
			{
				"supplier": "SUPPLIER-A",
				"files": [{"file_name": "other.pdf", "file_url": "/files/other.pdf"}],
			}
		]
		extract_text.return_value = "Документ без реквізитів постачальника"
		get_expected_values.return_value = {
			"tax_id": ["1234567890"],
			"edrpou": ["12345678"],
			"iban": ["UA123456789012345678901234567"],
		}

		result = validate_supplier_requisites(frappe._dict(doctype="Purchase Invoice"))

		self.assertFalse(result["has_detected_requisites"])
		self.assertTrue(result["requires_manual_confirmation"])

	@patch("erpnext.accounts.supplier_requisites_validation._get_expected_values")
	@patch("erpnext.accounts.supplier_requisites_validation._extract_pdf_text")
	@patch("erpnext.accounts.supplier_requisites_validation._get_invoice_file_groups")
	@patch("erpnext.accounts.supplier_requisites_validation._get_validation_context")
	def test_matching_file_and_ambiguity_are_reported_when_supplier_has_multiple_pdfs(
		self, get_context, get_file_groups, extract_text, get_expected_values
	):
		get_context.return_value = {"supplier": "SUPPLIER-A", "bank_accounts": []}
		get_file_groups.return_value = [
			{
				"supplier": "SUPPLIER-A",
				"files": [
					{"file_name": "wrong.pdf", "file_url": "/files/wrong.pdf"},
					{"file_name": "matching.pdf", "file_url": "/files/matching.pdf"},
				],
			}
		]
		extract_text.side_effect = [
			"ІПН 9999999999 ЄДРПОУ 99999999 IBAN UA999999999999999999999999999",
			"ІПН 1234567890 ЄДРПОУ 12345678 IBAN UA123456789012345678901234567",
		]
		get_expected_values.return_value = {
			"tax_id": ["1234567890"],
			"edrpou": ["12345678"],
			"iban": ["UA123456789012345678901234567"],
		}

		result = validate_supplier_requisites(frappe._dict(doctype="Purchase Invoice"))

		self.assertTrue(result["requires_manual_confirmation"])
		for check in result["checks"]:
			self.assertEqual(check["status"], "ambiguous")
			self.assertEqual(
				check["matched_files"],
				[{"file_name": "matching.pdf", "file_url": "/files/matching.pdf"}],
			)

	@patch("erpnext.accounts.supplier_requisites_validation.validate_supplier_requisites")
	def test_submit_requires_manual_confirmation_for_an_issue(self, validate):
		validate.return_value = {
			"applicable": True,
			"requires_manual_confirmation": True,
			"checks": [
				{
					"status": "mismatched",
					"message": "IBAN does not match",
				}
			],
		}
		doc = frappe._dict(custom_supplier_requisites_manual_confirmation=0)

		with self.assertRaises(frappe.ValidationError):
			validate_before_submit(doc)

		doc.custom_supplier_requisites_manual_confirmation = 1
		validate_before_submit(doc)
