frappe.ui.form.on("Production Line", {
	refresh(frm) {
		frm.trigger("show_workplaces");
		frm.trigger("show_orders");
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
	},
});
