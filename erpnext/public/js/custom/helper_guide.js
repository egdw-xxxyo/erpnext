(() => {
	if (erpnext.helper_guide) return;

	const preference = "procurement_assistant_enabled";
	const rules = new Map();
	const selections = new WeakMap();
	let dismiss;
	let mounted;
	let loading;
	function close() {
		dismiss?.();
	}

	function unmount() {
		close();
		mounted?.dispose();
		mounted = null;
	}

	function visible(element) {
		return element?.isConnected && element.getClientRects().length > 0;
	}

	function can_write(field) {
		return field?.get_status?.() === "Write" && !field.$wrapper.closest(".hide-control").length;
	}

	function reveal(field) {
		if (field.tab && !field.tab.is_active()) field.tab.set_active();
		if (field.section?.body?.hasClass("hide")) field.section.collapse(false);
		return field.$wrapper[0];
	}

	function missing(row, df) {
		const value = row[df.fieldname];
		if (df.fieldtype === "Table") return !value?.length;
		return value == null || (typeof value === "string" && !value.trim());
	}

	function field_step(field, row, message, is_missing = missing) {
		return {
			message,
			target: () => reveal(field),
			input: () => field.$input?.[0],
			done: () => !is_missing(row, field.df) || !can_write(field),
		};
	}

	function add_row_step(field, message) {
		return {
			message,
			target() {
				const wrapper = reveal(field);
				const add = field.grid.wrapper.find(".grid-add-row")[0];
				return visible(add) ? add : wrapper.querySelector(".grid-heading-row");
			},
			action: true,
		};
	}

	function row_step(field, row, df, message, is_missing = missing) {
		let control;
		let inline_row;
		let inline_column;
		let open_row = false;
		return {
			get message() {
				return open_row
					? __("Open row {0} to fill in {1}. {2}", [row.idx, __(df.label || df.fieldname), message])
					: __("Row {0}. {1}", [row.idx, message]);
			},
			get action() {
				return open_row;
			},
			target() {
				reveal(field);
				const grid = field.grid;
				if (!grid.get_row(row.name)) {
					const index = grid.data.findIndex((entry) => entry.name === row.name);
					if (index < 0) return;
					const pagination = grid.grid_pagination;
					pagination.go_to_page(Math.floor(index / pagination.page_length) + 1);
				}
				const grid_row = grid.get_row(row.name);
				if (!grid_row) return;
				if (grid_row.get_open_form() === grid_row) {
					control = grid_row.grid_form?.fields_dict[df.fieldname];
					if (can_write(control)) return reveal(control);
				}
				const column = grid_row.columns[df.fieldname];
				if (
					grid.allow_on_grid_editing() &&
					grid.is_editable() &&
					visible(column?.[0]) &&
					frappe.perm.get_field_display_status(column.df, row, grid.frm?.perm) === "Write"
				) {
					inline_row = grid_row;
					inline_column = column;
					return column[0];
				}
				open_row = true;
				control = null;
				const edit = grid_row.open_form_button?.[0];
				return visible(edit) ? edit : grid_row.row[0];
			},
			input: () => (inline_column?.field || control)?.$input?.[0],
			activate_input() {
				if (!inline_row) return;
				if (frappe.ui.form.editable_row !== inline_row) inline_row.activate();
				const input = inline_column.field;
				if (can_write(input)) return input.$input?.[0];
			},
			done: () => !is_missing(row, df),
		};
	}

	function button_step(button, message) {
		if (visible(button) && !button.disabled) return { target: () => button, message, action: true };
	}

	function menu_labels(menu) {
		return [...(menu?.[0]?.querySelectorAll(".menu-item-label") || [])].map((label) =>
			label.textContent.trim()
		);
	}

	function custom_button(frm, label, group) {
		const button = frm.custom_buttons[__(label)]?.[0];
		if (visible(button)) return button;
		const grouped = button?.closest(".inner-group-button")?.querySelector("button");
		if (visible(grouped)) return grouped;
		const menu_label = group ? `${__(group)} > ${__(label)}` : __(label);
		if (menu_labels(frm.page.menu).includes(menu_label)) {
			return frm.page.menu_btn_group.find("button")[0];
		}
	}

	function status_step(frm, message, field, selector, pose, status_element) {
		return {
			target() {
				if (field && !field.$wrapper.closest(".hide-control").length && !field.df.hidden) {
					const element = selector ? field.$wrapper.find(selector)[0] : field.$wrapper[0];
					if (element && visible(reveal(field)) && visible(element)) return element;
				}
				return [
					status_element,
					frm.page.indicator?.[0],
					frm.page.$title_area?.[0],
				].find(visible);
			},
			message,
			pose,
		};
	}

	function configured_field(frm, doc, config) {
		const [parent, child] = config.field.split(".");
		const field = frm.fields_dict[parent];
		if (!can_write(field) || (field.grid && !field.grid.is_editable())) return;
		const value_check = config.when.value || "empty";
		const needs_value = (row, df) => {
			if (value_check === "required_positive") return (missing(row, df) || !(Number(row[df.fieldname]) > 0));
			if (value_check === "required_nonnegative") return (missing(row, df) || !(Number(row[df.fieldname]) >= 0));
			return missing(row, df);
		};
		const applies = (row, df) => (value_check === "empty" || df.reqd) && needs_value(row, df);
		const message = __(config.hint);
		if (!child) {
			if (!applies(doc, field.df)) return;
			return field.grid ? add_row_step(field, message) : field_step(field, doc, message, applies);
		}
		if (!field.grid) return;
		for (const row of doc[parent] || []) {
			const fields = field.grid.get_row(row.name)?.docfields || field.grid.docfields || [];
			const df = fields.find((column) => column.fieldname === child);
			if (
				df && !df.hidden_due_to_dependency && applies(row, df) &&
				frappe.perm.get_field_display_status(df, row, field.grid.frm?.perm) === "Write"
			) {
				return row_step(field, row, df, message, applies);
			}
		}
	}

	function configured_action(frm, config) {
		const target = config.target;
		if (target.startsWith("workflow:")) {
			const label = __(target.slice("workflow:".length));
			if (menu_labels(frm.page.actions).includes(label)) {
				return button_step(frm.page.actions_btn_group.find("button")[0], __(config.hint));
			}
			return;
		}
		const labels = { save: __("Save"), submit: __("Submit"), update: __("Update") };
		const button = frm.page.btn_primary[0];
		const label = button?.getAttribute("data-label") || button?.textContent.trim();
		if (label === labels[target]) return button_step(button, __(config.hint));
	}

	function matches_field(doc, { field, operator, value }) {
		const actual = doc[field] ?? null;
		if (operator === "equals") return actual === value;
		if (operator === "not_equals") return actual !== value;
		if (operator === "in") return value.includes(actual);
		if (operator === "not_in") return !value.includes(actual);
		const empty = actual == null ||
			(typeof actual === "string" && !actual.trim()) || (Array.isArray(actual) && !actual.length);
		return operator === "empty" ? empty : !empty;
	}

	async function configured_step(frm, doc, guide) {
		const context = new Map();
		for (const config of guide.steps) {
			const { docstatus, workflow_state, role } = config.when;
			if (docstatus != null && Number(doc.docstatus || 0) !== docstatus) continue;
			if (workflow_state && doc[guide.workflow_state_field || "workflow_state"] !== workflow_state) continue;
			if (role && !frappe.user.has_role(role)) continue;
			if (config.when.fields?.some((condition) => !matches_field(doc, condition))) continue;
			let step;
			switch (config.type) {
				case "field":
					step = configured_field(frm, doc, config);
					break;
				case "action":
					step = configured_action(frm, config);
					break;
				case "wait":
					step = status_step(frm, __(config.hint), frm.fields_dict[config.target]);
					break;
				case "rule":
					step = await rules.get(config.target)?.(frm, doc, config, context);
			}
			if (step) {
				step.pose = config.emotion || step.pose;
				return step;
			}
		}
	}

	function guide_viewport(viewport) {
		const { clientHeight, clientWidth } = document.documentElement;
		const left = viewport?.offsetLeft ?? 0;
		const top = viewport?.offsetTop ?? 0;
		return {
			left,
			top,
			right: left + (viewport?.width ?? clientWidth),
			bottom: top + (viewport?.height ?? clientHeight),
		};
	}

	function scroll_to_target(anchor, viewport, signal, smooth) {
		const horizontal = anchor.closest(".form-grid-container, .cpo-route-scroll");
		if (horizontal && horizontal.scrollWidth > horizontal.clientWidth) {
			const { left, right } = anchor.getBoundingClientRect();
			const start = horizontal.getBoundingClientRect().left + horizontal.clientLeft;
			const end = start + horizontal.clientWidth;
			const offset = left < start ? left - start : Math.max(0, right - end);
			if (offset) horizontal.scrollBy({ left: offset, behavior: "instant" });
		}

		const main = anchor.closest(".main-section");
		const pane =
			anchor.closest(".grid-form-body") || (main && main.scrollHeight > main.clientHeight ? main : null);
		const { top, height } = anchor.getBoundingClientRect();
		const { top: viewport_top, bottom: viewport_bottom } = guide_viewport(viewport);
		const pane_top = pane ? pane.getBoundingClientRect().top + pane.clientTop : viewport_top;
		const center = (Math.max(viewport_top, pane_top) +
			Math.min(viewport_bottom, pane ? pane_top + pane.clientHeight : viewport_bottom)) / 2;
		const scroller = pane || document.scrollingElement;
		const start = scroller.scrollTop;
		const end = Math.max(
			0,
			Math.min(start + top + height / 2 - center, scroller.scrollHeight - scroller.clientHeight)
		);
		const distance = Math.abs(end - start);
		if (!smooth || distance < 2) {
			scroller.scrollTo({ top: end, behavior: "instant" });
			return;
		}

		const duration = Math.min(280, 110 + distance * 0.4);
		return new Promise((resolve) => {
			let started;
			function scroll(time) {
				if (signal.aborted) {
					resolve();
					return;
				}
				started ??= time;
				const progress = Math.min((time - started) / duration, 1);
				const eased = 1 - (1 - progress) ** 3;
				scroller.scrollTo({ top: start + (end - start) * eased, behavior: "instant" });
				if (progress < 1) requestAnimationFrame(scroll);
				else resolve();
			}
			requestAnimationFrame(scroll);
		});
	}

	function fly_in(mascot, viewport) {
		const { top, right, bottom, left } = guide_viewport(viewport);
		const rect = mascot.getBoundingClientRect();
		const landing_x = rect.left + rect.width / 2;
		const landing_y = rect.top + rect.height / 2;
		const edge_x = left + (right - left) * (0.22 + 0.56 * Math.random());
		const edge_y = top + (bottom - top) * (0.22 + 0.56 * Math.random());
		const starts = [
			[left - rect.width / 2 - 8, edge_y],
			[right + rect.width / 2 + 8, edge_y],
			[edge_x, top - rect.height / 2 - 8],
			[edge_x, bottom + rect.height / 2 + 8],
		];
		const [x, y] = starts[Math.floor(Math.random() * starts.length)];
		const dx = x - landing_x;
		const dy = y - landing_y;
		const distance = Math.hypot(dx, dy);
		const bend = Math.min(distance * 0.26, 130) * (Math.random() < 0.5 ? -1 : 1);
		const control_x = dx * 0.46 - (dy / distance) * bend;
		const control_y = dy * 0.46 + (dx / distance) * bend;
		const bank = bend < 0 ? -13 : 13;
		// Sample a quadratic Bézier curve from the chosen edge to the hint.
		const keyframes = Array.from({ length: 25 }, (_, i) => {
			const t = i / 24;
			const rest = 1 - t;
			const tx = rest ** 2 * dx + 2 * rest * t * control_x;
			const ty = rest ** 2 * dy + 2 * rest * t * control_y;
			return {
				transform: `translate(${tx}px, ${ty}px) rotate(${bank * rest}deg) scale(${0.8 + 0.2 * t})`,
			};
		});
		return mascot.animate(keyframes, {
			delay: 55,
			duration: Math.min(650, 400 + distance * 0.16),
			easing: "cubic-bezier(.38, .05, .23, 1)",
			fill: "backwards",
		});
	}

	function show_hint(frm, step, trigger, mascot_settings) {
		const anchor = step.target();
		if (!visible(anchor)) return;
		const layer = $(`<div class="procurement-guide is-preparing">
			<div class="procurement-guide-outline"></div>
			<div class="procurement-guide-hint">
				<img width="256" height="171" alt="">
				<div class="procurement-guide-bubble" inert>
					<div class="procurement-guide-copy">
						<div id="procurement-guide-message" role="status"></div>
					</div>
					<button type="button" class="procurement-guide-close">×</button>
				</div>
			</div>
		</div>`).appendTo(document.body)[0];
		const hint = layer.querySelector(".procurement-guide-hint");
		const mascot = hint.querySelector("img");
		const bubble = layer.querySelector(".procurement-guide-bubble");
		const outline = layer.querySelector(".procurement-guide-outline");
		const exit = layer.querySelector(".procurement-guide-close");
		layer.classList.toggle("is-grid", Boolean(anchor.closest(".form-in-grid")));
		layer.dataset.pose = step.pose || mascot_settings.default_emotion;
		mascot.src = mascot_settings.emotions[layer.dataset.pose] || mascot_settings.emotions[mascot_settings.default_emotion];
		const message = layer.querySelector("[role=status]");
		message.textContent = step.hint || step.message;
		if (step.decisions?.length) {
			const decisions = $('<ul class="procurement-guide-decisions"></ul>').appendTo(message);
			for (const decision of step.decisions) $('<li></li>').text(decision).appendTo(decisions);
		}
		exit.setAttribute("aria-label", __("Close assistant hint"));

		const controller = new AbortController();
		const { signal } = controller;
		let skip;
		if (step.skip) {
			skip = $('<button type="button" class="btn btn-xs btn-default procurement-guide-skip"></button>')
				.text(__("Skip"))
				.insertAfter(message)[0];
			skip.addEventListener("click", () => {
				step.skip();
				trigger.click();
			}, { signal });
		}
		const focus = skip || (step.action && anchor.matches("button, a") ? anchor : exit);
		const description = "procurement-guide-message";
		const descriptions = new Map();
		function describe(element) {
			if (!element || descriptions.has(element)) return;
			const previous = element.getAttribute("aria-describedby");
			descriptions.set(element, previous);
			element.setAttribute("aria-describedby", [previous, description].filter(Boolean).join(" "));
		}
		let frame;
		let motion;
		let positioned = false;
		const observer = new MutationObserver(schedule);
		const resize = new ResizeObserver(schedule);
		const viewport = window.visualViewport;
		let selecting = false;

		dismiss = (restore = false) => {
			dismiss = null;
			controller.abort();
			motion?.cancel();
			observer.disconnect();
			resize.disconnect();
			cancelAnimationFrame(frame);
			$(frm.wrapper).off("dirty.procurement-assistant", schedule);
			layer.remove();
			for (const [element, previous] of descriptions) {
				if (previous) element.setAttribute("aria-describedby", previous);
				else element.removeAttribute("aria-describedby");
			}
			if (restore && visible(trigger)) trigger.focus({ preventScroll: true });
		};

		function position() {
			frame = null;
			if (step.done?.() || !visible(anchor)) {
				close();
				return;
			}
			if (!positioned) return;
			const rect = anchor.getBoundingClientRect();
			const container = anchor
				.closest(".form-grid-container, .grid-form-body, .cpo-route-scroll")
				?.getBoundingClientRect();
			const { left: viewport_left, top: viewport_top, right: viewport_right, bottom: screen_bottom } =
				guide_viewport(viewport);
			const viewport_width = viewport_right - viewport_left;
			const viewport_height = screen_bottom - viewport_top;
			const viewport_bottom = Math.min(
				screen_bottom,
				anchor.closest(".main-section")?.getBoundingClientRect().bottom ?? Infinity
			);
			const top = Math.max(viewport_top + 5, (container?.top ?? 0) - 4, rect.top - 4);
			const bottom = Math.min(viewport_bottom - 5, (container?.bottom ?? Infinity) + 4, rect.bottom + 4);
			const left = Math.max(viewport_left + 5, (container?.left ?? 0) - 4, rect.left - 4);
			const right = Math.min(viewport_right - 5, (container?.right ?? Infinity) + 4, rect.right + 4);
			layer.hidden = bottom <= top || right <= left;
			if (layer.hidden) {
				motion?.finish();
				return;
			}
			Object.assign(outline.style, {
				top: `${top}px`,
				left: `${left}px`,
				width: `${right - left}px`,
				height: `${bottom - top}px`,
			});
			const gap = Math.min(12, viewport_width / 4, viewport_height / 4);
			hint.style.maxWidth = `${Math.min(380, viewport_width - 2 * gap)}px`;
			hint.style.maxHeight = "";
			const space_below = viewport_bottom - bottom - 2 * gap;
			const space_above = top - viewport_top - 2 * gap;
			const above = hint.offsetHeight > space_below && space_above > space_below;
			hint.style.maxHeight = `${Math.max(0, above ? space_above : space_below)}px`;
			const hint_width = hint.offsetWidth;
			const x = Math.max(viewport_left + gap, Math.min(left, viewport_right - hint_width - gap));
			const y = above ? top - hint.offsetHeight - gap : bottom + gap;
			if (
				motion && (Math.abs(parseFloat(hint.style.left) - x) >= 1 || Math.abs(parseFloat(hint.style.top) - y) >= 1)
			) {
				motion.finish();
			}
			hint.style.left = `${x}px`;
			hint.style.top = `${y}px`;
		}

		function schedule() {
			if (frame == null) frame = requestAnimationFrame(position);
		}

		exit.addEventListener("click", () => dismiss?.(true), { signal });
		exit.addEventListener("keydown", (event) => {
			if (event.key === "Tab" && !event.shiftKey) {
				let input = step.input?.();
				if (!visible(input)) input = step.activate_input?.();
				if (!visible(input)) return;
				event.preventDefault();
				describe(input);
				input.focus({ preventScroll: true });
			}
		}, { signal });
		anchor.addEventListener("focusin", ({ target }) => {
			if (!bubble.inert && target === step.input?.()) describe(target);
		}, { signal });
		document.addEventListener("keydown", (event) => {
			if (event.key !== "Escape" || selecting || document.querySelector(".modal.show, .datepicker.-active-")) return;
			event.preventDefault();
			event.stopImmediatePropagation();
			dismiss?.(true);
		}, { capture: true, signal });
		for (const name of ["awesomplete-open", "awesomplete-close"]) {
			anchor.addEventListener(name, () => {
				selecting = name === "awesomplete-open";
				layer.classList.toggle("is-selecting", selecting);
				if (selecting && positioned) motion?.finish();
			}, { signal });
		}
		if (step.action) anchor.addEventListener("click", close, { signal });
		window.addEventListener("scroll", schedule, { capture: true, signal });
		window.addEventListener("resize", schedule, { signal });
		viewport?.addEventListener("resize", schedule, { signal });
		viewport?.addEventListener("scroll", schedule, { signal });
		$(frm.wrapper).on("dirty.procurement-assistant", schedule);
		observer.observe(frm.wrapper, { childList: true, subtree: true });
		resize.observe(anchor);
		resize.observe(hint);

		async function introduce() {
			const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
			const initial_focus = document.activeElement;
			const loaded = smooth ? mascot.decode().then(() => true, () => false) : null;
			if (smooth) {
				motion = layer.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 100, easing: "ease-out" });
				await motion.finished.catch(() => {});
				motion = null;
			}
			if (signal.aborted) return;
			if (!anchor.closest(".page-head")) {
				const scrolling = scroll_to_target(anchor, viewport, signal, smooth);
				if (scrolling) await scrolling;
			}
			if (signal.aborted) return;
			positioned = true;
			position();
			if (signal.aborted) return;
			layer.classList.remove("is-preparing");
			if (loaded && (await loaded) && !signal.aborted && !layer.hidden && !selecting) {
				layer.classList.add("is-flying");
				motion = fly_in(mascot, viewport);
				await motion.finished.catch(() => {});
				motion = null;
			}
			if (signal.aborted) return;
			layer.classList.remove("is-flying");
			layer.classList.add("is-landed");
			bubble.inert = false;
			describe(focus);
			describe(step.input?.());
			if (!layer.hidden && !selecting && document.activeElement === initial_focus) {
				focus.focus({ preventScroll: true });
			}
		}
		introduce();
	}

	function mount(frm, data) {
		unmount();
		const column = frm.page.main[0].parentElement;
		const controls = $('<div class="procurement-assistant-controls" hidden></div>').appendTo(column)[0];
		const next = $('<button type="button" class="btn btn-sm procurement-assistant-next"></button>')
			.text(__("Suggest my next action"))
			.appendTo(controls)[0];
		const switch_guide = $('<button type="button" class="btn btn-sm procurement-assistant-switch" hidden></button>')
			.html(frappe.utils.icon("chevron-down"))
			.appendTo(controls)[0];
		const { guides, mascot, workflow_state_field } = data;
		let selected = guides.length === 1 ? guides[0] : guides.find((item) => item.name === selections.get(frm.doc));
		let chooser;
		const toggle = $(`<button type="button" class="btn btn-default icon-btn text-muted procurement-assistant-toggle">
			<svg class="icon" viewBox="0 0 24 20" aria-hidden="true">
				<g fill="none" stroke="currentColor" stroke-width="1.4">
					<ellipse cx="7.1" cy="4.9" rx="4.5" ry="2.6" transform="rotate(25 7.1 4.9)" />
					<ellipse cx="5.4" cy="11.9" rx="4.3" ry="2.7" transform="rotate(13 5.4 11.9)" />
					<ellipse cx="18.6" cy="8" rx="4.2" ry="2.5" transform="rotate(29 18.6 8)" />
					<ellipse cx="17.3" cy="15.3" rx="4.2" ry="2.5" transform="rotate(29 17.3 15.3)" />
				</g>
				<path fill="currentColor" stroke="none" fill-rule="evenodd"
					d="M8.3 9.1c.5-2.7 2.7-4.1 5.4-3.4 2.9.7 4.3 2.9 3.9 5.3-.4 2.6-2.9 4.5-5.5 4-2.6-.5-4.3-3-3.8-5.9Zm8 1.6c-.2-1.3-1.3-2-2.7-1.7-1.5.3-2.4 1.4-2.2 2.6.2 1.3 1.3 2 2.7 1.7 1.4-.3 2.4-1.4 2.2-2.6Z" />
				<circle cx="14.6" cy="11" r="0.9" fill="currentColor" stroke="none" />
			</svg>
			<span aria-hidden="true">?</span>
		</button>`)[0];
		const wrapper = $(frm.wrapper);
		const icon_group = frm.page.icon_group[0];
		const menu = frm.page.menu_btn_group[0];
		const controller = new AbortController();
		const { signal } = controller;
		const place_toggle = () => {
			const wiki = icon_group.querySelector(".doc-help-btn");
			if (visible(wiki)) {
				if (wiki.nextElementSibling !== toggle) wiki.after(toggle);
			} else if (menu.previousElementSibling !== toggle) {
				menu.before(toggle);
			}
		};
		const toolbar_observer = new MutationObserver(place_toggle);
		toolbar_observer.observe(icon_group, { childList: true });
		window.addEventListener("resize", place_toggle, { signal });
		const place_next = () => {
			const { left, right, width } = column.getBoundingClientRect();
			const inset = getComputedStyle(column).direction === "rtl"
				? left
				: document.documentElement.clientWidth - right;
			controls.style.setProperty("--procurement-assistant-inline-end", `${Math.max(0, inset)}px`);
			controls.style.setProperty("--procurement-assistant-column-width", `${width}px`);
		};
		const column_observer = new ResizeObserver(place_next);
		column_observer.observe(column);
		column_observer.observe(document.documentElement);
		wrapper.on("hide.procurement-assistant", unmount);
		mounted = {
			route: frappe.get_route().join("/"),
			dispose() {
				controller.abort();
				toolbar_observer.disconnect();
				column_observer.disconnect();
				wrapper.off("hide.procurement-assistant", unmount);
				toggle.remove();
				controls.remove();
				chooser?.hide();
			},
		};

		let request;
		const update = () => {
			const enabled = sessionStorage.getItem(preference) === "1";
			if (enabled) place_next();
			controls.hidden = !enabled;
			switch_guide.hidden = guides.length < 2 || !selected;
			const switch_label = selected ? __("Change Guide ({0})", [selected.title]) : __("Change Guide");
			switch_guide.title = switch_label;
			switch_guide.setAttribute("aria-label", switch_label);
			const label = enabled ? __("Disable {0}", [mascot.name]) : __("Enable {0}", [mascot.name]);
			toggle.setAttribute("aria-label", label);
			toggle.setAttribute("aria-pressed", String(enabled));
			toggle.title = label;
		};
		toggle.addEventListener("click", () => {
			close();
			request = null;
			sessionStorage.setItem(preference, controls.hidden ? "1" : "0");
			update();
		}, { signal });
		function choose_guide(trigger) {
			if (chooser) return;
			close();
			const dialog = new frappe.ui.Dialog({
				title: __("How can I help?"),
				fields: [{ fieldtype: "HTML", fieldname: "guides" }],
				keep_grid_form_open: true,
			});
			chooser = dialog;
			const list = $('<div class="list-group list-group-flush"></div>').appendTo(dialog.fields_dict.guides.$wrapper);
			let chosen;
			for (const option of guides) {
				$('<button type="button" class="list-group-item list-group-item-action"></button>')
					.text(option.title)
					.attr("aria-pressed", String(option === selected))
					.appendTo(list)
					.on("click", () => {
						chosen = option;
						dialog.hide();
					});
			}
			dialog.$wrapper.one("hidden.bs.modal", () => {
				dialog.$wrapper.remove();
				chooser = null;
				if (signal.aborted || controls.hidden) return;
				trigger.focus({ preventScroll: true });
				if (chosen) {
					selected = chosen;
					selections.set(frm.doc, chosen.name);
					update();
					next.click();
				}
			});
			dialog.show();
		}
		switch_guide.addEventListener("click", () => choose_guide(switch_guide), { signal });
		next.addEventListener("click", async () => {
			if (!selected) {
				choose_guide(next);
				return;
			}
			close();
			const doc = frm.doc;
			const route = frappe.get_route().join("/");
			const token = (request = {});
			const current = () =>
				request === token && next.isConnected && !controls.hidden && frm.doc === doc &&
				frappe.get_route().join("/") === route;
			next.setAttribute("aria-busy", "true");
			next.disabled = true;
			switch_guide.disabled = true;
			try {
				await frappe.after_ajax();
				if (!current()) return;
				const step = await configured_step(frm, doc, { steps: selected.steps, workflow_state_field });
				if (!current()) return;
				if (step) show_hint(frm, step, next, mascot);
				else frappe.show_alert({ message: __("There is no matching guide step for this document.") });
			} catch {
				if (current()) {
					frappe.show_alert({ message: __("Could not load the next step. Try again."), indicator: "orange" });
				}
			} finally {
				next.disabled = false;
				switch_guide.disabled = false;
				next.removeAttribute("aria-busy");
			}
		}, { signal });
		place_toggle();
		update();
	}

	erpnext.helper_guide = {
		has_rule: (name) => rules.has(name),
		register_rule: (name, resolve) => rules.set(name, resolve),
		visible, can_write, field_step, add_row_step, row_step, button_step, menu_labels, custom_button, status_step,
	};

	$(document).on("form-refresh.helper-guide", async (_, frm) => {
		unmount();
		if (frm.meta.istable || !frm.page?.main?.length) return;
		const route = frappe.get_route().join("/");
		const doc = frm.doc;
		const request = (loading = {});
		try {
			const data = await frappe.xcall(
				"erpnext.setup.helper_guides.get_active_guides", { target_doctype: frm.doctype }, "GET", { silent: true }
			);
			if (loading === request && frm.doc === doc && frappe.get_route().join("/") === route && data?.guides.length) {
				mount(frm, data);
			}
		} catch {
			// A form stays usable when its guide cannot be loaded.
		}
	});
	frappe.router.on("change", () => {
		if (mounted && mounted.route !== frappe.get_route().join("/")) unmount();
		else close();
	});
})();
