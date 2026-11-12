(() => {
	const api = "erpnext.support.";
	const esc = frappe.utils.escape_html;
	const link = (doctype, name) =>
		`<a href="${esc(erpnext.entity.url(["Form", doctype, name]))}" title="${esc(
			`${__(doctype)}: ${name}`
		)}">${esc(name)}</a>`;
	const working = [
		"Received",
		"In Repair",
		"Waiting for Parts",
		"Waiting for Customer",
		"Ready for Dispatch",
	];
	const colors = {
		"Awaiting Receipt": "gray",
		Received: "blue",
		"In Repair": "orange",
		"Waiting for Parts": "yellow",
		"Waiting for Customer": "yellow",
		"Ready for Dispatch": "green",
		Dispatched: "blue",
		Delivered: "green",
		Disposed: "red",
	};

	async function stage(frm, status) {
		if (frm.is_dirty()) await frm.save();
		await frappe.call({
			method: api + "repair_units.change_stage",
			args: { unit: frm.doc.name, status },
			freeze: true,
		});
		try {
			await frm.reload_doc();
		} catch {
			frappe.show_alert({
				message: __("The operation was completed. Reload the document to see the latest data."),
				indicator: "orange",
			});
		}
	}

	function distribution(frm, canWork) {
		const field = frm.fields_dict.outcome_distribution;
		const batch = !frm.doc.has_serial_no && frm.doc.qty > 1;
		frm.toggle_display("outcome_distribution", batch);
		frm.toggle_display("outcome", !batch);
		frm.toggle_display("qty", !frm.doc.has_serial_no);
		field.$wrapper.empty();
		if (!batch) return;
		const options = [
			["repaired_qty", "Repaired"],
			["no_fault_qty", "No Fault Found"],
			["not_repairable_qty", "Not Repairable"],
		];
		const editable = canWork && !frm.doc.split_finalized;
		field.$wrapper.html(`<style>
			.repair-results{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px}
			.repair-result{flex:1 1 150px;min-width:0;padding:10px 12px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--control-bg)}
			.repair-result label{display:block;font-size:var(--text-sm);margin-bottom:6px}
			.repair-result input{width:100%;border:0;background:var(--card-bg);border-radius:6px;padding:5px 8px;font-weight:600;color:var(--text-color)}
		</style><div class="repair-results">${options
			.map(
				([key, label]) => `
			<div class="repair-result"><label for="repair-${key}">${esc(__(label))}</label>
			<input id="repair-${key}" data-result="${key}" type="number" min="0" max="${frm.doc.qty}" step="1" value="${
					frm.doc[key] || 0
				}" ${editable ? "" : "disabled"}></div>`
			)
			.join("")}
		</div><div class="text-muted small repair-result-total"></div>`);
		const updateTotal = () => {
			const total = options.reduce((sum, [key]) => sum + (frm.doc[key] || 0), 0);
			field.$wrapper
				.find(".repair-result-total")
				.text(__("Distributed {0} of {1}", [total, frm.doc.qty]));
			for (const [key] of options) {
				field.$wrapper
					.find(`[data-result="${key}"]`)
					.attr("max", frm.doc.qty - total + (frm.doc[key] || 0));
			}
		};
		updateTotal();
		field.$wrapper.find("input[data-result]").on("change", async function () {
			const key = this.dataset.result;
			const value = Number(this.value);
			const others = options.reduce((sum, [name]) => sum + (name === key ? 0 : frm.doc[name] || 0), 0);
			if (!Number.isInteger(value) || value < 0 || value + others > frm.doc.qty) {
				this.value = frm.doc[key] || 0;
				frappe.show_alert({
					message: __("The total repair result quantity cannot exceed the repair quantity."),
					indicator: "red",
				});
				return;
			}
			await frm.set_value(key, value);
			updateTotal();
		});
	}

	function render_parts(frm, rows) {
		frm.fields_dict.total_cost.$wrapper.siblings(".repair-consumed-parts").remove();
		const headers = [
			"Item",
			"Quantity",
			"Rate",
			"Amount",
			"Posted By",
			"Posting Date",
			"Stock Entry",
			"Status",
		];
		const body = rows
			.map(
				(row) => `<tr>
			<td title="${esc(row.item_name || row.item_code)}">${link(
					"Item",
					row.item_code
				)}<div class="text-muted small">${esc(row.item_name || "")}</div></td>
			<td class="text-right">${esc(row.qty)} ${esc(row.uom)}</td>
			<td class="text-right text-nowrap">${esc(format_currency(row.rate, frm.doc.currency))}</td>
			<td class="text-right text-nowrap">${esc(format_currency(row.amount, frm.doc.currency))}</td>
			<td>${esc(row.posted_by_name || row.posted_by || __("Not recorded"))}</td>
			<td class="text-nowrap">${esc(row.posted_on ? frappe.datetime.str_to_user(row.posted_on) : "—")}</td>
			<td>${row.can_open ? link("Stock Entry", row.stock_entry) : esc(row.stock_entry)}</td>
			<td><span class="indicator-pill ${row.docstatus === 2 ? "red" : "green"}">${esc(
					__(row.docstatus === 2 ? "Cancelled" : "Submitted")
				)}</span></td>
		</tr>`
			)
			.join("");
		frm.fields_dict.total_cost.$wrapper.after(`<div class="repair-consumed-parts mt-4">
			<h5>${esc(__("Consumed Parts"))}</h5>
			${
				rows.length
					? `<div class="table-responsive"><table class="table table-bordered"><thead><tr>${headers
							.map((title) => `<th>${esc(__(title))}</th>`)
							.join("")}</tr></thead><tbody>${body}</tbody></table></div>
			<p class="text-muted small">${esc(__("Cancelled issues are excluded from the repair cost."))}</p>`
					: `<p class="text-muted">${esc(__("No parts have been consumed for this repair."))}</p>`
			}
		</div>`);
	}

	function parts(frm) {
		erpnext.repair_form.prompt(
			frm,
			[
				{
					fieldname: "parts",
					label: __("Consumed Parts"),
					fieldtype: "Table",
					reqd: 1,
					in_place_edit: true,
					fields: [
						{
							fieldname: "item_code",
							label: __("Item"),
							fieldtype: "Link",
							options: "Item",
							in_list_view: 1,
							reqd: 1,
						},
						{
							fieldname: "qty",
							label: __("Quantity"),
							fieldtype: "Float",
							in_list_view: 1,
							reqd: 1,
						},
						{
							fieldname: "warehouse",
							label: __("Source Warehouse"),
							fieldtype: "Link",
							options: "Warehouse",
							in_list_view: 1,
							reqd: 1,
							get_query: () => ({
								filters: { company: frm.doc.company, is_group: 0, disabled: 0 },
							}),
						},
						{ fieldname: "serial_no", label: __("Serial No"), fieldtype: "Small Text" },
						{ fieldname: "batch_no", label: __("Batch No"), fieldtype: "Link", options: "Batch" },
					],
				},
			],
			async (values) => {
				if (frm.is_dirty()) await frm.save();
				const { message } = await frappe.call({
					method: api + "repair_unit_movement.consume_parts",
					args: { unit: frm.doc.name, parts: values.parts },
					freeze: true,
				});
				frappe.set_route("Form", "Stock Entry", message);
			},
			__("Consume Parts"),
			__("Create Stock Entry")
		);
	}

	frappe.ui.form.on("Repair Unit", {
		async refresh(frm) {
			erpnext.repair_form.refresh(frm);
			if (!frm.is_dirty() || !$(frm.wrapper).hasClass("repair-form-ui")) {
				frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
			}
			if (frm.is_new()) return;
			const manager = frappe.session.user === "Administrator" || frappe.user.has_role("System Manager");
			const technician = manager || frappe.user.has_role("Repair Technician");
			const ownRepair = manager || frm.doc.repair_user === frappe.session.user;
			const canWork = Boolean(
				technician &&
					ownRepair &&
					frm.doc.received_on &&
					working.includes(frm.doc.status) &&
					frm.perm?.[0]?.write
			);
			if (
				technician &&
				frm.doc.status === "Received" &&
				frm.doc.received_on &&
				(!frm.doc.repair_user || ownRepair) &&
				frm.perm?.[0]?.write
			) {
				frm.add_custom_button(__("Take into Work"), () => stage(frm, "In Repair"));
			}
			["diagnosis", "work_done", "outcome", "work_log"].forEach((field) =>
				frm.set_df_property(field, "read_only", !canWork)
			);
			if (frm.doc.split_finalized) frm.set_df_property("outcome", "read_only", true);
			distribution(frm, canWork);
			if (canWork) {
				if (
					["Waiting for Parts", "Waiting for Customer", "Ready for Dispatch"].includes(
						frm.doc.status
					)
				)
					frm.add_custom_button(__("Resume Repair"), () => stage(frm, "In Repair"));
				if (frm.doc.status !== "Ready for Dispatch") {
					frm.add_custom_button(
						__("Waiting for Parts"),
						() => stage(frm, "Waiting for Parts"),
						__("Repair Stage")
					);
					frm.add_custom_button(
						__("Waiting for Customer"),
						() => stage(frm, "Waiting for Customer"),
						__("Repair Stage")
					);
					frm.add_custom_button(
						__("Ready for Dispatch"),
						() => stage(frm, "Ready for Dispatch"),
						__("Repair Stage")
					);
				}
				if (
					["In Repair", "Waiting for Parts"].includes(frm.doc.status) &&
					frappe.model.can_create("Stock Entry")
				)
					frm.add_custom_button(__("Consume Parts"), () => parts(frm));
			}
			const { message: data } = await frappe.call({
				method: api + "service_repair.get_summary",
				args: { doctype: frm.doctype, name: frm.doc.name },
			});
			render_parts(frm, data.consumed_parts || []);
			frm.fields_dict.unit_history.$wrapper.html(
				(data.legacy_order
					? `<div class="mb-2">${esc(__("Legacy Repair Order"))}: ${link(
							"Repair Order",
							data.legacy_order
					  )}</div>`
					: "") +
					(data.legacy_stock_entries || [])
						.map((name) => `<div class="mb-2">${link("Stock Entry", name)}</div>`)
						.join("") +
					(data.previous_repairs || [])
						.map(
							(row) =>
								`<div class="mb-2">${__("Previous Repair")}: ${link(
									"Repair Unit",
									row.name
								)} <span class="indicator-pill ${colors[row.status] || "gray"}">${esc(
									__(row.status)
								)}</span></div>`
						)
						.join("") +
					(data.movements || [])
						.map(
							(row) =>
								`<div class="mb-2">${link(row.doctype, row.name)} - ${esc(
									__(row.custom_repair_action)
								)} (${esc(__(["Draft", "Submitted", "Cancelled"][row.docstatus]))})</div>`
						)
						.join("")
			);
		},
	});
})();
