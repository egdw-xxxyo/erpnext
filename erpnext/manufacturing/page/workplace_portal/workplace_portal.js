const API = "erpnext.manufacturing.page.workplace_portal.workplace_portal";

frappe.pages["workplace-portal"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Workplace Portal"),
		single_column: true,
	});

	new WorkplacePortal({
		wrapper: $(wrapper).find(".layout-main-section"),
		page: page,
	});
};

class WorkplacePortal {
	constructor({ wrapper, page }) {
		this.$wrapper = wrapper;
		this.page = page;
		this.workplace = null;
		this.timer_job_cards = {};
		this.active_job_card = null;
		this.detail_controls = {};

		let url_params = new URLSearchParams(window.location.search);
		let wp_param = url_params.get("workplace");
		let jc_param = url_params.get("job_card");
		if (jc_param) {
			this.active_job_card = jc_param;
		}

		this.$switcher = $('<div class="workplace-switcher" style="padding:10px 15px;border-bottom:1px solid var(--border-color);"></div>');
		this.$wrapper.append(this.$switcher);

		this.$content = $('<div class="workplace-portal-content"></div>');
		this.$wrapper.append(this.$content);

		this.initial_workplace = wp_param || null;
		this.setup_switcher();
	}

	setup_switcher() {
		frappe.call({
			method: API + ".get_workplaces",
			callback: (r) => {
				let workplaces = r.message || [];
				if (workplaces.length === 0) {
					this.$content.html(
						'<div class="text-muted text-center" style="padding:30px;">' +
						__("No active Workplaces found. Create one first.") +
						'</div>'
					);
					return;
				}

				this.render_switcher(workplaces);

				if (this.initial_workplace) {
					this.select_workplace(this.initial_workplace);
				} else if (workplaces.length === 1) {
					this.select_workplace(workplaces[0].name);
				}
			},
		});
	}

	render_switcher(workplaces) {
		this.$switcher.empty();
		let $row = $('<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;"></div>');

		workplaces.forEach((wp) => {
			let $btn = $(`<button class="btn btn-default btn-sm workplace-switch-btn" data-workplace="${frappe.utils.escape_html(wp.name)}">${frappe.utils.escape_html(wp.name)}</button>`);
			$btn.on("click", () => {
				this.select_workplace(wp.name);
			});
			$row.append($btn);
		});

		this.$switcher.append($row);
	}

	update_switcher_active() {
		this.$switcher.find(".workplace-switch-btn").each((i, el) => {
			let $el = $(el);
			if ($el.attr("data-workplace") === this.workplace) {
				$el.removeClass("btn-default").addClass("btn-primary");
			} else {
				$el.removeClass("btn-primary").addClass("btn-default");
			}
		});
	}

	select_workplace(name) {
		this.workplace = name;
		this.page.set_title(__("Workplace Portal") + " \u2014 " + name);
		this.update_switcher_active();
		this.update_url();
		this.$content.empty();
		this.active_job_card = null;
		this.clear_timers();
		this.detail_controls = {};
		this.load_job_cards();
	}

	// === DATA LOADING ===

	load_job_cards() {
		frappe.call({
			method: API + ".get_job_cards",
			args: { workplace: this.workplace },
			callback: (r) => {
				this.job_cards = r.message || [];
				this.render();
			},
		});
	}

	render() {
		this.$content.empty();

		this.$content.html(`
			<div class="workplace-list-view">
				<div class="qrcode-fields" style="padding:10px 15px;"></div>
				<div class="my-jc-section" style="padding:0 15px 15px;">
					<h6 style="margin:15px 0 8px;font-weight:600;">${__("My Job Cards")}</h6>
					<div class="my-jc-table"></div>
				</div>
				<div class="other-jc-section" style="padding:0 15px 15px;">
					<h6 style="margin:15px 0 8px;font-weight:600;">${__("Other Job Cards")}</h6>
					<div class="other-jc-table"></div>
				</div>
			</div>
			<div class="workplace-detail-view" style="display:none;"></div>
		`);

		if (this.active_job_card) {
			let jc = this.job_cards.find((j) => j.name === this.active_job_card);
			if (jc) {
				this.render_detail_view(jc);
				return;
			}
			this.active_job_card = null;
			this.update_url();
		}

		this.render_list_view();
	}

	get_datatable_columns() {
		return [
			{ name: __("Job Card"), editable: false, width: 140 },
			{ name: __("Item"), editable: false, width: 160 },
			{ name: __("Operation"), editable: false, width: 140 },
			{ name: __("Qty"), editable: false, width: 80 },
			{ name: __("Employee"), editable: false, width: 160 },
			{ name: __("Status"), editable: false, width: 120, format: (value) => {
				let color_map = {
					"Not Started": "gray", "Open": "gray", "Work In Progress": "orange",
					"On Hold": "yellow", "Completed": "green",
				};
				let color = color_map[value] || "blue";
				return `<span class="badge badge-${color}">${__(value)}</span>`;
			}},
		];
	}

	format_jc_row(d) {
		let emp_names = (d.assigned_employees || []).map((e) => e.employee_name).join(", ");
		return [
			d.name,
			d.production_item,
			d.operation,
			`${d.for_quantity} ${d.fg_uom || ""}`,
			emp_names,
			d.status === "Open" ? "Not Started" : d.status,
		];
	}

	render_list_view() {
		this.$content.find(".workplace-list-view").show();
		this.$content.find(".workplace-detail-view").hide();

		this.setup_barcode_field();

		if (!this.job_cards || !this.job_cards.length) {
			this.$content.find(".my-jc-section").hide();
			this.$content.find(".other-jc-section").html(
				'<div class="text-muted text-center" style="padding:30px;">' +
				__("No Job Cards found for the configured operations") + '</div>'
			);
			return;
		}

		let user_employee = this.job_cards[0]?.user_employee;
		let my_cards = [];
		let other_cards = [];

		this.job_cards.forEach((d) => {
			let is_mine = (d.assigned_employees || []).some((e) => e.employee === user_employee);
			if (is_mine) {
				my_cards.push(d);
			} else {
				other_cards.push(d);
			}
		});

		let columns = this.get_datatable_columns();

		if (my_cards.length) {
			this.$content.find(".my-jc-section").show();
			this.my_datatable = new frappe.DataTable(
				this.$content.find(".my-jc-table").get(0),
				{
					columns: columns,
					data: my_cards.map((d) => this.format_jc_row(d)),
					dynamicRowHeight: true,
					checkboxColumn: false,
					inlineFilters: true,
					layout: "fluid",
					cellHeight: 36,
				}
			);
			this.bind_datatable_click(this.my_datatable, my_cards);
		} else {
			this.$content.find(".my-jc-section").hide();
		}

		if (other_cards.length) {
			this.$content.find(".other-jc-section").show();
			this.other_datatable = new frappe.DataTable(
				this.$content.find(".other-jc-table").get(0),
				{
					columns: columns,
					data: other_cards.map((d) => this.format_jc_row(d)),
					dynamicRowHeight: true,
					checkboxColumn: false,
					inlineFilters: true,
					layout: "fluid",
					cellHeight: 36,
				}
			);
			this.bind_datatable_click(this.other_datatable, other_cards);
		} else {
			this.$content.find(".other-jc-section").hide();
		}
	}

	bind_datatable_click(datatable, cards) {
		let scope = datatable.style.scopeClass;
		$(`.${scope} .dt-scrollable`).on("click", ".dt-row", (e) => {
			let $row = $(e.currentTarget);
			let row_index = $row.attr("data-row-index");
			if (row_index !== undefined) {
				let jc = cards[parseInt(row_index)];
				if (jc) this.open_job_card(jc.name);
			}
		});
	}

	setup_barcode_field() {
		let $qr = this.$content.find(".qrcode-fields");
		if (!$qr.length) return;

		this.scan_field = frappe.ui.form.make_control({
			df: {
				label: __("Scan Barcode"),
				fieldtype: "Data",
				options: "Barcode",
				placeholder: __("Scan Job Card, Serial Number or Item Barcode"),
			},
			parent: $qr,
			render_input: true,
		});
		this.scan_field.$wrapper.addClass("col-sm-6");

		this.scan_field.$input.on("input", () => {
			clearTimeout(this._scan_timeout);
			this._scan_timeout = setTimeout(() => {
				let barcode = this.scan_field.get_value();
				if (barcode) {
					this.handle_barcode_scan(barcode);
					this.scan_field.set_value("");
				}
			}, 300);
		});
	}

	handle_barcode_scan(barcode) {
		let match = this.job_cards.find((jc) => jc.name === barcode);
		if (match) {
			this.open_job_card(match.name);
			return;
		}

		frappe.call({
			method: API + ".find_job_card_by_barcode",
			args: { workplace: this.workplace, barcode: barcode },
			callback: (r) => {
				if (r.message && r.message.length) {
					let found = r.message[0];
					let visible = this.job_cards.find((jc) => jc.name === found.name);
					if (visible) {
						this.open_job_card(found.name);
					} else {
						frappe.msgprint({
							title: __("Job Card Found"),
							message: __("Job Card {0} for {1} ({2})", [
								found.name, found.production_item, found.operation,
							]),
							indicator: "blue",
						});
					}
				} else {
					frappe.show_alert({
						message: __("No matching Job Card found for barcode: {0}", [barcode]),
						indicator: "orange",
					});
				}
			},
		});
	}

	// === DETAIL VIEW ===

	open_job_card(name) {
		this.active_job_card = name;
		this.update_url();
		let jc = this.job_cards.find((j) => j.name === name);
		if (jc) {
			this.render_detail_view(jc);
		}
	}

	close_job_card() {
		this.clear_timers();
		this.active_job_card = null;
		this.detail_controls = {};
		this.update_url();
		this.load_job_cards();
	}

	update_url() {
		let url = new URL(window.location);
		if (this.workplace) {
			url.searchParams.set("workplace", this.workplace);
		} else {
			url.searchParams.delete("workplace");
		}
		if (this.active_job_card) {
			url.searchParams.set("job_card", this.active_job_card);
		} else {
			url.searchParams.delete("job_card");
		}
		window.history.replaceState({}, "", url);
	}

	render_detail_view(jc) {
		this.$content.find(".workplace-list-view").hide();
		let $detail = this.$content.find(".workplace-detail-view");
		$detail.show();

		let status_label = jc.status;
		if (status_label === "Open") status_label = "Not Started";

		let html = `
		<div class="workplace-back-link">
			<a class="btn-back-to-list">\u2190 ${__("Back to list")}</a>
		</div>
		<div class="workplace-detail-header">
			<div style="display:flex;justify-content:space-between;align-items:center;">
				<a class="jc-title" href="/app/job-card/${encodeURIComponent(jc.name)}" style="color:inherit;text-decoration:underline;">${jc.name}</a>
				<span class="badge badge-${jc.status_colour}">${__(status_label)}</span>
			</div>
			<div class="jc-subtitle">
				${jc.production_item} \u00b7 ${jc.for_quantity} ${jc.fg_uom || ""} \u00b7 ${jc.operation}
			</div>
			${jc.serial_no ? `<div class="jc-serial-numbers" style="margin-top:6px;font-size:12px;color:var(--text-muted);">
				<strong>${__("Serial No")}:</strong> ${frappe.utils.escape_html(jc.serial_no).replace(/\n/g, ", ")}
			</div>` : ""}
			<div style="display:flex;align-items:center;gap:12px;margin-top:8px;">
				<div class="timer" data-job-card="${frappe.utils.escape_html(jc.name)}" style="font-size:16px;font-weight:600;">
					<span class="hours">00</span>:<span class="minutes">00</span>:<span class="seconds">00</span>
				</div>
				<div class="detail-employees" style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;">
					${(jc.assigned_employees || []).map((emp) =>
						`<span class="badge badge-secondary employee-badge"
							data-job-card="${jc.name}" data-employee="${emp.employee}"
							title="${__("Click to unassign")}">
							${emp.employee_name} \u2715
						</span>`
					).join("")}
					<button class="btn btn-xs btn-default btn-assign" data-job-card="${jc.name}" title="${__("Assign Employee")}">+</button>
				</div>
			</div>
		</div>
		<div class="detail-fields-container"></div>
		<div class="workplace-detail-actions" data-job-card="${jc.name}">
			<div class="btn-start" data-job-card="${jc.name}">
				<button class="btn btn-primary btn-sm">${__("Start")}</button>
			</div>
			<div class="btn-pause" data-job-card="${jc.name}" style="display:none;">
				<button class="btn btn-warning btn-sm">${__("Pause")}</button>
			</div>
			<div class="btn-resume" data-job-card="${jc.name}" style="display:none;">
				<button class="btn btn-default btn-sm">${__("Resume")}</button>
			</div>
			<div class="btn-save" data-job-card="${jc.name}">
				<button class="btn btn-default btn-sm">${__("Save")}</button>
			</div>
			<div class="btn-complete" data-job-card="${jc.name}"
				data-qty="${jc.for_quantity}">
				<button class="btn btn-success btn-sm" disabled>${__("Complete")}</button>
			</div>
		</div>`;

		$detail.html(html);

		this.setup_detail_fields(jc, $detail.find(".detail-fields-container"));
		this.setup_detail_actions(jc, $detail);
		this.setup_detail_timer(jc);
		this.bind_detail_events(jc, $detail);
	}

	setup_detail_fields(jc, $container) {
		this.detail_controls = {};
		let fields = jc.custom_fields || [];
		if (!fields.length) return;

		let saved_data = jc.custom_data || {};

		fields.forEach((cf) => {
			if (cf.fieldtype === "Link" && cf.link_doctype) {
				if (cf.multiple) {
					this.render_multi_link_field(jc, cf, $container, saved_data);
				} else {
					this.render_single_link_field(jc, cf, $container, saved_data);
				}
			} else {
				this.render_standard_field(jc, cf, $container, saved_data);
			}
		});
	}

	parse_link_filters(raw) {
		if (!raw) return {};
		let parsed;
		try { parsed = JSON.parse(raw); } catch(e) { return {}; }

		let tuples = [];
		if (Array.isArray(parsed) && parsed.length === 3 && typeof parsed[0] === "string") {
			tuples = [parsed];
		} else if (parsed.and) {
			tuples = parsed.and;
		} else if (typeof parsed === "object" && !Array.isArray(parsed)) {
			return parsed;
		}

		let filters = {};
		tuples.forEach(([field, op, value]) => {
			if (op === "=") {
				filters[field] = value;
			} else {
				filters[field] = [op, value];
			}
		});
		return filters;
	}

	render_single_link_field(jc, cf, $container, saved_data) {
		let is_workstation = cf.link_doctype === "Workstation";
		let current_value = is_workstation ? (jc.plog_workstation || "") : (saved_data[cf.fieldname] || "");

		let scan_col = cf.show_barcode_scanner ? '<div class="col-sm-4 link-scan-input"></div>' : "";
		let $section = $(`
			<div class="workplace-detail-section">
				<div class="row">
					${scan_col}
					<div class="col-sm-6 link-select-input"></div>
				</div>
			</div>
		`);
		$container.append($section);

		let filters = this.parse_link_filters(cf.link_scan_filters);

		let on_value_change = (val) => {
			if (is_workstation && val) {
				this.do_set_workstation(jc.name, val, $section);
			}
		};

		let link_df = {
			fieldtype: "Link",
			fieldname: cf.fieldname + "_link",
			label: cf.label,
			options: cf.link_doctype,
			reqd: cf.reqd,
			change: function() {
				let val = link_ctrl.get_value();
				on_value_change(val);
			},
		};
		if (Object.keys(filters).length) {
			link_df.get_query = () => ({ filters: filters });
		}

		let link_ctrl = frappe.ui.form.make_control({
			df: link_df,
			parent: $section.find(".link-select-input"),
			render_input: true,
		});

		if (current_value) {
			link_ctrl.set_value(current_value);
		}

		if (!is_workstation) {
			this.detail_controls[cf.fieldname] = link_ctrl;
		}

		if (cf.show_barcode_scanner) {
			let scan_ctrl = frappe.ui.form.make_control({
				df: {
					fieldtype: "Data",
					options: "Barcode",
					placeholder: __("Scan barcode"),
				},
				parent: $section.find(".link-scan-input"),
				render_input: true,
			});

			scan_ctrl.$input.on("input", () => {
				clearTimeout(this._link_scan_timeout);
				this._link_scan_timeout = setTimeout(() => {
					let val = scan_ctrl.get_value();
					if (val) {
						if (is_workstation) {
							this.resolve_and_set_workstation(jc.name, val, $section);
						} else {
							link_ctrl.set_value(val);
						}
						scan_ctrl.set_value("");
					}
				}, 300);
			});
		}
	}

	resolve_and_set_workstation(job_card, barcode, $section) {
		frappe.call({
			method: API + ".resolve_workstation_barcode",
			args: { barcode: barcode },
			callback: (r) => {
				if (r.message && r.message.workstation) {
					this.do_set_workstation(job_card, r.message.workstation, $section);
				} else {
					frappe.show_alert({
						message: __("No workstation found for: {0}", [barcode]),
						indicator: "orange",
					});
				}
			},
		});
	}

	do_set_workstation(job_card, workstation, $section) {
		frappe.call({
			method: API + ".set_workstation",
			args: { workplace: this.workplace, job_card: job_card, workstation: workstation },
			callback: (r) => {
				if (r.message) {
					let $input = $section.find("input[data-fieldtype='Link']");
					if ($input.length) {
						$input.val(r.message.workstation).trigger("change");
					}
					let jc = this.job_cards.find((j) => j.name === job_card);
					if (jc) jc.plog_workstation = r.message.workstation;
					frappe.show_alert({
						message: __("Workstation set: {0}", [r.message.workstation]),
						indicator: "green",
					});
				}
			},
		});
	}

	render_multi_link_field(jc, cf, $container, saved_data) {
		let reqd_mark = cf.reqd ? '<span class="text-danger"> *</span>' : "";
		let json_filters = this.parse_link_filters(cf.link_scan_filters);

		// Current values stored as comma-separated in readings
		let current_csv = saved_data[cf.fieldname] || "";
		let selected_values = current_csv ? current_csv.split(",").map((v) => v.trim()).filter(Boolean) : [];

		let scan_col = cf.show_barcode_scanner ? '<div class="col-sm-4 multi-scan-input"></div>' : "";
		let $section = $(`
			<div class="workplace-detail-section">
				<div class="section-label">${cf.label}${reqd_mark}</div>
				<div class="row">
					${scan_col}
					<div class="col-sm-4 multi-link-input"></div>
				</div>
				<div class="multi-values" style="margin-top:8px;"></div>
			</div>
		`);
		$container.append($section);

		let render_badges = () => {
			let $container = $section.find(".multi-values");
			let html = "";
			selected_values.forEach((val, idx) => {
				html += `<span class="material-badge" data-idx="${idx}">
					${frappe.utils.escape_html(val)}
					<span class="remove-multi-value" data-idx="${idx}" title="${__("Remove")}">\u2715</span>
				</span>`;
			});
			$container.html(html);
			$container.find(".remove-multi-value").on("click", (e) => {
				e.stopPropagation();
				let idx = parseInt($(e.currentTarget).attr("data-idx"));
				selected_values.splice(idx, 1);
				render_badges();
				update_control_value();
			});
		};

		let update_control_value = () => {
			let csv = selected_values.join(", ");
			// Store in detail_controls for save_custom_data
			this.detail_controls[cf.fieldname] = { get_value: () => csv };
		};

		if (cf.show_barcode_scanner) {
			let scan_ctrl = frappe.ui.form.make_control({
				df: {
					fieldtype: "Data",
					options: "Barcode",
					placeholder: __("Scan barcode"),
				},
				parent: $section.find(".multi-scan-input"),
				render_input: true,
			});

			scan_ctrl.$input.on("input", () => {
				clearTimeout(this._multi_scan_timeout);
				this._multi_scan_timeout = setTimeout(() => {
					let val = scan_ctrl.get_value();
					if (val && !selected_values.includes(val)) {
						selected_values.push(val);
						render_badges();
						update_control_value();
					}
					scan_ctrl.set_value("");
				}, 300);
			});
		}

		let link_df = {
			fieldtype: "Link",
			options: cf.link_doctype,
			placeholder: __("Select"),
		};
		if (Object.keys(json_filters).length) {
			link_df.get_query = () => ({ filters: json_filters });
		}

		let link_ctrl = frappe.ui.form.make_control({
			df: link_df,
			parent: $section.find(".multi-link-input"),
			render_input: true,
		});

		link_ctrl.$input.on("change", () => {
			let val = link_ctrl.get_value();
			if (val && !selected_values.includes(val)) {
				selected_values.push(val);
				render_badges();
				update_control_value();
				link_ctrl.set_value("");
			}
		});

		render_badges();
		update_control_value();
	}

	render_standard_field(jc, cf, $container, saved_data) {
		let reqd_mark = cf.reqd ? '<span class="text-danger"> *</span>' : "";

		let $section = $(`
			<div class="workplace-detail-section">
				<div class="row">
					<div class="col-sm-6">
						<label class="control-label" style="font-size:11px;">${cf.label}${reqd_mark}</label>
						<div class="field-control" data-fieldname="${cf.fieldname}"></div>
					</div>
				</div>
			</div>
		`);
		$container.append($section);

		let df = {
			fieldtype: cf.fieldtype || "Data",
			fieldname: cf.fieldname,
			placeholder: cf.label,
		};
		if (cf.fieldtype === "Select" && cf.options) {
			df.options = "\n" + cf.options;
		}

		let control = frappe.ui.form.make_control({
			df: df,
			parent: $section.find(`.field-control[data-fieldname='${cf.fieldname}']`),
			render_input: true,
		});

		if (saved_data[cf.fieldname]) {
			control.set_value(saved_data[cf.fieldname]);
		}

		this.detail_controls[cf.fieldname] = control;
	}

	save_custom_data(job_card) {
		let custom_data = {};
		Object.keys(this.detail_controls).forEach((fn) => {
			custom_data[fn] = this.detail_controls[fn].get_value();
		});
		frappe.call({
			method: API + ".save_custom_data",
			args: { workplace: this.workplace, job_card: job_card, custom_data: JSON.stringify(custom_data) },
			callback: () => {
				let jc = this.job_cards.find((j) => j.name === job_card);
				if (jc) jc.custom_data = Object.assign({}, custom_data);
				frappe.show_alert({ message: __("Saved"), indicator: "green" });
			},
		});
	}

	// === DETAIL ACTIONS ===

	setup_detail_actions(jc, $detail) {
		let $actions = $detail.find(".workplace-detail-actions");
		$actions.find(".btn-resume").hide();
		$actions.find(".btn-pause").hide();
		$actions.find(".btn-complete .btn").attr("disabled", true);

		let has_pending = jc.for_quantity + jc.process_loss_qty > jc.total_completed_qty;
		if (has_pending) {
			if (!jc.time_logs?.length) {
				$actions.find(".btn-start").show();
			} else {
				let last = jc.time_logs[jc.time_logs.length - 1];
				if (last.to_time) {
					$actions.find(".btn-start").show();
					$actions.find(".btn-complete .btn").attr("disabled", false);
				} else {
					$actions.find(".btn-start").hide();
					$actions.find(".btn-pause").show();
					$actions.find(".btn-complete .btn").attr("disabled", false);
				}
			}
		}
	}

	setup_detail_timer(jc) {
		if (jc.time_logs?.length) {
			jc._current_time = this.get_current_time(jc);
			let last = jc.time_logs[jc.time_logs.length - 1];
			if (last.to_time || jc.is_paused) {
				this.update_stopwatch(jc);
			} else {
				this.initialise_timer(jc);
			}
		}
	}

	bind_detail_events(jc, $detail) {
		$detail.find(".btn-back-to-list").on("click", () => this.close_job_card());

		$detail.find(".btn-save").on("click", () => this.save_custom_data(jc.name));

		$detail.find(".btn-start").on("click", () => this.start_job(jc.name));

		$detail.find(".btn-pause").on("click", () => {
			frappe.call({
				method: API + ".pause_job",
				args: { job_card: jc.name, end_time: frappe.datetime.now_datetime() },
				callback: () => this.reload_dashboard(),
			});
		});

		$detail.find(".btn-resume").on("click", () => {
			frappe.call({
				method: API + ".resume_job",
				args: { job_card: jc.name, start_time: frappe.datetime.now_datetime() },
				callback: () => this.reload_dashboard(),
			});
		});

		$detail.find(".btn-complete").on("click", () => {
			this.try_complete_job(jc);
		});

		$detail.find(".btn-assign").on("click", () => this.assign_employee(jc.name));

		$detail.find(".employee-badge").on("click", (e) => {
			let employee = $(e.currentTarget).attr("data-employee");
			this.unassign_employee(jc.name, employee);
		});
	}

	try_complete_job(jc) {
		let custom_data = {};
		let missing = [];

		Object.keys(this.detail_controls).forEach((fn) => {
			custom_data[fn] = this.detail_controls[fn].get_value();
		});

		(jc.custom_fields || []).forEach((cf) => {
			// Workstation link is validated server-side via production log
			if (cf.fieldtype === "Link" && cf.link_doctype === "Workstation" && !cf.multiple) return;
			if (cf.reqd && !custom_data[cf.fieldname]) {
				missing.push(cf.label);
			}
		});

		if (missing.length) {
			frappe.msgprint({
				title: __("Missing Required Fields"),
				message: missing.join(", "),
				indicator: "red",
			});
			return;
		}

		let save_and_complete = () => {
			this.complete_job(jc.name, jc.for_quantity);
		};

		if (Object.keys(custom_data).length) {
			frappe.call({
				method: API + ".save_custom_data",
				args: { workplace: this.workplace, job_card: jc.name, custom_data: JSON.stringify(custom_data) },
				callback: save_and_complete,
			});
		} else {
			save_and_complete();
		}
	}

	// === SHARED METHODS ===

	assign_employee(job_card) {
		frappe.prompt(
			{ fieldtype: "Link", label: __("Employee"), options: "Employee", fieldname: "employee", reqd: 1 },
			(data) => {
				frappe.call({
					method: API + ".assign_employee",
					args: { job_card: job_card, employee: data.employee },
					callback: () => this.reload_dashboard(),
				});
			},
			__("Assign Employee"), __("Assign")
		);
	}

	unassign_employee(job_card, employee) {
		frappe.call({
			method: API + ".unassign_employee",
			args: { job_card: job_card, employee: employee },
			callback: () => this.reload_dashboard(),
		});
	}

	start_job(job_card) {
		frappe.call({
			method: API + ".get_current_employee",
			args: { workplace: this.workplace },
			callback: (r) => {
				let employee = r.message;
				if (!employee) {
					frappe.prompt(
						{ fieldtype: "Link", label: __("Select Employee"), options: "Employee", fieldname: "employee", reqd: 1 },
						(data) => this.do_start_job(job_card, data.employee),
						__("No employee linked to your user"), __("Start")
					);
					return;
				}
				this.do_start_job(job_card, employee);
			},
		});
	}

	do_start_job(job_card, employee) {
		frappe.call({
			method: API + ".start_job",
			args: { job_card: job_card, employee: employee, start_time: frappe.datetime.now_datetime() },
			callback: () => this.reload_dashboard(),
		});
	}

	complete_job(job_card, for_quantity) {
		frappe.prompt(
			{ fieldname: "qty", label: __("Completed Quantity"), fieldtype: "Float", reqd: 1, default: flt(for_quantity || 0) },
			(data) => {
				if (flt(data.qty) <= 0) {
					frappe.throw(__("Quantity should be greater than 0"));
				}
				frappe.call({
					method: API + ".complete_job",
					args: { workplace: this.workplace, job_card: job_card, qty: flt(data.qty), end_time: frappe.datetime.now_datetime() },
					callback: () => {
						this.active_job_card = null;
						this.reload_dashboard();
					},
				});
			},
			__("Enter Value"), __("Submit")
		);
	}

	reload_dashboard() {
		this.clear_timers();
		this.detail_controls = {};
		this.load_job_cards();
	}

	clear_timers() {
		$.each(this.timer_job_cards, (index, value) => clearInterval(value));
		this.timer_job_cards = {};
	}

	// === TIMER ===

	initialise_timer(data) {
		let timeout = setInterval(() => {
			data._current_time += 1;
			this.update_stopwatch(data);
		}, 1000);
		this.timer_job_cards[data.name] = timeout;
	}

	update_stopwatch(data) {
		let increment = data._current_time;
		let hours = Math.floor(increment / 3600);
		let minutes = Math.floor((increment - hours * 3600) / 60);
		let seconds = cint(increment - hours * 3600 - minutes * 60);

		let $timer = this.$content.find(`[data-job-card='${data.name}'] .timer, .timer[data-job-card='${data.name}']`);
		$timer.find(".hours").text(hours < 10 ? "0" + hours : hours);
		$timer.find(".minutes").text(minutes < 10 ? "0" + minutes : minutes);
		$timer.find(".seconds").text(seconds < 10 ? "0" + seconds : seconds);
	}

	get_current_time(data) {
		let current_time = 0.0;
		data.time_logs.forEach((d) => {
			if (d.to_time) {
				if (d.time_in_mins) {
					current_time += flt(d.time_in_mins, 2) * 60;
				} else {
					current_time += moment(d.to_time).diff(d.from_time, "seconds");
				}
			} else {
				current_time += moment(frappe.datetime.now_datetime()).diff(d.from_time, "seconds");
			}
		});
		return current_time;
	}
}
