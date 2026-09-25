const supplierInvoiceFilesField = "custom_supplier_invoice_files_html";
const purchaseInvoiceSupplierSection = "supplier_invoice_details";
const supplierInvoiceFilesMethod =
	"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_supplier_invoice_files";

frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		render_supplier_invoice_files(frm);
	},
	supplier(frm) {
		render_supplier_invoice_files(frm);
	},
	custom_consolidated_purchase_order(frm) {
		render_supplier_invoice_files(frm);
	},
});

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		render_supplier_invoice_files(frm);
		render_supplier_payment_details(frm);
	},
	party_type(frm) {
		render_supplier_payment_details(frm);
	},
	party(frm) {
		render_supplier_payment_details(frm);
	},
	party_bank_account(frm) {
		render_supplier_payment_details(frm);
	},
});

frappe.ui.form.on("Payment Entry Reference", {
	reference_doctype(frm) {
		render_supplier_invoice_files(frm);
	},
	reference_name(frm) {
		render_supplier_invoice_files(frm);
	},
	payment_request(frm) {
		render_supplier_invoice_files(frm);
	},
	references_remove(frm) {
		render_supplier_invoice_files(frm);
	},
});

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
