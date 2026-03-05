// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Workplace", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.trigger("prepare_dashboard");
		}
	},

	prepare_dashboard(frm) {
		let $parent = $(frm.fields_dict["workplace_dashboard"].wrapper);
		$parent.empty();

		new WorkplaceDashboard({
			wrapper: $parent,
			frm: frm,
		});
	},
});

class WorkplaceDashboard {
	constructor({ wrapper, frm }) {
		this.$wrapper = $(wrapper);
		this.frm = frm;
		this.timer_job_cards = {};

		this.load_job_cards();
	}

	load_job_cards() {
		this.frm.call({
			method: "get_job_cards",
			doc: this.frm.doc,
			callback: (r) => {
				this.job_cards = r.message || [];
				this.render();
			},
		});
	}

	render() {
		let template = frappe.render_template("workplace_dashboard", {
			data: this.job_cards,
		});

		this.$wrapper.html(template);
		this.setup_barcode_fields();
		this.setup_menu_actions();
		this.prepare_timer();
		this.bind_events();
	}

	setup_barcode_fields() {
		this.scan_field = frappe.ui.form.make_control({
			df: {
				label: __("Scan Barcode"),
				fieldtype: "Data",
				options: "Barcode",
				placeholder: __("Scan Job Card or Item Barcode"),
			},
			parent: this.$wrapper.find(".qrcode-fields"),
			render_input: true,
		});

		this.scan_field.$wrapper.addClass("form-column col-sm-6");

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
		// First check if it matches a visible Job Card name
		let match = this.job_cards.find((jc) => jc.name === barcode);
		if (match) {
			this.highlight_job_card(match.name);
			return;
		}

		// Call backend to search by barcode
		this.frm.call({
			method: "find_job_card_by_barcode",
			doc: this.frm.doc,
			args: { barcode: barcode },
			callback: (r) => {
				if (r.message && r.message.length) {
					let found = r.message[0];
					// Check if it's already in the dashboard
					let visible = this.job_cards.find((jc) => jc.name === found.name);
					if (visible) {
						this.highlight_job_card(found.name);
					} else {
						frappe.msgprint({
							title: __("Job Card Found"),
							message: __("Job Card {0} for {1} ({2})", [
								`<a href="/app/job-card/${found.name}">${found.name}</a>`,
								found.production_item,
								found.operation,
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

	highlight_job_card(job_card_name) {
		let $card = this.$wrapper.find(`[data-name='${job_card_name}']`);
		$card[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
		$card.addClass("workplace-highlight");
		setTimeout(() => $card.removeClass("workplace-highlight"), 3000);
	}

	setup_menu_actions() {
		this.job_cards.forEach((data) => {
			let $btns = this.$wrapper.find(`.workplace-job-card-link[data-name='${data.name}']`);

			$btns.find(".btn-resume").hide();
			$btns.find(".btn-pause").hide();
			$btns.find(".btn-complete .btn").attr("disabled", true);

			let has_pending_qty = data.for_quantity + data.process_loss_qty > data.total_completed_qty;

			if (has_pending_qty) {
				if (!data.time_logs?.length) {
					$btns.find(".btn-start").show();
				} else {
					let last_log = data.time_logs[data.time_logs.length - 1];
					if (last_log.to_time) {
						// Last log is closed, can start again or complete
						$btns.find(".btn-start").show();
						$btns.find(".btn-complete").show();
						$btns.find(".btn-complete .btn").attr("disabled", false);
					} else {
						// Timer is running
						$btns.find(".btn-start").hide();
						$btns.find(".btn-pause").show();
						$btns.find(".btn-complete").show();
						$btns.find(".btn-complete .btn").attr("disabled", false);
					}
				}
			}
		});
	}

	bind_events() {
		this.$wrapper.find(".btn-start").on("click", (e) => {
			let job_card = $(e.currentTarget).closest("div").attr("data-job-card");
			this.start_job(job_card);
		});

		this.$wrapper.find(".btn-pause").on("click", (e) => {
			let job_card = $(e.currentTarget).closest("div").attr("data-job-card");
			this.update_job_card(job_card, "pause_job", {
				end_time: frappe.datetime.now_datetime(),
			});
		});

		this.$wrapper.find(".btn-resume").on("click", (e) => {
			let job_card = $(e.currentTarget).closest("div").attr("data-job-card");
			this.update_job_card(job_card, "resume_job", {
				start_time: frappe.datetime.now_datetime(),
			});
		});

		this.$wrapper.find(".btn-complete").on("click", (e) => {
			let job_card = $(e.currentTarget).closest("div").attr("data-job-card");
			let for_quantity = $(e.currentTarget).attr("data-qty");
			this.complete_job(job_card, for_quantity);
		});
	}

	start_job(job_card) {
		// Auto-detect employee from workplace config — no prompt needed
		this.frm.call({
			method: "get_current_employee",
			doc: this.frm.doc,
			callback: (r) => {
				let employee = r.message;
				if (!employee) {
					frappe.msgprint(__("No employee linked to your user in this workplace. Please add yourself to the Employees tab."));
					return;
				}

				this.update_job_card(job_card, "start_timer", {
					start_time: frappe.datetime.now_datetime(),
					employees: [{ employee: employee }],
				});
			},
		});
	}

	complete_job(job_card, for_quantity) {
		frappe.prompt(
			{
				fieldname: "qty",
				label: __("Completed Quantity"),
				fieldtype: "Float",
				reqd: 1,
				default: flt(for_quantity || 0),
			},
			(data) => {
				if (flt(data.qty) <= 0) {
					frappe.throw(__("Quantity should be greater than 0"));
				}

				this.update_job_card(job_card, "complete_job_card", {
					qty: flt(data.qty),
					end_time: frappe.datetime.now_datetime(),
					auto_submit: 1,
				});
			},
			__("Enter Value"),
			__("Submit")
		);
	}

	update_job_card(job_card, method, data) {
		frappe.call({
			method: "erpnext.manufacturing.doctype.workstation.workstation.update_job_card",
			args: {
				job_card: job_card,
				method: method,
				start_time: data.start_time || "",
				employees: data.employees || [],
				end_time: data.end_time || "",
				qty: data.qty || 0,
				auto_submit: data.auto_submit || 0,
			},
			callback: () => {
				$.each(this.timer_job_cards, (index, value) => {
					clearInterval(value);
				});
				this.timer_job_cards = {};
				this.load_job_cards();
			},
		});
	}

	prepare_timer() {
		this.job_cards.forEach((data) => {
			if (data.time_logs?.length) {
				data._current_time = this.get_current_time(data);
				if (data.time_logs[cint(data.time_logs.length) - 1].to_time || data.is_paused) {
					this.update_stopwatch(data);
				} else {
					this.initialise_timer(data);
				}
			}
		});
	}

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

		let $timer = this.$wrapper.find(`[data-job-card='${data.name}']`);
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
