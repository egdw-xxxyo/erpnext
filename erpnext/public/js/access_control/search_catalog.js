frappe.provide("erpnext.access_control");

erpnext.access_control.search_catalog = (() => {
	const METHOD = "erpnext.access_control.catalog.search_inaccessible";
	const MIN_CHARS = 3;
	const SEARCH_INPUT = "#navbar-search";
	const states = new WeakMap();

	const blank_state = () => ({
		seq: 0,
		items: [],
		total: 0,
		expanded: false,
		active: -1,
	});

	const state_of = (input) => {
		if (!states.has(input)) states.set(input, blank_state());
		return states.get(input);
	};

	const query_of = (input) => input.value.trim().replace(/\s\s+/g, " ");

	const block_of = (input) => {
		const $container = $(input).closest(".awesomplete");
		const $existing = $container.children(".access-catalog");
		return $existing.length
			? $existing
			: $('<div class="access-catalog" hidden></div>').appendTo($container);
	};

	const input_of = (element) => $(element).closest(".awesomplete").find(SEARCH_INPUT).get(0);

	const row_count = (state) => 1 + (state.expanded ? state.items.length : 0);

	const own_count = (input) => (input.awesomplete?.opened ? input.awesomplete.ul.children.length : 0);

	const header_html = (state) => `
		<div class="access-catalog-row access-catalog-header" data-row="0"
			role="option" aria-expanded="${state.expanded}">
			<i class="fa fa-chevron-${state.expanded ? "down" : "right"} access-catalog-chevron"></i>
			<i class="fa fa-lock text-muted"></i>
			<span>${__("No access")}</span>
			<span class="access-catalog-count">${state.total}</span>
			<span class="access-catalog-hint text-muted">${__("Open an item to request access")}</span>
		</div>`;

	const item_html = (item, index) => `
		<div class="access-catalog-row access-catalog-item" data-row="${index + 1}"
			role="option" title="${frappe.utils.escape_html(__("No access. Open to request it"))}">
			<i class="fa fa-lock text-muted"></i>
			<span class="access-catalog-title ellipsis">${frappe.utils.escape_html(item.title)}</span>
			<span class="access-catalog-kind text-muted">${frappe.utils.escape_html(item.kind)}</span>
		</div>`;

	const more_html = (state) =>
		state.total > state.items.length
			? `<div class="access-catalog-more text-muted">${__(
					"Showing {0} of {1}. Refine the search to see the rest",
					[state.items.length, state.total]
			  )}</div>`
			: "";

	const items_html = (state) =>
		state.expanded
			? `<div class="access-catalog-items">${state.items.map(item_html).join("")}${more_html(
					state
			  )}</div>`
			: "";

	const set_active = (input, row) => {
		const state = state_of(input);
		state.active = row;
		const $rows = block_of(input).find("[data-row]");
		$rows.removeClass("active");
		const $current = $rows.filter(`[data-row="${row}"]`).addClass("active");
		$current.get(0)?.scrollIntoView({ block: "nearest" });
	};

	const render = (input) => {
		const state = state_of(input);
		const $block = block_of(input);
		$block.prop("hidden", !state.total);
		$block.html(state.total ? header_html(state) + items_html(state) : "");
		set_active(input, Math.min(state.active, row_count(state) - 1));
	};

	const toggle = (input) => {
		const state = state_of(input);
		state.expanded = !state.expanded;
		render(input);
	};

	const open = (input, item, event) => {
		if (event && (event.ctrlKey || event.metaKey)) frappe.open_in_new_tab = true;
		input.value = "";
		$(input).trigger("blur").closest(".modal").modal("hide");
		frappe.set_route(item.route);
	};

	const leave_to_list = (input, index) => {
		set_active(input, -1);
		input.awesomplete.goto(index);
	};

	const enter_block = (input, row) => {
		input.awesomplete?.goto(-1);
		set_active(input, row);
	};

	const key_outside = (input, key) => {
		const count = own_count(input);
		const index = input.awesomplete?.index ?? -1;
		const last = row_count(state_of(input)) - 1;
		const target = {
			ArrowDown: !count || index === count - 1 ? 0 : null,
			ArrowUp: !count || index === 0 ? last : null,
		}[key];
		if (target === undefined || target === null) return false;
		enter_block(input, target);
		return true;
	};

	const move_down = (input, state, count) =>
		state.active < row_count(state) - 1
			? set_active(input, state.active + 1)
			: count && leave_to_list(input, 0);

	const move_up = (input, state, count) =>
		state.active > 0 ? set_active(input, state.active - 1) : count && leave_to_list(input, count - 1);

	const collapse = (input, state) => {
		state.active = 0;
		toggle(input);
	};

	const key_inside = (input, key, event) => {
		const state = state_of(input);
		const count = own_count(input);
		const on_header = state.active === 0;
		const actions = {
			ArrowDown: () => move_down(input, state, count),
			ArrowUp: () => move_up(input, state, count),
			ArrowRight: on_header && !state.expanded ? () => toggle(input) : null,
			ArrowLeft: state.expanded ? () => collapse(input, state) : null,
			Enter: () => (on_header ? toggle(input) : open(input, state.items[state.active - 1], event)),
		};
		if (!actions[key]) return false;
		actions[key]();
		return true;
	};

	const on_keydown = (event) => {
		const input = event.target;
		if (input.id !== "navbar-search" || !states.has(input) || !state_of(input).total) return;
		const handled =
			state_of(input).active === -1
				? key_outside(input, event.key)
				: key_inside(input, event.key, event);
		if (!handled) return;
		event.preventDefault();
		event.stopImmediatePropagation();
	};

	const fetch = frappe.utils.debounce((input, seq, txt) => {
		frappe
			.xcall(METHOD, { txt })
			.then(({ total, items }) => {
				const state = state_of(input);
				if (seq !== state.seq) return;
				Object.assign(state, { total, items });
				render(input);
			})
			.catch(() => {});
	}, 250);

	const on_input = (event) => {
		const input = event.target;
		const state = state_of(input);
		const txt = query_of(input);
		state.seq += 1;
		state.active = -1;
		if (txt.length >= MIN_CHARS) {
			fetch(input, state.seq, txt);
			return;
		}
		Object.assign(state, { total: 0, items: [] });
		render(input);
	};

	const on_modal_hidden = (event) => {
		$(event.target)
			.find(SEARCH_INPUT)
			.toArray()
			.filter((input) => states.has(input))
			.forEach((input) => {
				states.set(input, { ...blank_state(), seq: state_of(input).seq + 1 });
				render(input);
			});
	};

	const on_header_click = (event) => toggle(input_of(event.currentTarget));

	const on_item_click = (event) => {
		const input = input_of(event.currentTarget);
		const row = Number(event.currentTarget.dataset.row);
		open(input, state_of(input).items[row - 1], event);
	};

	const add_style = () => {
		if (document.getElementById("access-catalog-style")) return;
		const style = document.createElement("style");
		style.id = "access-catalog-style";
		style.textContent = `
			.access-catalog {
				margin-top: var(--margin-sm);
				padding-top: var(--padding-xs);
				border-top: 1px solid var(--border-color);
			}
			.access-catalog-row {
				display: flex;
				align-items: center;
				gap: var(--margin-sm);
				padding: var(--padding-sm);
				border-radius: var(--border-radius);
				color: var(--text-color);
				font-size: var(--text-sm);
				cursor: pointer;
			}
			.access-catalog-row:hover,
			.access-catalog-row.active {
				background-color: var(--awesomplete-hover-bg);
			}
			.access-catalog-chevron {
				width: 10px;
				color: var(--text-muted);
			}
			.access-catalog-count {
				padding: 0 6px;
				border-radius: var(--border-radius-full);
				background-color: var(--subtle-fg);
				font-size: var(--text-xs);
			}
			.access-catalog-hint,
			.access-catalog-kind {
				margin-left: auto;
				font-size: var(--text-xs);
				white-space: nowrap;
			}
			.access-catalog-title {
				min-width: 0;
			}
			.access-catalog-items {
				max-height: 240px;
				overflow-y: auto;
			}
			.access-catalog-item {
				padding-left: calc(var(--padding-sm) + 18px);
			}
			.access-catalog-more {
				padding: var(--padding-xs) var(--padding-sm);
				font-size: var(--text-xs);
			}
		`;
		document.head.appendChild(style);
	};

	const setup = () => {
		add_style();
		document.addEventListener("keydown", on_keydown, true);
		$(document)
			.on("input", SEARCH_INPUT, on_input)
			.on("hidden.bs.modal", ".modal", on_modal_hidden)
			.on("mousedown", ".access-catalog", (event) => event.preventDefault())
			.on("click", ".access-catalog-header", on_header_click)
			.on("click", ".access-catalog-item", on_item_click);
	};

	setup();

	return { render };
})();
