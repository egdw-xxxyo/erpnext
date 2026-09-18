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

	// A panel that has just rendered says how often it wants to be polled
	// (`data-poll`, seconds): every second while a job is running, back to the
	// idle interval once it ends. The alternative — polling everything at 1s
	// all day — is the 50k-execs-a-day problem the visibility guard below
	// exists to avoid.
	function applyPollRates(root) {
		(root || document).querySelectorAll("[data-poll]").forEach(function (marker) {
			var panel = marker.closest("[hx-get]");
			if (!panel) return;
			var want = "load, every " + (parseInt(marker.getAttribute("data-poll"), 10) || 15) + "s";
			// Paused by the visibility guard: change what it will restore to,
			// not the live trigger, or the tab starts polling while hidden.
			if (panel.hasAttribute("data-paused-trigger")) {
				panel.setAttribute("data-paused-trigger", want);
				return;
			}
			if (panel.getAttribute("hx-trigger") === want) return;
			panel.setAttribute("hx-trigger", want);
			if (window.htmx) window.htmx.process(panel);
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

	// ---- jump from a step row to where that step starts in the log --------
	//
	// The markers the timeline is built from are also printed to stdout by
	// tools/ops-progress.sh, so every step has a literal line in the log:
	//   [OPS] 2026-09-18T08:50:25Z custom-fields start Applying custom fields
	// Matching on the step's own timestamp pins the right occurrence even when
	// a phase runs more than once in a job.

	function markerIndex(text, phase, started) {
		var exact = text.indexOf("[OPS] " + started + " " + phase + " ");
		if (exact !== -1) return exact;
		// No timestamp (or a log that predates it): first mention of the phase.
		var loose = new RegExp("\\[OPS\\]\\s+\\S+\\s+" + phase.replace(/[^\w-]/g, "") + "\\s", "m");
		var m = loose.exec(text);
		return m ? m.index : -1;
	}

	// The <pre> normally holds one text node, but a highlight or a re-render
	// can split it — walk to whichever node owns this character offset.
	function positionAt(root, index) {
		var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
		var node;
		var seen = 0;
		while ((node = walker.nextNode())) {
			var len = node.nodeValue.length;
			if (seen + len > index) return { node: node, offset: index - seen };
			seen += len;
		}
		return null;
	}

	function highlight(range) {
		if (!window.CSS || !CSS.highlights || typeof window.Highlight === "undefined") return;
		try {
			CSS.highlights.set("ops-step", new window.Highlight(range));
		} catch (err) {
			/* highlighting is decoration; never let it break the jump */
		}
	}

	function jumpToStep(row) {
		var wrap = row.closest(".console-wrap");
		var out = wrap && wrap.querySelector("[data-console-out]");
		if (!out) return;

		var phase = row.getAttribute("data-step-phase") || "";
		var started = row.getAttribute("data-step-started") || "";
		var index = markerIndex(out.textContent, phase, started);
		if (index === -1) {
			row.classList.add("step-missing");
			setTimeout(function () {
				row.classList.remove("step-missing");
			}, 1200);
			return;
		}

		var lineEnd = out.textContent.indexOf("\n", index);
		var start = positionAt(out, index);
		var end = positionAt(out, lineEnd === -1 ? out.textContent.length : lineEnd);
		if (!start || !end) return;

		var range = document.createRange();
		range.setStart(start.node, start.offset);
		range.setEnd(end.node, end.offset);

		// Following the tail would yank the view straight back to the bottom.
		var followEl = wrap.querySelector("[data-console-follow]");
		if (followEl) followEl.checked = false;

		var rect = range.getClientRects()[0] || range.getBoundingClientRect();
		out.scrollTop += rect.top - out.getBoundingClientRect().top - 24;
		highlight(range);

		wrap.querySelectorAll(".step-current").forEach(function (el) {
			el.classList.remove("step-current");
		});
		row.classList.add("step-current");
	}

	document.addEventListener("click", function (event) {
		var row = event.target.closest && event.target.closest("tr.step-jump");
		if (row) jumpToStep(row);
	});

	document.addEventListener("keydown", function (event) {
		if (event.key !== "Enter" && event.key !== " ") return;
		var row = event.target.closest && event.target.closest("tr.step-jump");
		if (!row) return;
		event.preventDefault();
		jumpToStep(row);
	});

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
				var after = ["jobs", "version", "backups", "actions", "disk", "space-backups"];
				refreshPanels(after);
				// The host writes .exit and only then unwinds the job wrapper,
				// so a refresh issued this instant can still read "running"
				// and leave the banner stuck until the next poll. Ask again.
				setTimeout(function () {
					refreshPanels(["jobs", "actions"]);
				}, 1500);
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
	document.body.addEventListener("htmx:afterSwap", function (event) {
		scan();
		applyPollRates(event.target);
	});

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
