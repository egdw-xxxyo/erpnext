// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Supplier", {
	setup: function (frm) {
		frm.set_query("default_price_list", { buying: 1 });
		if (frm.doc.__islocal == 1) {
			frm.set_value("represents_company", "");
		}
		frm.set_query("account", "accounts", function (doc, cdt, cdn) {
			let d = locals[cdt][cdn];
			return {
				filters: {
					account_type: "Payable",
					root_type: "Liability",
					company: d.company,
					is_group: 0,
				},
			};
		});

		frm.set_query("advance_account", "accounts", function (doc, cdt, cdn) {
			let d = locals[cdt][cdn];
			return {
				filters: {
					account_type: "Payable",
					root_type: "Asset",
					company: d.company,
					is_group: 0,
				},
			};
		});

		frm.set_query("default_bank_account", function () {
			return {
				filters: {
					is_company_account: 1,
				},
			};
		});

		frm.set_query("supplier_primary_contact", function (doc) {
			return {
				query: "erpnext.buying.doctype.supplier.supplier.get_supplier_primary",
				filters: {
					supplier: doc.name,
					type: "Contact",
				},
			};
		});

		frm.set_query("supplier_primary_address", function (doc) {
			return {
				query: "erpnext.buying.doctype.supplier.supplier.get_supplier_primary",
				filters: {
					supplier: doc.name,
					type: "Address",
				},
			};
		});

		frm.set_query("user", "portal_users", function (doc) {
			return {
				filters: {
					ignore_user_type: true,
				},
			};
		});

		frm.make_methods = {
			"Purchase Order": () =>
				frappe.model.with_doctype("Purchase Order", function () {
					const po = frappe.model.get_new_doc("Purchase Order");
					po.supplier = frm.doc.name;
					frappe.set_route("Form", "Purchase Order", po.name);
				}),
			"Purchase Invoice": () =>
				frappe.model.with_doctype("Purchase Invoice", function () {
					const pi = frappe.model.get_new_doc("Purchase Invoice");
					pi.supplier = frm.doc.name;
					frappe.set_route("Form", "Purchase Invoice", pi.name);
				}),
			"Request for Quotation": () =>
				frappe.model.with_doctype("Request for Quotation", function () {
					const rfq = frappe.model.get_new_doc("Request for Quotation");
					const row = frappe.model.add_child(rfq, "suppliers");
					row.supplier = frm.doc.name;
					frappe.set_route("Form", "Request for Quotation", rfq.name);
				}),
			"Supplier Quotation": () =>
				frappe.model.with_doctype("Supplier Quotation", function () {
					const sq = frappe.model.get_new_doc("Supplier Quotation");
					sq.supplier = frm.doc.name;
					frappe.set_route("Form", "Supplier Quotation", sq.name);
				}),
			"Bank Account": () => erpnext.utils.make_bank_account(frm.doc.doctype, frm.doc.name),
			"Pricing Rule": () => frm.trigger("make_pricing_rule"),
		};
	},

	website(frm) {
		if (frm.doc.website_details !== frm.doc.website) {
			frm.set_value("website_details", frm.doc.website);
		}
	},

	website_details(frm) {
		if (frm.doc.website !== frm.doc.website_details) {
			frm.set_value("website", frm.doc.website_details);
		}
	},

	supplier_group(frm) {
		if (frm.doc.supplier_group) {
			frm.trigger("get_supplier_group_details");
		}
	},

	refresh: function (frm) {
		frm.trigger("render_supplier_bank_accounts");

		if (frappe.defaults.get_default("supp_master_name") != "Naming Series") {
			frm.toggle_display("naming_series", false);
		} else {
			erpnext.toggle_naming_series();
		}

		if (frm.doc.__islocal) {
			hide_field(["address_html", "contact_html"]);
			frappe.contacts.clear_address_and_contact(frm);
		} else {
			unhide_field(["address_html", "contact_html"]);
			frappe.contacts.render_address_and_contact(frm);

			// custom buttons
			frm.add_custom_button(
				__("Accounting Ledger"),
				function () {
					frappe.set_route("query-report", "General Ledger", {
						party_type: "Supplier",
						party: frm.doc.name,
						party_name: frm.doc.supplier_name,
					});
				},
				__("View")
			);

			frm.add_custom_button(
				__("Accounts Payable"),
				function () {
					frappe.set_route("query-report", "Accounts Payable", {
						party_type: "Supplier",
						party: frm.doc.name,
					});
				},
				__("View")
			);

			for (const doctype in frm.make_methods) {
				frm.add_custom_button(__(doctype), frm.make_methods[doctype], __("Create"));
			}

			if (frm.doc.supplier_group) {
				frm.add_custom_button(
					__("Get Supplier Group Details"),
					function () {
						frm.trigger("get_supplier_group_details");
					},
					__("Actions")
				);
			}

			if (
				cint(frappe.defaults.get_default("enable_common_party_accounting")) &&
				frappe.model.can_create("Party Link")
			) {
				frm.add_custom_button(
					__("Link with Customer"),
					function () {
						frm.trigger("show_party_link_dialog");
					},
					__("Actions")
				);
			}

			// indicators
			erpnext.utils.set_party_dashboard_indicators(frm);
		}
	},

	render_supplier_bank_accounts(frm) {
		const field = frm.fields_dict.supplier_bank_accounts_html;
		if (!field) {
			return;
		}

		if (frm.is_new()) {
			field.$wrapper.html(
				`<p class="text-muted">${__("Save the supplier before adding bank accounts.")}</p>`
			);
			return;
		}

		field.$wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
		frappe.call({
			method: "erpnext.buying.doctype.supplier.supplier.get_supplier_bank_accounts",
			args: { supplier: frm.doc.name },
			callback: (response) => {
				const accounts = response.message || [];
				render_supplier_bank_accounts_table(frm, accounts);
			},
		});
	},

	after_save(frm) {
		frm.doc.supplier_default_bank_account_selection = null;
		frm.trigger("render_supplier_bank_accounts");
	},
	get_supplier_group_details: function (frm) {
		frappe.call({
			method: "get_supplier_group_details",
			doc: frm.doc,
			callback: function () {
				frm.refresh();
			},
		});
	},

	supplier_primary_address: function (frm) {
		if (frm.doc.supplier_primary_address) {
			frappe.call({
				method: "frappe.contacts.doctype.address.address.get_address_display",
				args: {
					address_dict: frm.doc.supplier_primary_address,
				},
				callback: function (r) {
					frm.set_value("primary_address", frappe.utils.html2text(r.message));
				},
			});
		}
		if (!frm.doc.supplier_primary_address) {
			frm.set_value("primary_address", "");
		}
	},

	supplier_primary_contact: function (frm) {
		if (!frm.doc.supplier_primary_contact) {
			frm.set_value("mobile_no", "");
			frm.set_value("email_id", "");
		}
	},

	is_internal_supplier: function (frm) {
		if (frm.doc.is_internal_supplier == 1) {
			frm.toggle_reqd("represents_company", true);
		} else {
			frm.toggle_reqd("represents_company", false);
			frm.set_value("represents_company", "");
			frm.set_value("companies", []);
		}
	},
	show_party_link_dialog: function (frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Select a Customer"),
			fields: [
				{
					fieldtype: "Link",
					label: __("Customer"),
					options: "Customer",
					fieldname: "customer",
					reqd: 1,
				},
			],
			primary_action: function ({ customer }) {
				frappe.call({
					method: "erpnext.accounts.doctype.party_link.party_link.create_party_link",
					args: {
						primary_role: "Supplier",
						primary_party: frm.doc.name,
						secondary_party: customer,
					},
					freeze: true,
					callback: function () {
						dialog.hide();
						frappe.msgprint({
							message: __("Successfully linked to Customer"),
							alert: true,
						});
					},
					error: function () {
						dialog.hide();
						frappe.msgprint({
							message: __("Linking to Customer Failed. Please try again."),
							title: __("Linking Failed"),
							indicator: "red",
						});
					},
				});
			},
			primary_action_label: __("Create Link"),
		});
		dialog.show();
	},
	make_pricing_rule: function (frm) {
		frappe.new_doc("Pricing Rule", {
			applicable_for: "Supplier",
			supplier: frm.doc.name,
			buying: 1,
		});
	},
});

function render_supplier_bank_accounts_table(frm, accounts) {
	const field = frm.fields_dict.supplier_bank_accounts_html;
	if (!field) {
		return;
	}

	if (!accounts.length) {
		field.$wrapper.html(
			`<p class="text-muted">${__("No bank accounts are configured for this supplier.")}</p>`
		);
		return;
	}

	const pending = frm.doc.supplier_default_bank_account_selection;
	const has_pending = pending !== undefined && pending !== null;
	const rows = accounts
		.map((account) => {
			const account_name = frappe.utils.escape_html(account.account_name || account.name);
			const bank_account = frappe.utils.escape_html(account.name);
			const account_link = frappe.utils.get_form_link("Bank Account", account.name, true, account_name);
			const iban = frappe.utils.escape_html(account.iban || __("Not specified"));
			const is_default = has_pending ? pending === account.name : cint(account.is_default);
			return `
				<tr>
					<td>${account_link}</td>
					<td>${iban}</td>
					<td class="text-center">
						<input type="checkbox" class="supplier-bank-account-default"
							data-bank-account="${bank_account}" ${is_default ? "checked" : ""}>
					</td>
				</tr>`;
		})
		.join("");

	field.$wrapper.html(`
		<div class="table-responsive">
			<table class="table table-bordered">
				<thead>
					<tr>
						<th>${__("Account Name")}</th>
						<th>${__("IBAN")}</th>
						<th class="text-center">${__("Default Account")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`);

	field.$wrapper
		.find(".supplier-bank-account-default")
		.off("change.supplier-bank-accounts")
		.on("change.supplier-bank-accounts", function () {
			const checkbox = $(this);
			if (checkbox.prop("checked")) {
				field.$wrapper.find(".supplier-bank-account-default").not(checkbox).prop("checked", false);
				frm.set_value("supplier_default_bank_account_selection", checkbox.attr("data-bank-account"));
			} else {
				frm.set_value("supplier_default_bank_account_selection", "");
			}
		});
}
