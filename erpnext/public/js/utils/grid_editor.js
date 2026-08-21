// Grid row editing the way the desk prototypes did it: the expanded row loses the
// "Insert Below" button (a payroll table has a fixed set of rows) and gains a plain
// close button, so the accountant does not have to hunt for the collapse arrow.

frappe.provide("erpnext.utils.grid_editor");

const CLOSE_CLASS = "erpnext-grid-row-close";

function compact_row_actions(frm) {
	paint_open_rows();

	if (frm.__grid_editor_observer) return;

	// frm.wrapper is a plain node on a form and a jQuery object in a few other layouts
	const wrapper = frm.wrapper;
	const target = (wrapper && (wrapper.get ? wrapper.get(0) : wrapper)) || document.body;

	// the observer watches the whole form, and the grid rewrites rows in bursts:
	// repaint once per frame instead of once per mutation
	let queued = false;

	frm.__grid_editor_observer = new MutationObserver(() => {
		if (queued) return;

		queued = true;
		window.requestAnimationFrame(() => {
			queued = false;
			paint_open_rows();
		});
	});
	frm.__grid_editor_observer.observe(target, { childList: true, subtree: true });
}

function paint_open_rows() {
	$(".grid-row-open").each(function () {
		const $row = $(this);

		hide_insert_below($row);
		add_close_button($row);
	});
}

function hide_insert_below($row) {
	$row.find("button").each(function () {
		const $button = $(this);

		if ([__("Insert Below"), "Insert Below"].includes($.trim($button.text()))) {
			$button.hide();
		}
	});
}

function add_close_button($row) {
	if ($row.find(`.${CLOSE_CLASS}`).length) return;

	const $button = $(
		`<button class="btn btn-secondary btn-xs ${CLOSE_CLASS}" type="button">${__("Close")}</button>`
	);

	$button.on("click", () => {
		const grid_row = $row.closest(".grid-row").data("grid_row");

		if (grid_row && grid_row.toggle_view) {
			grid_row.toggle_view(false);
			return;
		}

		$row.find(".grid-row-close, .btn-close").first().trigger("click");
	});

	const $toolbar = $row.find(".grid-row-actions").first();

	if ($toolbar.length) {
		$toolbar.prepend($button);
		return;
	}

	$row.find(".row-index").first().after($button);
}

Object.assign(erpnext.utils.grid_editor, { compact_row_actions });
