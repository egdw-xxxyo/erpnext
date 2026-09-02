// Generic <dialog>-backed modal, driven purely by htmx swaps into #modal-body.
// Any button that does hx-get/hx-post with hx-target="#modal-body" opens it;
// a mutating form's success response returns an oob-emptied #modal-body,
// which this script reads as "close".
(() => {
	const dlg = document.getElementById("modal");
	const body = document.getElementById("modal-body");
	if (!dlg || !body) return;

	document.addEventListener("htmx:afterSwap", (e) => {
		if (e.detail.target !== body) return;
		if (body.innerHTML.trim()) {
			if (!dlg.open) dlg.showModal();
		} else if (dlg.open) {
			dlg.close();
		}
	});

	// Click on the ::backdrop lands on the <dialog> element itself, not its
	// content wrapper — treat that as "close".
	dlg.addEventListener("click", (e) => {
		if (e.target === dlg) dlg.close();
	});

	dlg.addEventListener("close", () => {
		body.innerHTML = "";
	});
})();
