// Загальна таблиця для сторінок і форм: скрол усередині, липка шапка, закріплена колонка, сортування.
//
//   new erpnext.DataTable({
//       parent: $wrapper,
//       storage_key: "incapacity-cases",   // запам'ятовує закріплення колонки
//       columns: [
//           { key: "name", label: __("Case"), pin: true, html: (row) => escape(row.name) },
//           { key: "total", label: __("Total"), align: "right", html: (row) => money(row.total),
//             value: (row) => row.total, footer: money(sum) },
//       ],
//       rows: [...],
//       row_class: (row) => "text-muted",   // необов'язково
//       on_row_click: (row) => {...},        // необов'язково
//   });
//
// `html` — готова розмітка клітинки (екрануйте самі); `value` — за чим сортувати (без нього — за `row[key]`);
// `nowrap: true` — не переносити текст клітинки; `pin: true` — колонка, яку можна закріпити; `sortable: false` вимикає сортування; `footer` — підсумок.

(function () {
	const STYLE_ID = "erpnext-data-table-style";

	const CSS = `
.eg-dt-scroll { overflow: auto; max-width: 100%; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); }
.eg-dt { width: 100%; border-collapse: separate; border-spacing: 0; margin: 0; }
.eg-dt th, .eg-dt td { padding: 6px 8px; border-bottom: 1px solid var(--border-color); vertical-align: middle; background: var(--card-bg, var(--bg-color)); }
.eg-dt thead th { position: sticky; top: 0; z-index: 2; white-space: nowrap; font-weight: 600; background: var(--bg-color); }
.eg-dt tfoot td { position: sticky; bottom: 0; z-index: 2; font-weight: 600; background: var(--bg-color); border-top: 1px solid var(--border-color); border-bottom: none; }
.eg-dt-sortable { cursor: pointer; user-select: none; }
.eg-dt .text-right { text-align: right; }
.eg-dt .eg-dt-nowrap { white-space: nowrap; }
.eg-dt-clickable tbody tr { cursor: pointer; }
.eg-dt-clickable tbody tr:hover td { background: var(--bg-light-gray); }
.eg-dt-pin { margin-left: 8px; padding: 2px; color: var(--text-light); cursor: pointer; transform: rotate(45deg); }
.eg-dt-pin:hover { color: var(--text-color); }
.eg-dt-pinned .eg-dt-pin { color: var(--primary); transform: none; }
.eg-dt-pinned .eg-dt-col-pin { position: sticky; left: 0; z-index: 1; box-shadow: inset -1px 0 0 var(--border-color), 4px 0 6px -4px rgba(0, 0, 0, 0.25); }
.eg-dt-pinned thead .eg-dt-col-pin { z-index: 3; }
.eg-dt-pinned tfoot .eg-dt-col-pin { z-index: 3; }
.eg-dt-empty { padding: 24px; text-align: center; color: var(--text-muted); }
`;

	function ensure_style() {
		if (document.getElementById(STYLE_ID)) return;

		const style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = CSS;
		document.head.appendChild(style);
	}

	function remembered(key) {
		try {
			return localStorage.getItem(key);
		} catch (e) {
			return null;
		}
	}

	function remember(key, value) {
		try {
			localStorage.setItem(key, value);
		} catch (e) {
			// без сховища таблиця просто не пам'ятає закріплення
		}
	}

	erpnext.DataTable = class DataTable {
		constructor(options) {
			ensure_style();

			this.options = options;
			this.columns = options.columns || [];
			this.rows = options.rows || [];
			this.sort = null;
			this.pin_column = this.columns.find((column) => column.pin);
			this.storage_key = options.storage_key ? `eg-dt-pin-${options.storage_key}` : null;
			this.pinned = this.pin_column ? remembered(this.storage_key) !== "0" : false;

			this.$parent = $(options.parent);
			this.$scroll = $(`<div class="eg-dt-scroll"></div>`).appendTo(this.$parent.empty());

			if (options.max_height) this.$scroll.css("max-height", options.max_height);

			this.$scroll.on("click", ".eg-dt-sortable", (event) => {
				if ($(event.target).closest(".eg-dt-pin").length) return;

				this.toggle_sort($(event.currentTarget).data("key"));
			});
			this.$scroll.on("click", ".eg-dt-pin", (event) => {
				event.stopPropagation();
				this.pinned = !this.pinned;

				if (this.storage_key) remember(this.storage_key, this.pinned ? "1" : "0");

				this.render();
			});

			if (options.on_row_click) {
				this.$scroll.on("click", "tbody tr", (event) => {
					if ($(event.target).closest("a, button, input").length) return;

					options.on_row_click(this.sorted()[$(event.currentTarget).data("index")]);
				});
			}

			this.render();
		}

		set_rows(rows) {
			this.rows = rows || [];
			this.render();
		}

		toggle_sort(key) {
			if (!this.sort || this.sort.key !== key) this.sort = { key, dir: 1 };
			else if (this.sort.dir === 1) this.sort.dir = -1;
			else this.sort = null;

			this.render();
		}

		sorted() {
			if (!this.sort) return this.rows;

			const column = this.columns.find((candidate) => candidate.key === this.sort.key);
			const value = (row) => {
				const raw = column.value ? column.value(row) : row[column.key];

				return raw === null || raw === undefined ? "" : raw;
			};

			return this.rows.slice().sort((a, b) => {
				const x = value(a);
				const y = value(b);

				if (typeof x === "number" && typeof y === "number") return (x - y) * this.sort.dir;

				return String(x).localeCompare(String(y), undefined, { numeric: true }) * this.sort.dir;
			});
		}

		render() {
			const columns = this.columns;
			const pin_class = (column) => (column === this.pin_column ? " eg-dt-col-pin" : "");
			const align = (column) =>
				(column.align === "right" ? " text-right" : "") + (column.nowrap ? " eg-dt-nowrap" : "");

			const arrow = (column) => {
				if (column.sortable === false) return "";

				if (this.sort && this.sort.key === column.key)
					return `<i class="fa fa-sort-${this.sort.dir > 0 ? "asc" : "desc"}"></i>`;

				return `<i class="fa fa-sort text-muted"></i>`;
			};

			const pin = (column) =>
				column === this.pin_column
					? `<i class="fa fa-thumb-tack eg-dt-pin" title="${
							this.pinned ? __("Unpin column") : __("Pin column")
					  }"></i>`
					: "";

			const head = columns
				.map(
					(column) => `<th class="${column.sortable === false ? "" : "eg-dt-sortable"}${pin_class(
						column
					)}${align(column)}" data-key="${column.key}"${
						column.width ? ` style="min-width:${column.width}"` : ""
					}>${column.label} ${arrow(column)}${pin(column)}</th>`
				)
				.join("");

			const rows = this.sorted();
			const body = rows
				.map((row, index) => {
					const cls = this.options.row_class ? this.options.row_class(row) || "" : "";

					return `<tr data-index="${index}" class="${cls}">${columns
						.map(
							(column) =>
								`<td class="${pin_class(column).trim()}${align(column)}">${
									column.html ? column.html(row) : frappe.utils.escape_html(row[column.key] ?? "")
								}</td>`
						)
						.join("")}</tr>`;
				})
				.join("");

			const has_footer = columns.some((column) => column.footer !== undefined);
			const footer = has_footer
				? `<tfoot><tr>${columns
						.map(
							(column) =>
								`<td class="${pin_class(column).trim()}${align(column)}">${column.footer ?? ""}</td>`
						)
						.join("")}</tr></tfoot>`
				: "";

			this.$scroll
				.toggleClass("eg-dt-pinned", this.pinned)
				.toggleClass("eg-dt-clickable", !!this.options.on_row_click).html(`
				<table class="eg-dt">
					<thead><tr>${head}</tr></thead>
					<tbody>${body}</tbody>
					${footer}
				</table>
				${rows.length ? "" : `<div class="eg-dt-empty">${this.options.empty_text || __("No data")}</div>`}`);
		}
	};
})();
