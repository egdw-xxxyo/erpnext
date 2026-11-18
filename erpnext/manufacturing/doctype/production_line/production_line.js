frappe.ui.form.on("Production Line", {
	refresh(frm) {
		frm.trigger("show_workplaces");
		frm.trigger("show_orders");
		frm.trigger("show_critical_stock");
		frm.trigger("add_fill_from_boms_button");
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Production Flow"),
			() => {
				frappe.set_route("production-flow", { production_line: frm.doc.name });
			},
			__("View")
		);
		frm.add_custom_button(
			__("Production Line Overview"),
			() => {
				frappe.set_route("production-line-overview", { production_line: frm.doc.name });
			},
			__("View")
		);
		if (frm.doc.planning_mode == "Manual Planning") {
			frm.add_custom_button(__("Add Order"), () => frm.trigger("add_order_dialog"));
			const waiting = (frm.doc.orders || []).filter((row) => !row.work_order).length;
			if (waiting) {
				frm.add_custom_button(__("Release Orders"), () => frm.trigger("release_orders")).addClass(
					"btn-primary"
				);
			}
			return;
		}
		frm.add_custom_button(__("Close Day"), () => {
			frappe.confirm(
				__(
					"Units nobody started lose their Job Cards and Serial Nos, and each Work Order of the line shrinks to the units that were started. Continue?"
				),
				() =>
					frappe.call({
						method: "erpnext.manufacturing.doctype.production_line.production_line.close_day",
						args: { line: frm.doc.name },
						freeze: true,
						callback: (r) => {
							frappe.msgprint({
								title: __("Close Day"),
								message: frappe.utils.escape_html(r.message || "").replace(/\n/g, "<br>"),
							});
							frm.reload_doc();
						},
					})
			);
		});
	},
	planning_mode(frm) {
		frm.refresh();
	},
	release_orders(frm) {
		const release = () =>
			frappe.call({
				method: "erpnext.manufacturing.doctype.production_line.production_line.release_orders",
				args: { line: frm.doc.name },
				freeze: true,
				callback: (r) => {
					frappe.msgprint({
						title: __("Release Orders"),
						message: (r.message || []).map((line) => frappe.utils.escape_html(line)).join("<br>"),
					});
					frm.reload_doc();
				},
			});
		const waiting = (frm.doc.orders || []).filter((row) => !row.work_order).length;
		frappe.confirm(
			__(
				"Open a Work Order for each of the {0} order(s) that have none? Serial Nos and Job Cards are created now.",
				[waiting]
			),
			() => (frm.is_dirty() ? frm.save().then(release) : release())
		);
	},
	orders_remove(frm) {
		frm.trigger("hide_released_orders");
	},
	orders_add(frm) {
		frm.trigger("hide_released_orders");
	},
	hide_released_orders(frm) {
		// A released order is a Work Order: it is listed, read-only, under the progress tables.
		const grid = frm.fields_dict.orders && frm.fields_dict.orders.grid;
		if (!grid) return;
		(grid.grid_rows || []).forEach((row) => row.wrapper.toggle(!row.doc.work_order));
	},
	show_orders(frm) {
		frm.trigger("hide_released_orders");
		const current = frm.fields_dict.current_orders;
		const done = frm.fields_dict.done_orders;
		if (!current || !done) return;
		if (frm.is_new() || frm.doc.planning_mode != "Manual Planning") {
			current.$wrapper.html("");
			done.$wrapper.html("");
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.doctype.production_line.production_line.order_progress",
			args: { line: frm.doc.name },
			callback: (r) => {
				const esc = frappe.utils.escape_html;
				const render = (rows, empty) => {
					if (!rows.length) return `<div class="text-muted">${empty}</div>`;
					const body = rows
						.map((row) => {
							const percent = row.qty
								? Math.min(100, Math.round((row.produced_qty / row.qty) * 100))
								: 0;
							return `<tr>
								<td>${esc(row.item_code)}<div class="text-muted small">${esc(row.item_name || "")}</div></td>
								<td>${row.workplace ? esc(row.workplace) : `<span class="text-muted">—</span>`}</td>
								<td><a href="/desk/work-order/${encodeURIComponent(row.work_order)}">${esc(row.work_order)}</a>
									<div class="text-muted small">${__(row.status)}</div></td>
								<td class="text-right">${row.produced_qty} / ${row.qty}</td>
								<td style="min-width: 160px"><div class="progress" style="margin: 0">
									<div class="progress-bar" style="width: ${percent}%">${percent}%</div></div></td>
							</tr>`;
						})
						.join("");
					return `<table class="table table-bordered table-sm">
						<thead><tr>
							<th>${__("Item")}</th><th>${__("Workplace")}</th><th>${__("Work Order")}</th>
							<th class="text-right">${__("Produced")}</th><th>${__("Progress")}</th>
						</tr></thead><tbody>${body}</tbody></table>`;
				};
				const result = r.message || { current: [], done: [] };
				current.$wrapper.html(render(result.current, __("No released orders in progress")));
				done.$wrapper.html(render(result.done, __("No completed orders yet")));
			},
		});
	},
	show_workplaces(frm) {
		const wrapper = frm.fields_dict.workplace_overview.$wrapper;
		if (frm.is_new() || !(frm.doc.workplaces || []).length) {
			wrapper.html("");
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.doctype.production_line.production_line.workplace_overview",
			args: { line: frm.doc.name },
			callback: (r) => {
				const esc = frappe.utils.escape_html;
				const dash = `<span class="text-muted">—</span>`;
				const body = (r.message || [])
					.map((row) => {
						const operations = row.operations.length
							? row.operations
									.map(
										(op) =>
											esc(op.operation) +
											(op.workstation
												? ` <span class="text-muted">· ${esc(op.workstation)}</span>`
												: "")
									)
									.join("<br>")
							: dash;
						const warehouse = row.target_warehouse
							? esc(row.target_warehouse)
							: `<span class="text-muted">${__("does not change")}</span>`;
						return `<tr${row.enabled ? "" : ' class="text-muted"'}>
							<td>${erpnext.entity.workplace(row.workplace)}</td>
							<td>${__(row.role)}</td>
							<td>${operations}</td>
							<td>${row.script ? esc(row.script) : dash}</td>
							<td class="text-right">${row.employees || dash}</td>
							<td>${warehouse}</td>
						</tr>`;
					})
					.join("");
				wrapper.html(
					`<table class="table table-bordered table-sm">
						<thead><tr>
							<th>${__("Workplace")}</th><th>${__("Role")}</th>
							<th>${__("Allowed Operations")}</th><th>${__("Workplace Script")}</th>
							<th class="text-right">${__("Employees")}</th>
							<th>${__("Warehouse After Operation")}</th>
						</tr></thead>
						<tbody>${body}</tbody>
					</table>`
				);
			},
		});
	},
	setup(frm) {
		frm.set_query("target_warehouse", "workplaces", function (doc) {
			const filters = { is_group: 0 };
			if (doc.company) filters.company = doc.company;
			return { filters };
		});

		frm.set_query("workplace", "workplaces", function (doc) {
			const picked = (doc.workplaces || []).map((row) => row.workplace).filter(Boolean);
			return { filters: { is_active: 1, name: ["not in", picked] } };
		});

		const bench_query = function (doc) {
			const allowed = (doc.workplaces || [])
				.filter((row) => row.enabled && row.workplace && (row.role || "Production") == "Production")
				.map((row) => row.workplace);
			if (!allowed.length) return { filters: { is_active: 1 } };
			return { filters: { name: ["in", allowed] } };
		};
		frm.set_query("workplace", "plan", bench_query);
		frm.set_query("workplace", "orders", bench_query);

		frm.set_query("item_code", "allowed_items", function (doc) {
			const picked = (doc.allowed_items || []).map((row) => row.item_code).filter(Boolean);
			return { filters: { disabled: 0, default_bom: ["is", "set"], name: ["not in", picked] } };
		});
		frm.set_query("item_code", "critical_stock", function (doc) {
			const picked = (doc.critical_stock || []).map((row) => row.item_code).filter(Boolean);
			return { filters: { disabled: 0, is_stock_item: 1, name: ["not in", picked] } };
		});
		const allowed_item_query = function (doc) {
			const allowed = (doc.allowed_items || []).map((row) => row.item_code).filter(Boolean);
			if (!allowed.length) return { filters: { disabled: 0 } };
			return { filters: { name: ["in", allowed] } };
		};
		frm.set_query("item_code", "plan", allowed_item_query);
		frm.set_query("item_code", "orders", allowed_item_query);
		frm.allowed_item_query = allowed_item_query;
		frm.bench_query = bench_query;
	},
	allowed_items_remove(frm) {
		frm.trigger("show_critical_stock");
	},
	add_fill_from_boms_button(frm) {
		const grid = frm.fields_dict.critical_stock && frm.fields_dict.critical_stock.grid;
		if (!grid || grid.fill_from_boms_added) return;
		grid.fill_from_boms_added = true;
		grid.add_custom_button(__("Fill From BOMs"), () => frm.trigger("fill_critical_stock"));
	},
	fill_critical_stock(frm) {
		if (frm.is_new() || frm.is_dirty()) {
			frappe.msgprint(__("Save the production line first"));
			return;
		}
		if (!(frm.doc.allowed_items || []).length) {
			frappe.msgprint(__("Add allowed items first: their BOMs give the component list"));
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.doctype.production_line.production_line.critical_stock_components",
			args: { line: frm.doc.name },
			freeze: true,
			callback: (r) => {
				const have = new Set((frm.doc.critical_stock || []).map((row) => row.item_code));
				const missing = (r.message || []).filter((row) => !have.has(row.item_code));
				missing.forEach((row) =>
					frm.add_child("critical_stock", {
						item_code: row.item_code,
						item_name: row.item_name,
						stock_uom: row.stock_uom,
						critical_qty: 0,
					})
				);
				frm.refresh_field("critical_stock");
				frappe.show_alert({
					message: missing.length
						? __("{0} component(s) added. Set their critical stock and save.", [missing.length])
						: __("All components are already listed"),
					indicator: missing.length ? "blue" : "green",
				});
			},
		});
	},
	show_critical_stock(frm) {
		const field = frm.fields_dict.critical_stock_overview;
		if (!field) return;
		if (frm.is_new() || !(frm.doc.critical_stock || []).length) {
			field.$wrapper.html("");
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.doctype.production_line.production_line.critical_stock_overview",
			args: { line: frm.doc.name },
			callback: (r) => {
				const rows = r.message || [];
				const num = (v) => format_number(v, null, 3);
				const esc = frappe.utils.escape_html;
				const low = rows.filter((row) => row.below && !row.unused).length;
				const unused = rows.filter((row) => row.unused).length;
				const body = rows
					.map((row) => {
						let state = `<span class="indicator-pill green">${__("OK")}</span>`;
						let cls = "";
						if (row.unused) {
							state = `<span class="indicator-pill gray">${__(
								"Not used by any allowed item's BOM — can be removed"
							)}</span>`;
							cls = ' class="text-muted"';
						} else if (row.below) {
							state = `<span class="indicator-pill red">${__("Below critical stock")}</span>`;
							cls = ' style="background: var(--bg-red)"';
						}
						return `<tr${cls}>
							<td>${erpnext.entity.item(row, { size: 20 })}</td>
							<td class="text-right">${num(row.free)} ${esc(row.stock_uom || "")}</td>
							<td class="text-right">${num(row.critical_qty)}</td>
							<td>${state}</td>
						</tr>`;
					})
					.join("");
				const summary = [];
				if (low)
					summary.push(`<span class="text-danger">${__("{0} below critical stock", [low])}</span>`);
				if (unused)
					summary.push(
						`<span class="text-muted">${__("{0} not needed by this line", [unused])}</span>`
					);
				field.$wrapper.html(
					`${summary.length ? `<div class="mb-2">${summary.join(" · ")}</div>` : ""}
					<table class="table table-bordered table-sm">
						<thead><tr>
							<th>${__("Component")}</th><th class="text-right">${__("Free Stock")}</th>
							<th class="text-right">${__("Critical Stock")}</th><th>${__("Status")}</th>
						</tr></thead>
						<tbody>${body}</tbody>
					</table>`
				);
				if (low) {
					frm.dashboard.set_headline(
						__("{0} component(s) below critical stock — order them in time", [low]),
						"red"
					);
				}
			},
		});
	},
	add_order_dialog(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Order"),
			size: "large",
			fields: [
				{
					fieldname: "item_code",
					fieldtype: "Link",
					label: __("Item"),
					options: "Item",
					reqd: 1,
					get_query: () => frm.allowed_item_query(frm.doc),
					onchange: () => refresh_check(),
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "qty",
					fieldtype: "Int",
					label: __("Qty"),
					reqd: 1,
					onchange: () => refresh_check(),
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "workplace",
					fieldtype: "Link",
					label: __("Workplace"),
					options: "Workplace",
					get_query: () => frm.bench_query(frm.doc),
				},
				{ fieldtype: "Section Break" },
				{ fieldname: "result", fieldtype: "HTML" },
			],
			primary_action_label: __("Add"),
			primary_action: (values) => {
				const add = () => {
					frm.add_child("orders", {
						item_code: values.item_code,
						qty: values.qty,
						workplace: values.workplace,
					});
					frm.refresh_field("orders");
					dialog.hide();
					frm.save();
				};
				const check = dialog.check_result;
				if (check && check.max_producible !== null && values.qty > check.max_producible) {
					frappe.confirm(
						__("Components on stock cover only {0} of {1}. Add the order for {1} anyway?", [
							check.max_producible,
							values.qty,
						]),
						add
					);
				} else {
					add();
				}
			},
		});
		const result = dialog.fields_dict.result.$wrapper;
		const render = (data) => {
			dialog.check_result = data;
			const num = (v) => format_number(v, null, 3);
			const esc = frappe.utils.escape_html;
			if (!data.rows.length) {
				result.html(`<div class="text-muted">${__("The BOM has no stock components")}</div>`);
				return;
			}
			const fits = data.max_producible === null || data.max_producible >= data.qty;
			const headline = `<div class="mb-2" style="font-size: var(--text-lg)">
				<span class="indicator-pill ${fits ? "green" : "red"}">
					${__("Can produce {0} of {1}", [data.max_producible ?? "∞", data.qty])}
				</span></div>`;
			const body = data.rows
				.map((row) => {
					let style = "";
					let note = "";
					if (row.short) {
						style = ' style="background: var(--bg-red)"';
						note = `<span class="text-danger">${__("short by {0}", [
							num(row.required - row.free),
						])}</span>`;
					} else if (row.below_critical) {
						style = ' style="background: var(--bg-orange)"';
						note = `<span class="text-warning">${__(
							"below critical stock after this order"
						)}</span>`;
					}
					return `<tr${style}>
						<td>${erpnext.entity.item(row, { size: 20 })}</td>
						<td class="text-right">${num(row.per_unit)}</td>
						<td class="text-right">${num(row.required)}</td>
						<td class="text-right">${num(row.free)}</td>
						<td class="text-right">${num(row.after)} ${esc(row.stock_uom || "")}</td>
						<td class="text-right">${
							row.critical_qty === null || row.critical_qty === undefined
								? "—"
								: num(row.critical_qty)
						}</td>
						<td>${note}</td>
					</tr>`;
				})
				.join("");
			result.html(
				`${headline}<table class="table table-bordered table-sm">
					<thead><tr>
						<th>${__("Component")}</th><th class="text-right">${__("Per Unit")}</th>
						<th class="text-right">${__("Required Qty")}</th><th class="text-right">${__("Free Stock")}</th>
						<th class="text-right">${__("After Order")}</th><th class="text-right">${__("Critical Stock")}</th>
						<th></th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>`
			);
		};
		const refresh_check = frappe.utils.debounce(() => {
			const { item_code, qty } = dialog.get_values(true) || {};
			if (!item_code) {
				dialog.check_result = null;
				result.html("");
				return;
			}
			frappe.call({
				method: "erpnext.manufacturing.doctype.production_line.production_line.check_order",
				args: { line: frm.doc.name, item_code, qty: qty || 1 },
				callback: (r) => r.message && render(r.message),
			});
		}, 300);
		dialog.show();
	},
});
