(() => {
	if (erpnext.service_repair_ui_loaded) return;
	erpnext.service_repair_ui_loaded = true;
	const method = "erpnext.support.service_repair.";
	const postal = ["Nova Poshta", "Ukrposhta"];
	const stages = [
		["Awaiting Receipt", "clock-o"],
		["Received", "archive"],
		["In Repair", "wrench"],
		["Ready for Dispatch", "check"],
		["Dispatched", "truck"],
		["Closed", "flag-checkered"],
	];
	const esc = frappe.utils.escape_html;
	const link = (doctype, name) =>
		`<a href="${esc(erpnext.entity.url(["Form", doctype, name]))}" title="${esc(
			`${__(doctype)}: ${name}`
		)}">${esc(name)}</a>`;

	async function summary(frm) {
		const field = frm.fields_dict[frm.doctype === "Issue" ? "custom_repair_route" : "route_html"];
		if (frm.doctype === "Issue") {
			const section = frm.fields_dict.custom_repair_route_section;
			if (section?.wrapper?.length) section.wrapper.parent().prepend(section.wrapper);
		}
		const name = frm.doc.name;
		const { message: data } = frm.is_new()
			? { message: { status: "Awaiting Receipt", items: [] } }
			: await frappe.call({
					method: method + "get_summary",
					args: { doctype: frm.doctype, name: frm.doc.name },
			  });
		if (frm.doc.name !== name || (frm.doctype === "Issue" && !frm.doc.custom_service_repair)) return;
		frm.repair_data = data;
		if (frm.fields_dict.movement_history) {
			frm.fields_dict.movement_history.$wrapper.html(
				(data.movements || [])
					.map(
						(m) =>
							`<div class="mb-2">${link(m.doctype || "Repair Movement", m.name)} - ${esc(
								__(m.custom_repair_action)
							)} (${esc(__(["Draft", "Submitted", "Cancelled"][m.docstatus]))})</div>`
					)
					.join("") || `<p class="text-muted">${esc(__("No repair movements yet"))}</p>`
			);
		}
		if (frm.doctype === "Issue" && data.legacy_stock_entries?.length) {
			frm.set_intro(
				__(
					"A stock receipt from the previous repair flow is still submitted. Its history and stock balance have been preserved."
				),
				"orange"
			);
		}
		if (!field) return;
		const current = stages.findIndex(([status]) => status === data.status);
		const cards = stages
			.map(([status, icon], index) => {
				const active = index === current;
				const complete = index < current || (status === "Closed" && data.status === "Closed");
				const stateClass = complete ? "is-complete" : active ? "is-current" : "is-pending";
				const detail = complete
					? __("Completed")
					: active
					? __("Current stage")
					: __("Not completed yet");
				return `<div class="repair-route-segment"><div class="repair-route-step ${stateClass}">
					<div class="repair-route-icon"><i class="fa fa-${icon}" aria-hidden="true"></i></div>
					<div class="repair-route-copy"><div class="repair-route-title">${esc(__(status))}</div>
					<div class="repair-route-role">${esc(detail)}</div></div>
				</div></div>`;
			})
			.join("");
		const counts = {};
		(data.items || []).forEach((row) => {
			counts[row.status] = (counts[row.status] || 0) + 1;
		});
		const progress = Object.entries(counts)
			.map(([status, count]) => `${esc(__(status))}: ${count}`)
			.join(" · ");
		const color = data.status === "Closed" ? "green" : "blue";
		const participant = (role, user) =>
			`<div class="repair-route-participant"><span class="text-muted">${esc(__(role))}:</span> ${
				user
					? Array.isArray(user)
						? user.map((u) => erpnext.entity.user(u)).join(" ")
						: erpnext.entity.user(user)
					: esc(__("Not assigned"))
			}</div>`;
		field.$wrapper.html(`<style>
		.repair-route-card{margin:8px 0 18px;padding:14px 16px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg)}
		.repair-route-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
		.repair-route-heading{font-size:var(--text-md);font-weight:600;color:var(--heading-color)}
		.repair-route-state{max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
		.repair-route-origin{margin-bottom:14px;font-size:var(--text-sm);color:var(--text-muted)}
		.repair-route-origin a{font-weight:500}
		.repair-route-scroll{overflow:visible;padding:2px 0 4px}
		.repair-route{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));align-items:start;gap:14px;width:100%;min-width:0}
		.repair-route-segment{min-width:0}
		.repair-route-step{display:flex;align-items:flex-start;gap:9px;width:100%;min-width:0}
		.repair-route-icon{display:flex;align-items:center;justify-content:center;width:34px;height:34px;flex:0 0 34px;border:1px solid var(--border-color);border-radius:50%;color:var(--text-muted);background:var(--control-bg)}
		.repair-route-copy{min-width:0;max-width:none}
		.repair-route-title{font-size:var(--text-sm);font-weight:600;line-height:1.25;color:var(--text-color);white-space:normal}
		.repair-route-role{margin-top:2px;font-size:var(--text-xs);line-height:1.25;color:var(--text-muted);white-space:normal;overflow-wrap:anywhere}
		.repair-route-actor{margin-top:4px;overflow:hidden;text-overflow:ellipsis;font-size:var(--text-xs);line-height:1.2;color:var(--text-color);white-space:nowrap}
		.repair-route-actor a{font-weight:500}
		.repair-route-people{display:flex;flex-wrap:wrap;gap:8px 24px;margin-top:10px}
		.repair-route-participant{display:flex;align-items:center;gap:6px;font-size:var(--text-sm)}
		.repair-route-participant .ent-avatar{display:none}
		.repair-route-step.is-complete .repair-route-icon{border-color:var(--green-500);background:var(--green-100);color:var(--green-700)}
		.repair-route-step.is-current .repair-route-icon{border-color:var(--blue-500);background:var(--blue-100);color:var(--blue-700);box-shadow:0 0 0 3px var(--blue-50)}
		.repair-route-step.is-pending{opacity:.5}
		@media(max-width:767px){.repair-route-card{padding:12px}.repair-route{grid-template-columns:1fr;gap:14px}}
		</style><div class="repair-route-card">
			<div class="repair-route-head"><div class="repair-route-heading">${esc(__("Repair Route"))}</div>
			<span class="indicator-pill no-indicator-dot ${color} repair-route-state">${esc(__(data.status))}</span></div>
			${
				data.items?.length
					? `<div class="repair-route-origin">${data.items
							.map((row) => link("Repair Unit", row.repair_unit))
							.join(" ")}</div>`
					: ""
			}
			<div class="repair-route-scroll"><div class="repair-route">${cards}</div></div>
			${progress ? `<div class="text-muted small mt-2">${progress}</div>` : ""}
			${
				data.items?.length
					? `<div class="repair-route-people">${participant(
							"Support Coordinator",
							data.support_user
					  )}${participant(
							"Repair Technician",
							data.repair_users?.length ? data.repair_users : null
					  )}</div>`
					: ""
			}
		</div>`);
	}

	frappe.ui.form.on("Issue", {
		async refresh(frm) {
			frm.toggle_display(["customer_name", "issue_split_from"], !frm.doc.custom_service_repair);
			frm.toggle_reqd(
				["contact", "company", "custom_repair_items"],
				Boolean(frm.doc.custom_service_repair)
			);
			["custom_repair_items"].forEach((field) => {
				frm.set_df_property(field, "read_only", false);
			});
			if (!frm.doc.custom_service_repair) return;
			await summary(frm);
			if (
				!frm.is_new() &&
				frm.doc.custom_repair_items?.some((row) => !row.repair_unit) &&
				frm.perm?.[0]?.write
			) {
				frm.add_custom_button(__("Create Repair Cards"), async () => {
					if (frm.is_dirty()) await frm.save();
					await frappe.call({
						method: "erpnext.support.repair_units.create_units",
						args: { issue: frm.doc.name },
						freeze: true,
					});
					await frm.reload_doc();
				});
			}
			if (!frm.is_new() && frm.repair_data?.items?.length && frm.perm?.[0]?.write) {
				[
					["Receive Units", "receive", ["Awaiting Receipt"]],
					["Dispatch Units", "dispatch", ["Ready for Dispatch"]],
					["Dispose with Customer Approval", "dispose", ["Ready for Dispatch"]],
				].forEach(([label, action, states]) => {
					if (
						frm.repair_data?.items?.some(
							(r) =>
								states.includes(r.status) &&
								(action !== "dispose" || r.outcome === "Not Repairable")
						)
					)
						frm.add_custom_button(__(label), () => movement(frm, action, states));
				});
				if (frm.repair_data?.items?.some((r) => r.status === "Dispatched"))
					frm.add_custom_button(__("Confirm Customer Delivery"), () => update(frm, true));
			}
		},
		custom_service_repair(frm) {
			frm.refresh();
		},
	});

	const unit_field = (frm, states, action) => ({
		fieldname: "units",
		label: __("Repair Units"),
		fieldtype: "MultiCheck",
		reqd: 1,
		options: (frm.doc.items || frm.repair_data?.items || [])
			.filter(
				(r) => states.includes(r.status) && (action !== "dispose" || r.outcome === "Not Repairable")
			)
			.map((r) => ({
				label: `${r.repair_unit} — ${r.product_name} (${__(r.status)} · ${
					r.outcome ? __(r.outcome) : __("Result not specified")
				})`,
				value: r.repair_unit,
			})),
	});

	function movement(frm, action, states) {
		const fields = [unit_field(frm, states, action)];
		if (["receive", "dispatch"].includes(action)) {
			fields.push(
				{
					fieldname: "delivery_type",
					label: __("Delivery Type"),
					fieldtype: "Select",
					options: ["", "Nova Poshta", "Ukrposhta", "Taxi", "Self Pickup", "Other"].join("\n"),
					reqd: 1,
					default: action === "receive" ? frm.doc.custom_repair_delivery_type : "",
				},
				{
					fieldname: "waybill",
					label: __(action === "receive" ? "Inbound Waybill" : "Outbound Waybill"),
					fieldtype: "Data",
					depends_on: "eval:['Nova Poshta', 'Ukrposhta'].includes(doc.delivery_type)",
					mandatory_depends_on: "eval:['Nova Poshta', 'Ukrposhta'].includes(doc.delivery_type)",
					default: action === "receive" ? frm.doc.custom_repair_waybill : "",
				},
				{
					fieldname: "delivery_details",
					label: __("Delivery Details"),
					fieldtype: "Small Text",
					depends_on:
						"eval:doc.delivery_type && !['Nova Poshta', 'Ukrposhta'].includes(doc.delivery_type)",
					mandatory_depends_on:
						"eval:doc.delivery_type && !['Nova Poshta', 'Ukrposhta'].includes(doc.delivery_type)",
					default: action === "receive" ? frm.doc.custom_repair_delivery_details : "",
				}
			);
		}
		if (["receive", "transfer"].includes(action)) {
			fields.push({
				fieldname: "warehouse",
				label: __("Destination Warehouse"),
				fieldtype: "Link",
				options: "Warehouse",
				reqd: 1,
				default: frm.repair_data?.default_warehouse,
				get_query: () => ({
					query: "erpnext.support.repair_unit_movement.warehouse_query",
					filters: { issue: frm.doc.name },
				}),
			});
		}
		if (action === "receive") {
			(frm.doc.items || frm.repair_data?.items || [])
				.filter((r) => states.includes(r.status))
				.forEach((row, index) => {
					fields.push({
						fieldname: `serial_${index}`,
						label: `${__("Factory Serial Number")} - ${row.product_name || row.repair_unit}`,
						fieldtype: "Data",
						default: row.factory_serial,
						repair_unit: row.repair_unit,
					});
				});
		}

		if (action === "dispose") {
			fields.push({
				fieldname: "disposal_approved",
				label: __("Customer Agreed to Disposal"),
				fieldtype: "Check",
				reqd: 1,
			});
			fields.push({
				fieldname: "approval",
				label: __("Customer Disposal Approval"),
				fieldtype: "Attach",
				reqd: 0,
			});
		}
		frappe.prompt(
			fields,
			async (values) => {
				if (action === "dispose" && !values.disposal_approved)
					frappe.throw(__("Confirm that the customer agreed to disposal."));
				if (["receive", "dispatch"].includes(action)) {
					if (postal.includes(values.delivery_type)) delete values.delivery_details;
					else delete values.waybill;
				}
				if (frm.is_dirty()) await frm.save();
				const serials = Object.fromEntries(
					fields
						.filter((f) => f.repair_unit && (values.units || []).includes(f.repair_unit))
						.map((f) => [f.repair_unit, values[f.fieldname]])
				);
				fields.filter((f) => f.repair_unit).forEach((f) => delete values[f.fieldname]);
				const { message } = await frappe.call({
					method: "erpnext.support.repair_unit_movement.register",
					args: { issue: frm.doc.name, action, ...values, serials },
					freeze: true,
				});
				await frm.reload_doc();
				frappe.show_alert(__("Repair movement registered."));
			},
			__(action),
			__("Confirm")
		);
	}

	function update(frm) {
		frappe.prompt(
			[unit_field(frm, ["Dispatched"])],
			async (values) => {
				for (const unit of values.units)
					await frappe.call({
						method: "erpnext.support.repair_units.change_stage",
						args: { unit, status: "Delivered" },
						freeze: true,
					});
				await frm.reload_doc();
			},
			__("Confirm Customer Delivery"),
			__("Apply")
		);
	}
})();
