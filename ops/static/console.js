// Live job console.
//
// The log lives in a file on the host, so the stream is stateless and
// resumable: every SSE event carries the byte offset reached after that chunk,
// and a reconnect resumes from it. That is what lets the console survive this
// container being restarted by the very deploy it is showing.

(function () {
	"use strict";

	var current = null;

	function detach() {
		if (current && current.source) {
			current.source.close();
		}
		current = null;
	}

	function attach(wrap) {
		var jobId = wrap.getAttribute("data-job-id");
		if (!jobId) return;

		detach();

		var out = wrap.querySelector("[data-console-out]");
		var stateEl = wrap.querySelector("[data-console-state]");
		var followEl = wrap.querySelector("[data-console-follow]");

		var state = { jobId: jobId, offset: 0, source: null };
		current = state;

		function open() {
			// offset is passed explicitly as well as via Last-Event-ID: the
			// browser only sends the header on its own automatic reconnects,
			// not on the first connect after we rebuild the EventSource.
			var source = new EventSource("/jobs/" + jobId + "/stream?offset=" + state.offset);
			state.source = source;

			source.onmessage = function (event) {
				if (event.lastEventId) {
					state.offset = parseInt(event.lastEventId, 10) || state.offset;
				}
				out.textContent += event.data + "\n";
				if (!followEl || followEl.checked) {
					out.scrollTop = out.scrollHeight;
				}
			};

			source.addEventListener("done", function (event) {
				var payload = {};
				try {
					payload = JSON.parse(event.data);
				} catch (err) {
					payload = {};
				}
				if (stateEl) {
					stateEl.textContent = payload.state || "finished";
					stateEl.className = "pill " + (payload.state === "success" ? "good" : "bad");
				}
				// Without this the browser reconnects forever once the job ends.
				source.close();
				state.source = null;
				if (window.htmx) {
					["jobs", "version", "backups", "actions"].forEach(function (name) {
						var el = document.getElementById("panel-" + name);
						if (el) window.htmx.trigger(el, "load");
					});
				}
			});

			source.onerror = function () {
				if (stateEl && state.source) {
					stateEl.textContent = "reconnecting…";
					stateEl.className = "pill warn";
				}
				// EventSource retries on its own; the server resumes from
				// Last-Event-ID so nothing is lost or duplicated.
			};
		}

		open();
	}

	function scan() {
		var wrap = document.querySelector(".console-wrap[data-job-id]");
		if (!wrap) {
			detach();
			return;
		}
		if (!current || current.jobId !== wrap.getAttribute("data-job-id")) {
			attach(wrap);
		}
	}

	document.addEventListener("DOMContentLoaded", scan);
	document.body.addEventListener("htmx:afterSwap", scan);

	// Native <details> menus (.menu) don't close on outside click or on their
	// own item click — do both here instead of hand-rolling a dropdown widget.
	document.addEventListener("click", function (event) {
		document.querySelectorAll(".menu[open]").forEach(function (menu) {
			if (!menu.contains(event.target) || event.target.closest(".menu-list")) {
				menu.removeAttribute("open");
			}
		});
	});

	// Six forgotten tabs polling every 10s is ~50k SSH execs a day. Stop
	// polling while the tab is hidden; htmx resumes on the next tick when it
	// comes back.
	document.addEventListener("visibilitychange", function () {
		document.querySelectorAll("[hx-trigger*='every']").forEach(function (el) {
			if (document.hidden) {
				el.setAttribute("data-paused-trigger", el.getAttribute("hx-trigger"));
				el.setAttribute("hx-trigger", "none");
			} else if (el.hasAttribute("data-paused-trigger")) {
				el.setAttribute("hx-trigger", el.getAttribute("data-paused-trigger"));
				el.removeAttribute("data-paused-trigger");
			}
			if (window.htmx) window.htmx.process(el);
		});
	});
})();
