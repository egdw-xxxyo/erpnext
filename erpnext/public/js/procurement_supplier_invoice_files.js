const supplierInvoiceFilesField = "custom_supplier_invoice_files_html";
const purchaseInvoiceSupplierSection = "supplier_invoice_details";
const supplierInvoiceFilesMethod =
	"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_supplier_invoice_files";
const supplierRequisitesValidationMethod =
	"erpnext.accounts.supplier_requisites_validation.get_supplier_requisites_validation";
const updateSupplierRequisitesMethod =
	"erpnext.accounts.supplier_requisites_validation.update_supplier_requisites_from_pdf";
const ibanBankSuggestionMethod = "erpnext.accounts.supplier_requisites_validation.get_iban_bank_suggestion";
const supplierRequisitesValidationField = "custom_supplier_requisites_validation_html";
const supplierRequisitesValidationSection = "custom_supplier_requisites_validation_section";
const supplierRequisitesManualConfirmation = "custom_supplier_requisites_manual_confirmation";
const supplierRequisiteFields = {
	"Purchase Invoice": { tax_id: "tax_id", edrpou: "edrpou" },
	"Payment Request": { iban: "iban" },
	"Payment Entry": {
		tax_id: "custom_party_tax_id",
		edrpou: "custom_party_edrpou",
		iban: "custom_party_iban",
	},
};

frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		configure_supplier_requisites_layout(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
	supplier(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
	custom_consolidated_purchase_order(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
});

frappe.ui.form.on("Payment Request", {
	refresh(frm) {
		configure_supplier_requisites_layout(frm);
		render_supplier_requisites_validation(frm);
	},
	party_type(frm) {
		reset_and_render_supplier_requisites_validation(frm);
	},
	party(frm) {
		reset_and_render_supplier_requisites_validation(frm);
	},
	reference_doctype(frm) {
		reset_and_render_supplier_requisites_validation(frm);
	},
	reference_name(frm) {
		reset_and_render_supplier_requisites_validation(frm);
	},
	bank_account(frm) {
		reset_and_render_supplier_requisites_validation(frm);
	},
});

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		configure_supplier_requisites_layout(frm);
		render_supplier_invoice_files(frm);
		render_supplier_payment_details(frm);
		render_supplier_requisites_validation(frm);
	},
	party_type(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_payment_details(frm);
		render_supplier_requisites_validation(frm);
	},
	party(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_payment_details(frm);
		render_supplier_requisites_validation(frm);
	},
	party_bank_account(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_payment_details(frm);
		render_supplier_requisites_validation(frm);
	},
});

frappe.ui.form.on("Payment Entry Reference", {
	reference_doctype(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
	reference_name(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
	payment_request(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
	references_remove(frm) {
		reset_supplier_requisites_confirmation(frm);
		render_supplier_invoice_files(frm);
		render_supplier_requisites_validation(frm);
	},
});

function reset_and_render_supplier_requisites_validation(frm) {
	reset_supplier_requisites_confirmation(frm);
	render_supplier_requisites_validation(frm);
}

function reset_supplier_requisites_confirmation(frm) {
	if (frm.doc[supplierRequisitesManualConfirmation]) {
		frm.set_value(supplierRequisitesManualConfirmation, 0);
	}
}

function configure_supplier_requisites_layout(frm) {
	frm.page.wrapper.css("--page-max-width", "1280px");
	ensure_supplier_requisites_styles();
	setTimeout(() => place_supplier_requisites_validation_last(frm), 0);
}

function place_supplier_requisites_validation_last(frm) {
	const section = frm.fields_dict[supplierRequisitesValidationSection];
	if (!section?.wrapper?.length) return;
	section.wrapper.parent().append(section.wrapper);
}

function ensure_supplier_requisites_styles() {
	if (document.getElementById("supplier-requisites-validation-styles")) return;
	$(
		`<style id="supplier-requisites-validation-styles">
			.supplier-requisites-summary{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;margin-bottom:14px;border:1px solid var(--border-color);border-left-width:4px;border-radius:8px;font-weight:500}
			.supplier-requisites-summary.success{border-left-color:var(--green-500);background:var(--green-50);color:var(--green-700)}
			.supplier-requisites-summary.warning{border-left-color:var(--orange-500);background:var(--orange-50);color:var(--orange-700)}
			.supplier-requisites-summary.danger{border-left-color:var(--red-500);background:var(--red-50);color:var(--red-700)}
			.supplier-requisites-note{display:flex;gap:7px;align-items:flex-start;padding:7px 9px;border-radius:6px;font-weight:500;line-height:1.35}
			.supplier-requisites-note.matched{background:var(--green-50);color:var(--green-700)}
			.supplier-requisites-note.mismatched{background:var(--red-50);color:var(--red-700)}
			.supplier-requisites-note.ambiguous{background:var(--yellow-50);color:var(--yellow-700)}
			.supplier-requisites-note.unreadable{background:var(--yellow-50);color:var(--yellow-700)}
			.supplier-requisites-note.missing_reference{background:var(--orange-50);color:var(--orange-700)}
			.supplier-requisites-note.not_applicable{background:var(--blue-50);color:var(--blue-700)}
			.supplier-requisites-result-cell{min-width:150px;white-space:nowrap}
			.supplier-requisites-result-cell .indicator-pill{display:inline-flex;align-items:center;white-space:nowrap}
			.supplier-requisite-indicator{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;margin-left:6px;padding:0;border:0;border-radius:50%;background:transparent;vertical-align:middle;cursor:pointer}
			.supplier-requisite-indicator.matched{color:var(--green-600);background:var(--green-50)}
			.supplier-requisite-indicator.mismatched{color:var(--red-600);background:var(--red-50)}
			.supplier-requisite-indicator.ambiguous{color:var(--yellow-700);background:var(--yellow-50)}
			.supplier-requisite-indicator.unreadable{color:var(--yellow-700);background:var(--yellow-50)}
			.supplier-requisite-indicator.missing_reference{color:var(--orange-600);background:var(--orange-50)}
			.supplier-requisite-indicator.not_applicable{color:var(--blue-600);background:var(--blue-50)}
			.supplier-requisites-row-focus{animation:supplier-requisites-row-focus 1.6s ease}
			@keyframes supplier-requisites-row-focus{0%,100%{box-shadow:none}25%,75%{box-shadow:inset 0 0 0 2px var(--blue-400)}}
			@media(max-width:767px){.supplier-requisites-validation-table{min-width:760px}}
		</style>`
	).appendTo(document.head);
}

function render_supplier_requisites_validation(frm) {
	const field = frm.get_field(supplierRequisitesValidationField);
	if (!field) return;

	const requestId = (frm.__supplier_requisites_validation_request_id || 0) + 1;
	frm.__supplier_requisites_validation_request_id = requestId;
	field.$wrapper.html(`<div class="text-muted">${__("Checking supplier details...")}</div>`);

	frappe.call({
		method: supplierRequisitesValidationMethod,
		args: { doc: frm.doc },
		callback(response) {
			if (frm.__supplier_requisites_validation_request_id !== requestId) return;
			const result = response.message || {};
			set_supplier_requisites_visibility(frm, result);
			field.$wrapper.html(build_supplier_requisites_validation_html(result, frm.doc.docstatus === 0));
			place_supplier_requisites_validation_last(frm);
			render_supplier_requisite_field_indicators(frm, result);
			bind_supplier_requisites_actions(frm, result);
			maybe_show_manual_supplier_requisites_dialog(frm, result);
		},
		error() {
			if (frm.__supplier_requisites_validation_request_id !== requestId) return;
			field.$wrapper.html(
				`<div class="text-muted">${__("Supplier details could not be checked.")}</div>`
			);
			clear_supplier_requisite_field_indicators(frm);
		},
	});
}

function set_supplier_requisites_visibility(frm, result) {
	const applicable = Boolean(result.applicable);
	frm.set_df_property(supplierRequisitesValidationSection, "hidden", applicable ? 0 : 1);
	frm.set_df_property(supplierRequisitesValidationField, "hidden", applicable ? 0 : 1);
	frm.set_df_property(
		supplierRequisitesManualConfirmation,
		"hidden",
		applicable && result.requires_manual_confirmation && frm.doc.docstatus === 0 ? 0 : 1
	);
}

function build_supplier_requisites_validation_html(result, allowSupplierUpdate) {
	if (!result.applicable) return "";
	const showChecksTable = Boolean(
		result.has_detected_requisites ?? (result.checks || []).some((check) => (check.detected || []).length)
	);
	const summary = get_supplier_requisites_summary(result.checks || []);
	const summaryHtml = `<div class="supplier-requisites-summary ${summary.level}">
		<i class="fa ${summary.icon}" aria-hidden="true"></i>
		<span>${summary.message}</span>
	</div>`;
	const fileLinks = build_supplier_pdf_links(result.files || []);
	const detectedChecks = get_supplier_requisites_update_checks(result, false);
	const canUpdateSupplier =
		allowSupplierUpdate && result.allow_supplier_update && detectedChecks.length > 0;
	const canEnterSupplierManually = allowSupplierUpdate && result.allow_manual_supplier_update;
	const actionsHtml = [
		canUpdateSupplier
			? `<button type="button" class="btn btn-default btn-sm supplier-requisites-update-supplier">
				${__("Update supplier details from PDF")}
			</button>`
			: "",
		canEnterSupplierManually
			? `<button type="button" class="btn btn-primary btn-sm supplier-requisites-enter-manually">
				${__("Enter supplier details manually")}
			</button>`
			: "",
	]
		.filter(Boolean)
		.join(" ");
	const filesHtml = fileLinks
		? `<div class="mb-3"><strong>${__("Checked PDF")}:</strong> ${fileLinks}</div>`
		: `<div class="text-muted mb-3">${__("No supplier invoice PDF was found.")}</div>`;
	if (!showChecksTable) {
		return `${summaryHtml}${filesHtml}${actionsHtml ? `<div class="mt-3">${actionsHtml}</div>` : ""}`;
	}

	const rows = (result.checks || [])
		.map((check) => {
			const status = get_supplier_requisites_status(check.status);
			const expected = (check.expected || []).join(", ") || "—";
			const detected = (check.detected || []).join(", ") || "—";
			return `<tr id="supplier-requisites-check-${frappe.utils.escape_html(
				check.key
			)}" data-requisite-key="${frappe.utils.escape_html(check.key)}">
				<td>${frappe.utils.escape_html(__(check.label))}</td>
				<td class="supplier-requisites-result-cell"><span class="indicator-pill ${
					status.color
				}"><span class="indicator-dot"></span>${status.label}</span></td>
				<td>${frappe.utils.escape_html(expected)}</td>
				<td>${frappe.utils.escape_html(detected)}</td>
				<td>${build_supplier_requisites_note(check, (result.files || []).length > 1)}</td>
			</tr>`;
		})
		.join("");

	return `
		${summaryHtml}
		${filesHtml}
		<div class="table-responsive">
			<table class="table table-bordered table-sm supplier-requisites-validation-table">
				<thead><tr>
					<th>${__("Detail")}</th><th class="supplier-requisites-result-cell">${__("Result")}</th><th>${__(
		"Supplier record"
	)}</th>
					<th>${__("PDF value")}</th><th>${__("Comment")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
		${actionsHtml ? `<div class="mt-3">${actionsHtml}</div>` : ""}`;
}

function bind_supplier_requisites_actions(frm, result) {
	const wrapper = frm.get_field(supplierRequisitesValidationField)?.$wrapper;
	wrapper
		?.find(".supplier-requisites-update-supplier")
		.off("click.supplier-requisites")
		.on("click.supplier-requisites", () =>
			show_supplier_requisites_update_dialog(frm, result, { manualEntry: false })
		);
	wrapper
		?.find(".supplier-requisites-enter-manually")
		.off("click.supplier-requisites")
		.on("click.supplier-requisites", () =>
			show_supplier_requisites_update_dialog(frm, result, { manualEntry: true })
		);
}

function get_supplier_requisites_update_checks(result, manualEntry) {
	return (result.checks || [])
		.map((check) => {
			if (manualEntry) {
				return check.status === "missing_reference" && !(check.detected || []).length
					? { ...check, selectable_values: [] }
					: null;
			}
			const existing = new Set(check.expected || []);
			const selectableValues = (check.detected || []).filter((value) => !existing.has(value));
			const canFillMissing = check.status === "missing_reference" && selectableValues.length;
			const canAddIban =
				check.key === "iban" &&
				["mismatched", "ambiguous"].includes(check.status) &&
				selectableValues.length;
			return canFillMissing || canAddIban ? { ...check, selectable_values: selectableValues } : null;
		})
		.filter(Boolean);
}

function build_supplier_pdf_links(files) {
	return files
		.map(
			(file) =>
				`<a href="${frappe.utils.escape_html(
					file.file_url || ""
				)}" target="_blank" rel="noopener noreferrer">${frappe.utils.escape_html(
					file.file_name || __("Supplier Invoice PDF")
				)}</a>`
		)
		.join(", ");
}

function maybe_show_manual_supplier_requisites_dialog(frm, result) {
	if (
		frm.doctype !== "Purchase Invoice" ||
		frm.doc.docstatus !== 0 ||
		!result.allow_manual_supplier_update
	) {
		return;
	}
	const dialogKey = JSON.stringify({
		supplier: result.supplier,
		files: (result.files || []).map((file) => file.file_url).sort(),
	});
	if (frm.__manual_supplier_requisites_dialog_key === dialogKey) return;
	frm.__manual_supplier_requisites_dialog_key = dialogKey;
	show_supplier_requisites_update_dialog(frm, result, { manualEntry: true });
}

function show_supplier_requisites_update_dialog(frm, result, { manualEntry = false } = {}) {
	if (frm.doctype !== "Purchase Invoice" || !result.allow_supplier_update) return;
	if (manualEntry && !result.allow_manual_supplier_update) return;
	const updateChecks = get_supplier_requisites_update_checks(result, manualEntry);
	if (!updateChecks.length) return;

	const fileLinks = build_supplier_pdf_links(result.files || []);
	const fields = [
		{
			fieldname: "pdf_files",
			fieldtype: "HTML",
			options: `<div class="alert alert-info"><strong>${__(
				"Check the source PDF before updating the supplier"
			)}:</strong><br>${fileLinks}</div>`,
		},
	];

	updateChecks.forEach((check) => {
		fields.push({
			fieldname: check.key,
			fieldtype: manualEntry ? "Data" : "Select",
			label: __(check.label),
			options: manualEntry ? undefined : ["", ...(check.selectable_values || [])],
			description: manualEntry
				? __("Enter the value after checking the attached PDF.")
				: check.key === "iban" && (check.expected || []).length
				? __("Select an additional IBAN to add to the supplier.")
				: __("Select the value that should be saved in the supplier record."),
		});
	});

	const hasIban = updateChecks.some((check) => check.key === "iban");
	let dialog;
	if (hasIban) {
		const ibanField = fields.find((field) => field.fieldname === "iban");
		ibanField.onchange = () => update_bank_suggestion(frm, dialog, result);
		fields.push(
			{
				fieldname: "bank_code",
				fieldtype: "Data",
				label: __("NBU Bank Code"),
				read_only: 1,
			},
			{
				fieldname: "bank",
				fieldtype: "Link",
				label: __("Bank"),
				options: "Bank",
				mandatory_depends_on: "eval:doc.iban",
			},
			{ fieldname: "bank_help", fieldtype: "HTML" }
		);
	}

	dialog = new frappe.ui.Dialog({
		title: manualEntry ? __("Enter supplier details manually") : __("Update supplier details from PDF"),
		fields,
		primary_action_label: __("Update supplier"),
		primary_action: async (values) => {
			const selected = Object.fromEntries(
				["tax_id", "edrpou", "iban", "bank"]
					.filter((key) => values[key])
					.map((key) => [key, values[key]])
			);
			if (manualEntry) selected.manual_entry = 1;
			if (!selected.tax_id && !selected.edrpou && !selected.iban) {
				frappe.msgprint(__("Select at least one value to update."));
				return;
			}
			const response = await frappe.call({
				method: updateSupplierRequisitesMethod,
				args: { doc: frm.doc, values: selected },
				freeze: true,
				freeze_message: __("Updating supplier details..."),
			});
			await apply_supplier_requisites_update(frm, response.message || {});
			dialog.hide();
			frappe.show_alert({ message: __("Supplier details updated"), indicator: "green" });
			render_supplier_requisites_validation(frm);
		},
	});
	dialog.show();
}

async function update_bank_suggestion(frm, dialog, result) {
	if (!dialog) return;
	const rawIban = dialog.get_value("iban") || "";
	const iban = rawIban.toUpperCase().replace(/[^A-Z0-9]/g, "");
	if (rawIban && rawIban !== iban) dialog.set_value("iban", iban);
	let suggestion = (result.iban_bank_suggestions || {})[iban] || {};
	if (iban && /^UA\d{27}$/.test(iban) && !suggestion.bank_code) {
		const response = await frappe.call({
			method: ibanBankSuggestionMethod,
			args: { doc: frm.doc, iban },
		});
		suggestion = response.message || {};
	}
	dialog.set_value("bank_code", suggestion.bank_code || "");
	dialog.set_value("bank", suggestion.bank || "");
	const help = dialog.get_field("bank_help");
	if (!help) return;
	if (!iban) {
		help.$wrapper.empty();
	} else if (!/^UA\d{27}$/.test(iban)) {
		help.$wrapper.html(
			`<div class="alert alert-info">${__(
				"Enter a complete Ukrainian IBAN to identify the bank."
			)}</div>`
		);
	} else if (suggestion.bank) {
		help.$wrapper.html(
			`<div class="alert alert-success">${__(
				"Bank found by NBU code"
			)}: <strong>${frappe.utils.escape_html(suggestion.bank)}</strong></div>`
		);
	} else {
		help.$wrapper.html(
			`<div class="alert alert-warning">${__(
				"The bank was not found by the code from the IBAN. Select an existing bank or create a new one and specify this NBU code."
			)}</div>`
		);
	}
}

async function apply_supplier_requisites_update(frm, response) {
	const updated = response.updated || {};
	for (const key of ["tax_id", "edrpou"]) {
		const fieldname = supplierRequisiteFields[frm.doctype]?.[key];
		if (updated[key] && fieldname && frm.fields_dict[fieldname]) {
			await frm.set_value(fieldname, updated[key]);
		}
	}
	if (response.bank_account && frm.doctype === "Payment Request") {
		await frm.set_value("bank_account", response.bank_account);
	}
	if (response.bank_account && frm.doctype === "Payment Entry") {
		await frm.set_value("party_bank_account", response.bank_account);
	}
}

function build_supplier_requisites_note(check, showMatchedFiles) {
	const status = get_supplier_requisites_status(check.status);
	const matchedFiles = showMatchedFiles
		? (check.matched_files || [])
				.map(
					(file) =>
						`<a href="${frappe.utils.escape_html(
							file.file_url || ""
						)}" target="_blank" rel="noopener noreferrer">${frappe.utils.escape_html(
							file.file_name || __("Supplier Invoice PDF")
						)}</a>`
				)
				.join(", ")
		: "";
	return `<div class="supplier-requisites-note ${frappe.utils.escape_html(check.status)}">
		<i class="fa ${status.icon}" aria-hidden="true"></i>
		<span>${frappe.utils.escape_html(check.message || "")}${
		matchedFiles ? `<br><strong>${__("Match found in PDF")}:</strong> ${matchedFiles}` : ""
	}</span>
	</div>`;
}

function get_supplier_requisites_summary(checks) {
	if (checks.some((check) => check.status === "mismatched")) {
		return {
			level: "danger",
			icon: "fa-exclamation-triangle",
			message: __(
				"Some supplier details do not match the attached PDF. Review the highlighted explanations before submitting the document."
			),
		};
	}
	if (checks.some((check) => !["matched", "not_applicable"].includes(check.status))) {
		return {
			level: "warning",
			icon: "fa-exclamation-circle",
			message: __(
				"The PDF could not be checked completely. Review the highlighted explanations before submitting the document."
			),
		};
	}
	return {
		level: "success",
		icon: "fa-check-circle",
		message: checks.some((check) => check.status === "not_applicable")
			? __("All applicable supplier details match the attached PDF.")
			: __("All supplier details match the attached PDF."),
	};
}

function get_supplier_requisites_status(status) {
	const statuses = {
		matched: { color: "green", icon: "fa-check", label: __("Matches") },
		mismatched: {
			color: "red",
			icon: "fa-exclamation-triangle",
			label: __("Does not match"),
		},
		ambiguous: {
			color: "yellow",
			icon: "fa-exclamation-triangle",
			label: __("Multiple values"),
		},
		unreadable: { color: "yellow", icon: "fa-question", label: __("Could not read") },
		missing_reference: {
			color: "orange",
			icon: "fa-exclamation",
			label: __("Not specified"),
		},
		not_applicable: {
			color: "blue",
			icon: "fa-info",
			label: __("Not applicable"),
		},
	};
	return statuses[status] || statuses.unreadable;
}

function render_supplier_requisite_field_indicators(frm, result) {
	clear_supplier_requisite_field_indicators(frm);
	if (!result.applicable || !result.has_detected_requisites) return;

	const fieldMap = supplierRequisiteFields[frm.doctype] || {};
	(result.checks || []).forEach((check) => {
		const field = frm.get_field(fieldMap[check.key]);
		if (!field?.$wrapper?.length) return;
		const label = field.$wrapper.find(".control-label").first();
		if (!label.length) return;

		const status = get_supplier_requisites_status(check.status);
		const button = $(`<button type="button"
			class="supplier-requisite-indicator ${frappe.utils.escape_html(check.status)}"
			title="${frappe.utils.escape_html(check.message || status.label)}"
			aria-label="${frappe.utils.escape_html(check.message || status.label)}">
			<i class="fa ${status.icon}" aria-hidden="true"></i>
		</button>`);
		button.on("click", () => scroll_to_supplier_requisite_check(check.key));
		label.append(button);
	});
}

function clear_supplier_requisite_field_indicators(frm) {
	Object.values(supplierRequisiteFields[frm.doctype] || {}).forEach((fieldname) => {
		frm.get_field(fieldname)?.$wrapper?.find(".supplier-requisite-indicator").remove();
	});
}

function scroll_to_supplier_requisite_check(key) {
	const row = document.getElementById(`supplier-requisites-check-${key}`);
	if (!row) return;
	row.scrollIntoView({ behavior: "smooth", block: "center" });
	row.classList.remove("supplier-requisites-row-focus");
	void row.offsetWidth;
	row.classList.add("supplier-requisites-row-focus");
}

function render_supplier_invoice_files(frm) {
	const field = frm.fields_dict[supplierInvoiceFilesField];
	if (!field) return;
	place_purchase_invoice_files_field(frm);

	const args = get_supplier_invoice_file_args(frm);
	if (!args) {
		const message =
			frm.doctype === "Purchase Invoice"
				? __(
						"Supplier invoice files are available for invoices created from a consolidated purchase order."
				  )
				: __("Supplier invoice files will appear after selecting a linked Purchase Invoice.");
		set_supplier_invoice_files_html(frm, `<div class="text-muted">${message}</div>`);
		return;
	}

	const requestId = (frm.__supplier_invoice_files_request_id || 0) + 1;
	frm.__supplier_invoice_files_request_id = requestId;
	set_supplier_invoice_files_html(frm, `<div class="text-muted">${__("Loading...")}</div>`);
	frappe.call({
		method: supplierInvoiceFilesMethod,
		args,
		callback(response) {
			if (frm.__supplier_invoice_files_request_id !== requestId) return;
			const groups = response.message || [];
			set_supplier_invoice_files_html(frm, build_supplier_invoice_files_html(groups));
			expand_purchase_invoice_supplier_section(frm, has_supplier_invoice_files(groups));
		},
	});
}

function place_purchase_invoice_files_field(frm) {
	if (frm.doctype !== "Purchase Invoice") return;

	const field = frm.fields_dict[supplierInvoiceFilesField];
	const section = frm.layout.sections.find(
		(candidate) => candidate.df.fieldname === purchaseInvoiceSupplierSection
	);
	if (!field?.$wrapper || !section?.body) return;

	let container = section.body.children(".supplier-invoice-files-full-width");
	if (!container.length) {
		container = $('<div class="supplier-invoice-files-full-width col-sm-12"></div>').appendTo(
			section.body
		);
	}
	container.append(field.$wrapper);
}

function has_supplier_invoice_files(groups) {
	return (groups || []).some((group) => (group.files || []).length);
}

function expand_purchase_invoice_supplier_section(frm, hasFiles) {
	if (frm.doctype !== "Purchase Invoice" || !hasFiles) return;

	const section = frm.layout.sections.find(
		(candidate) => candidate.df.fieldname === purchaseInvoiceSupplierSection
	);
	if (section?.is_collapsed()) section.collapse(false);
}

function get_supplier_invoice_file_args(frm) {
	if (frm.doctype === "Purchase Invoice") {
		if (!frm.doc.custom_consolidated_purchase_order || !frm.doc.supplier) return null;
		if (!frm.is_new()) {
			return {
				references: JSON.stringify([
					{
						reference_doctype: "Purchase Invoice",
						reference_name: frm.doc.name,
					},
				]),
			};
		}
		return {
			consolidated_order: frm.doc.custom_consolidated_purchase_order,
			supplier: frm.doc.supplier,
		};
	}

	const references = (frm.doc.references || [])
		.filter((row) => row.reference_name || row.payment_request)
		.map((row) => ({
			reference_doctype: row.reference_doctype,
			reference_name: row.reference_name,
			payment_request: row.payment_request,
		}));
	return references.length ? { references: JSON.stringify(references) } : null;
}

function build_supplier_invoice_files_html(groups) {
	const rows = [];
	(groups || []).forEach((group) => {
		(group.files || []).forEach((file) => {
			rows.push(`
				<tr>
					<td>${frappe.utils.escape_html(group.supplier || "")}</td>
					<td>
						<a href="${frappe.utils.escape_html(file.file_url || "")}" target="_blank" rel="noopener noreferrer">
							${frappe.utils.escape_html(file.file_name || __("Supplier Invoice PDF"))}
						</a>
					</td>
				</tr>`);
		});
	});

	if (!rows.length) {
		return `<div class="text-muted">${__(
			"No supplier invoice files are attached for this supplier."
		)}</div>`;
	}

	return `
		<div class="table-responsive">
			<table class="table table-bordered table-sm">
				<thead>
					<tr>
						<th>${__("Supplier")}</th>
						<th>${__("Supplier Invoice PDF")}</th>
					</tr>
				</thead>
				<tbody>${rows.join("")}</tbody>
			</table>
		</div>`;
}

function set_supplier_invoice_files_html(frm, html) {
	frm.fields_dict[supplierInvoiceFilesField]?.$wrapper.html(html);
}

const supplierPaymentDetailFields = {
	tax_id: "custom_party_tax_id",
	edrpou: "custom_party_edrpou",
	iban: "custom_party_iban",
};

async function render_supplier_payment_details(frm) {
	const requestId = (frm.__supplier_payment_details_request_id || 0) + 1;
	frm.__supplier_payment_details_request_id = requestId;

	if (frm.doc.party_type !== "Supplier" || !frm.doc.party) {
		set_supplier_payment_details(frm, {});
		return;
	}

	const supplierRequest = frappe.db.get_value("Supplier", frm.doc.party, ["tax_id", "edrpou"]);
	const bankAccountRequest = frm.doc.party_bank_account
		? frappe.db.get_value("Bank Account", frm.doc.party_bank_account, "iban")
		: Promise.resolve({ message: {} });
	const [supplierResponse, bankAccountResponse] = await Promise.all([supplierRequest, bankAccountRequest]);

	if (frm.__supplier_payment_details_request_id !== requestId) return;
	set_supplier_payment_details(frm, {
		tax_id: supplierResponse.message?.tax_id,
		edrpou: supplierResponse.message?.edrpou,
		iban: bankAccountResponse.message?.iban,
	});
}

function set_supplier_payment_details(frm, values) {
	Object.entries(supplierPaymentDetailFields).forEach(([sourceField, targetField]) => {
		frm.doc[targetField] = values[sourceField] || "";
		frm.refresh_field(targetField);
		add_supplier_detail_copy_button(frm, targetField);
	});
}

function add_supplier_detail_copy_button(frm, fieldname) {
	const field = frm.fields_dict[fieldname];
	const value = frm.doc[fieldname];
	if (!field || !value) return;

	const display = field.$wrapper.find(".control-value");
	if (!display.length || display.find(".supplier-detail-copy").length) return;

	display.addClass("d-flex align-items-center justify-content-between");
	$(`
		<button type="button" class="btn btn-xs btn-default supplier-detail-copy" title="${__("Copy")}">
			<i class="fa fa-copy" aria-hidden="true"></i>
			<span class="sr-only">${__("Copy")}</span>
		</button>
	`)
		.appendTo(display)
		.on("click", () => frappe.utils.copy_to_clipboard(value));
}
