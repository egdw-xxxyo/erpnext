// Search + select input: [data-combo] wraps an <input> and a listbox of options.
// Delegated on document so it survives htmx swaps of the panel it lives in.
(() => {
	const options = (combo) => [...combo.querySelectorAll("li[data-value]")];
	const visible = (combo) => options(combo).filter((li) => !li.hidden);

	function open(combo) {
		combo.querySelector(".combo-list").hidden = false;
		combo.querySelector("input").setAttribute("aria-expanded", "true");
	}

	function close(combo) {
		combo.querySelector(".combo-list").hidden = true;
		combo.querySelector("input").setAttribute("aria-expanded", "false");
		options(combo).forEach((li) => li.classList.remove("active"));
	}

	function filter(combo, query) {
		const q = query.trim().toLowerCase();
		options(combo).forEach((li) => {
			li.hidden = q !== "" && !li.dataset.value.toLowerCase().includes(q);
			li.classList.remove("active");
		});
		const empty = combo.querySelector(".combo-empty");
		if (empty) empty.hidden = visible(combo).length > 0;
	}

	function pick(combo, li) {
		const input = combo.querySelector("input");
		input.value = li.dataset.value;
		close(combo);
		input.focus();
	}

	function move(combo, step) {
		const items = visible(combo);
		if (!items.length) return;
		const idx = items.findIndex((li) => li.classList.contains("active"));
		items.forEach((li) => li.classList.remove("active"));
		const next = items[(idx + step + items.length) % items.length];
		next.classList.add("active");
		next.scrollIntoView({ block: "nearest" });
	}

	document.addEventListener("focusin", (e) => {
		const combo = e.target.closest && e.target.closest("[data-combo]");
		if (!combo || e.target.tagName !== "INPUT") return;
		filter(combo, "");
		open(combo);
		e.target.select();
	});

	document.addEventListener("focusout", (e) => {
		const combo = e.target.closest && e.target.closest("[data-combo]");
		if (combo && !combo.contains(e.relatedTarget)) close(combo);
	});

	document.addEventListener("input", (e) => {
		const combo = e.target.closest && e.target.closest("[data-combo]");
		if (!combo) return;
		filter(combo, e.target.value);
		open(combo);
	});

	document.addEventListener("mousedown", (e) => {
		const li = e.target.closest && e.target.closest("[data-combo] li[data-value]");
		if (!li) return;
		e.preventDefault();
		pick(li.closest("[data-combo]"), li);
	});

	document.addEventListener("keydown", (e) => {
		const combo = e.target.closest && e.target.closest("[data-combo]");
		if (!combo) return;
		const list = combo.querySelector(".combo-list");
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			if (list.hidden) open(combo);
			move(combo, e.key === "ArrowDown" ? 1 : -1);
		} else if (e.key === "Enter" && !list.hidden) {
			const active = combo.querySelector("li.active");
			if (active) {
				e.preventDefault();
				pick(combo, active);
			}
		} else if (e.key === "Escape" && !list.hidden) {
			e.preventDefault();
			close(combo);
		}
	});

	// The actions panel re-renders every 15s; skip that while someone is picking
	// a branch so the typed value and open list are not wiped mid-edit.
	document.addEventListener("htmx:beforeRequest", (e) => {
		if (e.detail.elt.id !== "panel-actions") return;
		const busy = [...e.detail.elt.querySelectorAll("[data-combo] input")].some(
			(input) => input === document.activeElement || input.value !== input.dataset.default
		);
		if (busy) e.preventDefault();
	});
})();
