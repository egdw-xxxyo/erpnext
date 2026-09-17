// Live job console.
//
// The log lives in a file on the host, so the stream is stateless and
// resumable: every SSE event carries the byte offset reached after that chunk,
// and a reconnect resumes from it. That is what lets the console survive this
// container being restarted by the very deploy it is showing.

(function () {
	"use strict";

	var current = null;

	// [OPS] <ts> <phase> <start|ok|fail|skip> <text> — milestone markers the
	// deploy scripts print. The stream replays the log from offset 0, so this
	// reconstructs the phase without a second round-trip to the host.
	var OPS_RE = /\[OPS\]\s+(\S+)\s+(\S+)\s+(start|ok|fail|skip)(?:\s+(.*))?$/;

	function readMarkers(chunk, phaseEl) {
		var seen = false;
		chunk.split("\n").forEach(function (line) {
			var m = OPS_RE.exec(line);
			if (!m) return;
			seen = true;
			if (phaseEl) {
				phaseEl.textContent = (m[4] || m[2]) + (m[3] === "fail" ? " — FAILED" : "");
				phaseEl.className = m[3] === "fail" ? "small bad-text" : "muted small";
			}
		});
		// Panels render the full step list server-side; a marker is the only
		// moment their 15s poll has anything new to say.
		if (seen) refreshPanels(["actions", "jobs"]);
	}

	// htmx.trigger(el, "load") is a no-op: htmx 2 runs the "load" trigger once
	// at init and never listens for the event, so the panels are fetched
	// directly. fresh=1 skips the jobs cache TTL — the job state just changed.
	function refreshPanels(names) {
		if (!window.htmx) return;
		names.forEach(function (name) {
			var el = document.getElementById("panel-" + name);
			var url = el && el.getAttribute("hx-get");
			if (!url) return;
			url += (url.indexOf("?") === -1 ? "?" : "&") + "fresh=1";
			window.htmx.ajax("GET", url, { target: el, swap: "innerHTML" });
		});
	}

	// Time-left estimates are rendered server-side as seconds remaining; tick
	// them down locally between panel polls. The deadline is pinned on first
	// sight, so a re-rendered panel restarts from the fresh server value.
	function formatSeconds(total) {
		total = Math.max(0, Math.round(total));
		return total < 60 ? total + "s" : Math.floor(total / 60) + "m " + (total % 60) + "s";
	}

	setInterval(function () {
		var now = Date.now() / 1000;
		document.querySelectorAll("[data-countdown]").forEach(function (el) {
			if (!el.dataset.deadline) {
				el.dataset.deadline = now + (parseFloat(el.getAttribute("data-countdown")) || 0);
			}
			var left = parseFloat(el.dataset.deadline) - now;
			el.textContent = left > 0 ? "~" + formatSeconds(left) + " left" : "over estimate";
		});
	}, 1000);

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
		var phaseEl = wrap.querySelector("[data-console-phase]");

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
				readMarkers(event.data, phaseEl);
				if (stateEl && stateEl.textContent !== "running") {
					stateEl.textContent = "running";
					stateEl.className = "pill ok";
				}
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
				refreshPanels(["jobs", "version", "backups", "actions", "disk", "space-backups"]);
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
