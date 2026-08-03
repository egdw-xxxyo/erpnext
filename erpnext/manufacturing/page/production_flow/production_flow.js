frappe.pages["production-flow"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Production Flow"),
		single_column: true,
	});

	new erpnext.ProductionFlow({
		wrapper: $(wrapper).find(".layout-main-section"),
		page: page,
	});
};

(function () {
	var API = "erpnext.manufacturing.page.production_flow.production_flow";

	var SWIM_LANE_CONFIG = {
		prep: {
			label: "Підготовчі операції",
			color: "#4a6fa5",
			keywords: ["Підготовчі операції"],
		},
		conveyor: {
			label: "Конвеїрна збірка",
			color: "#6a994e",
			keywords: [
				"Перший етап",
				"Пайка силової",
				"Підготовка шлейф на оптику (конвеїр)",
				"Підготовка плати ініціації (Буратіно)",
				"Фінальна збірка (конвеїр)",
				"Підготовчі операції мотори (конвеїр)",
			],
		},
		final: {
			label: "Фінальний етап виробництва",
			color: "#bc4749",
			keywords: ["Фінальний етап"],
		},
	};

	erpnext.ProductionFlow = class ProductionFlow {
		constructor({ wrapper, page }) {
			this.$wrapper = $(wrapper);
			this.page = page;
			this.setup_controls();
		}

		setup_controls() {
			this.$wrapper.html(`
				<div class="production-flow-container">
					<div class="pf-selector">
						<div class="pf-selector-row">
							<div class="pf-selector-field" data-field="item"></div>
							<div class="pf-selector-field" data-field="bom"></div>
						</div>
					</div>
					<div class="pf-content"></div>
				</div>
			`);
			this.$container = this.$wrapper.find(".pf-content");

			this.item_field = frappe.ui.form.make_control({
				df: {
					label: __("Item"),
					fieldtype: "Link",
					fieldname: "item",
					options: "Item",
					placeholder: __("Select Item..."),
					get_query: () => ({
						filters: { name: ["in", this.bom_items || []] },
					}),
					change: () => this.on_item_change(),
				},
				parent: this.$wrapper.find('[data-field="item"]'),
				render_input: true,
			});

			this.bom_field = frappe.ui.form.make_control({
				df: {
					label: __("BOM"),
					fieldtype: "Link",
					fieldname: "bom",
					options: "BOM",
					placeholder: __("Select BOM..."),
					get_query: () => {
						var filters = { docstatus: 1, with_operations: 1 };
						var item = this.item_field.get_value();
						if (item) filters.item = item;
						return { filters };
					},
					change: () => this.on_bom_change(),
				},
				parent: this.$wrapper.find('[data-field="bom"]'),
				render_input: true,
			});

			this.load_bom_items();
		}

		load_bom_items() {
			frappe.call({
				method: API + ".get_bom_list",
				callback: (r) => {
					if (r.message) {
						this.bom_items = [...new Set(r.message.map((b) => b.item))];
						if (r.message.length) {
							this.item_field.set_value(r.message[0].item);
							this.bom_field.set_value(r.message[0].name);
						}
					}
				},
			});
		}

		on_item_change() {
			var item = this.item_field.get_value();
			if (!item) return;
			this.bom_field.set_value("");
			frappe.call({
				method: API + ".get_bom_list",
				args: { item },
				callback: (r) => {
					if (r.message && r.message.length) {
						this.bom_field.set_value(r.message[0].name);
					} else {
						this.$container.html(
							'<div class="pf-empty">' +
								__("No BOM with operations found for this item") +
								"</div>"
						);
					}
				},
			});
		}

		on_bom_change() {
			var bom = this.bom_field.get_value();
			if (!bom) return;

			frappe.call({
				method: API + ".get_bom_flow",
				args: { bom_name: bom },
				callback: (r) => {
					if (r.message) {
						this.data = r.message;
						this.render();
					}
				},
			});
		}

		classify_workstation(ws_name) {
			for (var lane_id in SWIM_LANE_CONFIG) {
				var config = SWIM_LANE_CONFIG[lane_id];
				for (var i = 0; i < config.keywords.length; i++) {
					if (ws_name.includes(config.keywords[i])) return lane_id;
				}
			}
			return "conveyor";
		}

		build_graph() {
			var lanes = { prep: [], conveyor: [], final: [] };
			var nodes = [];
			var edges = [];

			var ws_map = {};
			for (var i = 0; i < this.data.workstations.length; i++) {
				var ws = this.data.workstations[i];
				var lane = this.classify_workstation(ws.name);
				ws.lane = lane;
				ws_map[ws.name] = ws;
				lanes[lane].push(ws);
			}

			var node_id = 0;
			var op_to_node = {};
			var lane_order = ["prep", "conveyor", "final"];

			for (var li = 0; li < lane_order.length; li++) {
				var lane_id = lane_order[li];
				for (var wi = 0; wi < lanes[lane_id].length; wi++) {
					var lane_ws = lanes[lane_id][wi];
					lane_ws.node_id = node_id;
					lane_ws.op_nodes = [];
					for (var oi = 0; oi < lane_ws.operations.length; oi++) {
						var op = lane_ws.operations[oi];
						var nid = node_id++;
						op_to_node[op.idx] = nid;
						lane_ws.op_nodes.push(nid);
						nodes.push({
							id: nid,
							label: op.operation,
							workstation: lane_ws.name,
							lane: lane_id,
							time: op.time_in_mins,
							idx: op.idx,
						});
					}
				}
			}

			var sorted_ops = this.data.operations.slice().sort(function (a, b) {
				return a.idx - b.idx;
			});
			for (var si = 1; si < sorted_ops.length; si++) {
				var from_idx = sorted_ops[si - 1].idx;
				var to_idx = sorted_ops[si].idx;
				if (op_to_node[from_idx] !== undefined && op_to_node[to_idx] !== undefined) {
					edges.push({ from: op_to_node[from_idx], to: op_to_node[to_idx] });
				}
			}

			return { nodes: nodes, edges: edges, lanes: lanes, ws_map: ws_map };
		}

		render() {
			this.$container.empty();

			var graph = this.build_graph();

			var header =
				'<div class="pf-header">' +
				'<div class="pf-title">' +
				this.data.item_name +
				"</div>" +
				'<div class="pf-subtitle">' +
				this.data.bom_name +
				" &middot; " +
				this.data.operations.length +
				" операцій &middot; " +
				this.data.items.length +
				" матеріалів</div>" +
				"</div>";
			this.$container.append(header);

			var $diagram = $('<div class="pf-diagram"></div>');
			this.$container.append($diagram);

			this.render_swim_lanes($diagram, graph);
			this.render_connections($diagram, graph);
			this.render_materials_panel();
		}

		render_swim_lanes($diagram, graph) {
			var lane_order = ["prep", "conveyor", "final"];
			var self = this;

			for (var li = 0; li < lane_order.length; li++) {
				var lane_id = lane_order[li];
				var config = SWIM_LANE_CONFIG[lane_id];
				var workstations = graph.lanes[lane_id];
				if (!workstations.length) continue;

				var $lane = $(
					'<div class="pf-lane" data-lane="' +
						lane_id +
						'">' +
						'<div class="pf-lane-header" style="background: ' +
						config.color +
						'">' +
						'<span class="pf-lane-label">' +
						config.label +
						"</span></div>" +
						'<div class="pf-lane-body"></div></div>'
				);

				var $body = $lane.find(".pf-lane-body");

				for (var wi = 0; wi < workstations.length; wi++) {
					var ws = workstations[wi];
					var $ws = $(
						'<div class="pf-workstation" data-ws="' +
							ws.name +
							'">' +
							'<div class="pf-ws-header">' +
							ws.name +
							"</div>" +
							'<div class="pf-ws-ops"></div></div>'
					);

					var $ops = $ws.find(".pf-ws-ops");
					for (var oi = 0; oi < ws.operations.length; oi++) {
						var op = ws.operations[oi];
						var node = graph.nodes.find(function (n) {
							return n.idx === op.idx;
						});
						var $op = $(
							'<div class="pf-op-node" data-node-id="' +
								node.id +
								'" data-idx="' +
								op.idx +
								'">' +
								'<div class="pf-op-name">' +
								op.operation +
								"</div>" +
								'<div class="pf-op-time">' +
								op.time_in_mins +
								" хв</div>" +
								'<div class="pf-op-seq">#' +
								op.idx +
								"</div></div>"
						);

						(function (op_ref, ws_ref) {
							$op.on("click", function () {
								self.show_operation_detail(op_ref, ws_ref);
							});
						})(op, ws);
						$ops.append($op);
					}

					$body.append($ws);
				}

				$diagram.append($lane);
			}
		}

		render_connections($diagram, graph) {
			var svg_ns = "http://www.w3.org/2000/svg";

			requestAnimationFrame(function () {
				requestAnimationFrame(function () {
					$diagram.find(".pf-connections-overlay").remove();

					var $svg_container = $('<div class="pf-connections-overlay"></div>');
					$diagram.append($svg_container);

					var diagram_rect = $diagram[0].getBoundingClientRect();
					var scroll_left = $diagram[0].scrollLeft;
					var scroll_top = $diagram[0].scrollTop;
					var full_w = $diagram[0].scrollWidth;
					var full_h = $diagram[0].scrollHeight;

					var svg = document.createElementNS(svg_ns, "svg");
					svg.setAttribute("class", "pf-connections-svg");
					svg.setAttribute("width", full_w);
					svg.setAttribute("height", full_h);
					$svg_container.append(svg);

					var defs = document.createElementNS(svg_ns, "defs");
					var marker = document.createElementNS(svg_ns, "marker");
					marker.setAttribute("id", "pf-arrowhead");
					marker.setAttribute("markerWidth", "8");
					marker.setAttribute("markerHeight", "6");
					marker.setAttribute("refX", "8");
					marker.setAttribute("refY", "3");
					marker.setAttribute("orient", "auto");
					var polygon = document.createElementNS(svg_ns, "polygon");
					polygon.setAttribute("points", "0 0, 8 3, 0 6");
					polygon.setAttribute("fill", "var(--text-muted)");
					marker.appendChild(polygon);
					defs.appendChild(marker);
					svg.appendChild(defs);

					for (var ei = 0; ei < graph.edges.length; ei++) {
						var edge = graph.edges[ei];
						var from_el = $diagram.find('[data-node-id="' + edge.from + '"]')[0];
						var to_el = $diagram.find('[data-node-id="' + edge.to + '"]')[0];
						if (!from_el || !to_el) continue;

						var from_rect = from_el.getBoundingClientRect();
						var to_rect = to_el.getBoundingClientRect();

						var offset_x = diagram_rect.left - scroll_left;
						var offset_y = diagram_rect.top - scroll_top;

						var from_cx = from_rect.left + from_rect.width / 2 - offset_x;
						var from_cy = from_rect.top + from_rect.height / 2 - offset_y;
						var to_cx = to_rect.left + to_rect.width / 2 - offset_x;
						var to_cy = to_rect.top + to_rect.height / 2 - offset_y;

						var x1, y1, x2, y2;
						var dx = to_cx - from_cx;
						var dy = to_cy - from_cy;

						if (Math.abs(dx) > Math.abs(dy)) {
							if (dx > 0) {
								x1 = from_rect.right - offset_x;
								x2 = to_rect.left - offset_x;
							} else {
								x1 = from_rect.left - offset_x;
								x2 = to_rect.right - offset_x;
							}
							y1 = from_cy;
							y2 = to_cy;
						} else {
							if (dy > 0) {
								y1 = from_rect.bottom - offset_y;
								y2 = to_rect.top - offset_y;
							} else {
								y1 = from_rect.top - offset_y;
								y2 = to_rect.bottom - offset_y;
							}
							x1 = from_cx;
							x2 = to_cx;
						}

						var path = document.createElementNS(svg_ns, "path");
						var mx = (x1 + x2) / 2;
						var d;
						if (Math.abs(y2 - y1) < 5) {
							d = "M " + x1 + " " + y1 + " L " + x2 + " " + y2;
						} else if (Math.abs(x2 - x1) < 5) {
							d = "M " + x1 + " " + y1 + " L " + x2 + " " + y2;
						} else {
							d =
								"M " +
								x1 +
								" " +
								y1 +
								" C " +
								mx +
								" " +
								y1 +
								", " +
								mx +
								" " +
								y2 +
								", " +
								x2 +
								" " +
								y2;
						}
						path.setAttribute("d", d);
						path.setAttribute("class", "pf-edge");
						path.setAttribute("marker-end", "url(#pf-arrowhead)");
						svg.appendChild(path);
					}
				});
			});
		}

		render_materials_panel() {
			if (!this.data.items.length) return;

			var rows = [];
			for (var i = 0; i < this.data.items.length; i++) {
				var item = this.data.items[i];
				rows.push(
					'<div class="pf-material-row">' +
						'<span class="pf-mat-code">' +
						item.item_code +
						"</span>" +
						'<span class="pf-mat-name">' +
						item.item_name +
						"</span>" +
						'<span class="pf-mat-qty">' +
						item.qty +
						" " +
						item.uom +
						"</span>" +
						"</div>"
				);
			}

			var panel =
				'<div class="pf-materials-panel">' +
				'<div class="pf-materials-header" style="cursor: pointer">' +
				"<span>" +
				__("Матеріали") +
				" (" +
				this.data.items.length +
				")</span>" +
				'<span class="pf-materials-toggle">&#9660;</span></div>' +
				'<div class="pf-materials-body" style="display: none">' +
				rows.join("") +
				"</div></div>";

			this.$container.append(panel);

			this.$container.find(".pf-materials-header").on("click", function () {
				var $body = $(this).next(".pf-materials-body");
				var $toggle = $(this).find(".pf-materials-toggle");
				$body.slideToggle(200);
				$toggle.text($body.is(":visible") ? "\u25B2" : "\u25BC");
			});
		}

		show_operation_detail(op, ws) {
			var items_for_op = this.get_items_for_operation(op.operation);
			var items_html;
			if (items_for_op.length) {
				var parts = [];
				for (var i = 0; i < items_for_op.length; i++) {
					var it = items_for_op[i];
					parts.push(
						'<div class="pf-detail-item">' +
							'<a href="/app/item/' +
							encodeURIComponent(it.item_code) +
							'">' +
							it.item_name +
							"</a>" +
							'<span class="text-muted"> x' +
							it.qty +
							"</span></div>"
					);
				}
				items_html = parts.join("");
			} else {
				items_html = '<div class="text-muted">' + __("No specific materials mapped") + "</div>";
			}

			var op_link = "/app/operation/" + encodeURIComponent(op.operation);
			var ws_link = "/app/workstation/" + encodeURIComponent(ws.name);

			var d = new frappe.ui.Dialog({
				title: op.operation,
				fields: [
					{
						fieldtype: "HTML",
						options:
							'<div class="pf-op-detail">' +
							'<div class="pf-detail-row"><label>' +
							__("Операція") +
							"</label>" +
							'<a href="' +
							op_link +
							'">' +
							op.operation +
							" &#8599;</a></div>" +
							'<div class="pf-detail-row"><label>' +
							__("Робоча станція") +
							"</label>" +
							'<a href="' +
							ws_link +
							'">' +
							ws.name +
							" &#8599;</a></div>" +
							'<div class="pf-detail-row"><label>' +
							__("Час") +
							"</label>" +
							"<span>" +
							op.time_in_mins +
							" " +
							__("хв") +
							"</span></div>" +
							'<div class="pf-detail-row"><label>' +
							__("Крок") +
							"</label>" +
							"<span>#" +
							op.idx +
							" з " +
							this.data.operations.length +
							"</span></div>" +
							"<hr>" +
							'<div class="pf-detail-row"><label>' +
							__("Матеріали") +
							"</label></div>" +
							items_html +
							"</div>",
					},
				],
			});
			d.show();
		}

		get_items_for_operation(operation_name) {
			var op_lower = operation_name.toLowerCase();
			return this.data.items.filter(function (item) {
				var code = item.item_code.toLowerCase();

				if (op_lower.includes("мотор")) {
					return (
						code.startsWith("motor") ||
						code.startsWith("washer") ||
						code.startsWith("prop-") ||
						code.startsWith("spring") ||
						code.startsWith("spacer") ||
						code === "nut-m5-lock" ||
						code.startsWith("screw-motor")
					);
				}
				if (op_lower.includes("рам") || op_lower.includes("гайок")) {
					return (
						code.startsWith("frame") ||
						code.startsWith("seal") ||
						code.startsWith("3dp-") ||
						code.startsWith("standoff") ||
						code.startsWith("screw-") ||
						code.startsWith("nut-press") ||
						code.startsWith("nut-nylon")
					);
				}
				if (op_lower.includes("електроніки")) {
					return (
						code.startsWith("esc-") ||
						code.startsWith("fc-") ||
						code.startsWith("capacitor") ||
						code.startsWith("power-wire") ||
						code.startsWith("damper") ||
						code.startsWith("inter-stack") ||
						code.startsWith("heatshrink")
					);
				}
				if (op_lower.includes("шлейф") && op_lower.includes("оптик")) {
					return (
						code.startsWith("optics-cable") ||
						code.startsWith("conn-xh") ||
						code.startsWith("pin-xh")
					);
				}
				if (op_lower.includes("плати ініціації") || op_lower.includes("пайка плати")) {
					return (
						code.startsWith("board-") ||
						code.startsWith("resistor") ||
						code.startsWith("cable-init")
					);
				}
				if (op_lower.includes("камер")) {
					return code.startsWith("cam-");
				}
				if (op_lower.includes("ніжок")) {
					return code.startsWith("leg-") || code === "rubber-band-leg";
				}
				if (op_lower.includes("ременців")) {
					return (
						code.startsWith("strap-") ||
						code.startsWith("ziptie-") ||
						code === "rubber-band-strap"
					);
				}
				if (op_lower.includes("проп")) {
					return code.startsWith("prop-blade") || code.startsWith("prop-stand");
				}
				return false;
			});
		}
	};
})();
