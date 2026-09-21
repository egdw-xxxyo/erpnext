// Spinner on whatever button started an htmx request, removed when it settles.
(() => {
	const ICON = '<i class="fa fa-spinner fa-spin busy-icon" aria-hidden="true"></i>';

	function buttonFor(detail) {
		const elt = detail.elt;
		if (!elt) return null;
		if (elt.tagName === "BUTTON") return elt;
		if (elt.tagName !== "FORM") return null;
		const ev = detail.requestConfig && detail.requestConfig.triggeringEvent;
		return (ev && ev.submitter) || elt.querySelector('button[type="submit"]');
	}

	document.addEventListener("htmx:beforeRequest", (e) => {
		const btn = buttonFor(e.detail);
		if (!btn || btn.dataset.busy) return;
		btn.dataset.busy = btn.disabled ? "was-disabled" : "1";
		btn.insertAdjacentHTML("afterbegin", ICON);
		btn.disabled = true;
	});

	document.addEventListener("htmx:afterRequest", (e) => {
		const btn = buttonFor(e.detail);
		if (!btn || !btn.dataset.busy) return;
		btn.querySelectorAll(".busy-icon").forEach((i) => i.remove());
		btn.disabled = btn.dataset.busy === "was-disabled";
		delete btn.dataset.busy;
	});
})();
