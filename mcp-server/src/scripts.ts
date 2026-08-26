/**
 * Tools for editing scripts on the Workplace Script / Scanner Script / Scanner Command
 * pages.
 *
 * Versioning (keep in sync with erpnext/manufacturing/doctype/workplace_script/workplace_script.py)
 * --------------------------------------------------------------------------------------------------
 * Each Workplace Script / Scanner Script has a child `versions` table. Each row stores a JSON
 * snapshot:
 *   - Workplace Script snapshot: {script, states, transitions}
 *   - Scanner Script   snapshot: {script}
 * Exactly one row is `is_default` — that's the version runtime uses. `viewing_version` is the row
 * whose snapshot is mirrored into the working-copy fields (`script`, `states`, `transitions`) on
 * the form / via the REST API. Saving the doc serializes the working copy back into the
 * `viewing_version` row.
 *
 * For these MCP tools that means:
 *   - get_* tools default to reading the DEFAULT version's snapshot (what runtime uses). Pass
 *     `version` to read a specific snapshot.
 *   - edit_* tools default to writing to the DEFAULT version. Pass `version` to target a
 *     non-default draft. The implementation sets `viewing_version` and ships the working copy.
 *
 * Runtime model
 * --------------------------------------------------------------------------------------------------
 * Workplace Script: per-workplace pipeline. Main `script` is a 2-line orchestrator that calls
 * `run_state(...)`. Each State row carries `on_enter_script` defining `def on_scan(e): ...`.
 * Inside that script: globals `frappe`, `scripts`, `e`. Available on `e`:
 *   - e.scan_type ∈ {workplace, employee, command, serial_no, item, job_card, packing_template, unknown}
 *   - e.doc, e.data, e.barcode, e.item_code
 *   - e.scanner, e.workplace, e.employee
 *   - e.set_workplace(name), e.set_employee(name)
 *   - e.state.name, e.state.context
 *   - e.state.set(state_name, ctx_dict) — transition (must be declared in Transitions table)
 *   - e.state.clear() — wipe state, next scan resets to initial
 *   - scripts.<scanner_script_name>.<symbol> — call shared helpers from Scanner Scripts
 *
 * Transitions are BOTH diagram source AND runtime validation. e.state.set(target) is rejected
 * unless a row with from_state == current and to_state == target exists (self-transitions and
 * e.state.clear() always allowed).
 *
 * Scanner Script: reusable Python module loaded into `scripts.<name>` inside every Workplace
 * Script execution. Define top-level functions / constants.
 *
 * Scanner Command: barcode-encoded command. Doc has `name`, `barcode_id` (e.g. "CMD-7E671283"),
 * `description`. State scripts match these via `e.scan_type == "command" and e.doc.barcode_id == "..."`.
 */

import type { ERPNextClient } from "./index.js";

const STATE_SCRIPT_USAGE = `
The state's script must define \`def on_scan(e)\`. Globals: frappe, scripts, e.

Event:
  e.scan_type ∈ {workplace, employee, command, serial_no, item, job_card, packing_template, unknown}
  e.doc, e.data, e.barcode, e.item_code, e.scanner, e.workplace, e.employee
  e.set_workplace(name), e.set_employee(name)

State (Redis-backed, persists across scans):
  e.state.name, e.state.context
  e.state.set(state_name, ctx_dict) — transition; raises TransitionError if (current → state_name)
                                       is not in the Transitions table (self-transitions are always allowed)
  e.state.clear() — wipe state, next scan resets to the initial state (always allowed)

Reusable helpers: scripts.<scanner_script_name>.<symbol>
Match commands: e.scan_type == "command" and e.doc.barcode_id == "CMD-..."

Transitions table feeds both the diagram and runtime validation: declare every (from_state →
to_state) pair you call \`e.state.set(...)\` for, otherwise the operator sees a "Помилка
переходу" error and the state is unchanged.
`.trim();

const VERSION_NOTE =
  "Optional. Target version (e.g. 'v2'). Defaults to the doc's default version (the one runtime uses).";

export const SCRIPT_TOOLS = [
  // ── Workplace Script ────────────────────────────────────────────────────
  {
    name: "list_workplace_scripts",
    description: "List all Workplace Scripts (the per-workplace scanner pipeline scripts) with workplace + parent_script + active status + default version. parent_script identifies subflows (see edit_workplace_script_meta).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_workplace_script",
    description:
      "Read a Workplace Script — main `script`, all state rows (with their per-state scripts), and transitions. By default returns the snapshot of the version that runtime uses (the default version). Pass `version` to read a specific snapshot. Always returns version metadata: default_version, viewing_version, versions[].",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string", description: "Workplace Script name (e.g. Пакувальник)" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["script_name"],
    },
  },
  {
    name: "list_workplace_script_versions",
    description: "List all versions of a Workplace Script with is_default + created_on metadata.",
    inputSchema: {
      type: "object",
      properties: { script_name: { type: "string" } },
      required: ["script_name"],
    },
  },
  {
    name: "add_workplace_script_version",
    description:
      "Create a new version on a Workplace Script. Auto-named v1, v2, … Snapshot is copied from `source_version` (defaults to the current default version). The new version is NOT made default — call set_default_workplace_script_version afterwards if you want runtime to use it.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        source_version: { type: "string", description: "Version to clone the snapshot from. Defaults to default version." },
        label: { type: "string", description: "Optional free-form description shown in the grid." },
      },
      required: ["script_name"],
    },
  },
  {
    name: "remove_workplace_script_version",
    description: "Remove a version row from a Workplace Script. Blocked when only one version exists or when removing the current default (switch default first).",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        version: { type: "string" },
      },
      required: ["script_name", "version"],
    },
  },
  {
    name: "set_default_workplace_script_version",
    description: "Mark a version as the default (the one runtime executes). The previous default becomes a draft.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        version: { type: "string" },
      },
      required: ["script_name", "version"],
    },
  },
  {
    name: "edit_workplace_script_main",
    description:
      "Replace the main `script` field of a Workplace Script. Typically just a 2-line dispatcher: `from erpnext.manufacturing.doctype.workplace_script.workplace_script import run_state` / `def on_scan(e): return run_state(\"<name>\", e, scripts=scripts)`. Per-state logic belongs in the State rows. Targets the default version unless `version` is supplied.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        script: { type: "string", description: "Full Python source for the main script field" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["script_name", "script"],
    },
  },
  {
    name: "edit_workplace_script_state",
    description:
      `Create or update a State row on a Workplace Script. If the state already exists, updates its script (and flags if provided). If not, appends a new row. Targets the default version unless \`version\` is supplied.\n\n${STATE_SCRIPT_USAGE}`,
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string", description: "Workplace Script name" },
        state: { type: "string", description: "State name (e.g. Початок)" },
        script: {
          type: "string",
          description: "Python source defining `def on_scan(e): ...`. Stored on the row's on_enter_script field.",
        },
        label: { type: "string", description: "Optional translatable label shown in the diagram (defaults to state name)" },
        is_initial: { type: "boolean", description: "Mark as the initial state. Only one state per script may be initial." },
        is_final: { type: "boolean" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["script_name", "state"],
    },
  },
  {
    name: "delete_workplace_script_state",
    description: "Remove a State row from a Workplace Script. Targets the default version unless `version` is supplied.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        state: { type: "string" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["script_name", "state"],
    },
  },
  {
    name: "edit_workplace_script_transitions",
    description:
      "Replace the entire Transitions list on a Workplace Script. Transitions feed both the diagram AND runtime validation — `e.state.set(target)` from inside a state's script is rejected unless a row with matching from_state/to_state exists (self-transitions and `e.state.clear()` are always allowed). After editing state scripts that introduce a new `e.state.set(...)`, ALWAYS update transitions to match, otherwise the operator sees a transition error. Each row needs from_state, event, to_state. Targets the default version unless `version` is supplied.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        transitions: {
          type: "array",
          description: "Full replacement list of transitions.",
          items: {
            type: "object",
            properties: {
              from_state: { type: "string" },
              event: { type: "string", description: "Human-readable label (e.g. start_packaging) shown on the diagram edge." },
              to_state: { type: "string" },
            },
            required: ["from_state", "event", "to_state"],
          },
        },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["script_name", "transitions"],
    },
  },

  // ── Scanner Script ──────────────────────────────────────────────────────
  {
    name: "list_scanner_scripts",
    description:
      "List all Scanner Scripts (reusable Python modules loaded into `scripts.<name>` inside every Workplace Script execution).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_scanner_script",
    description: "Read a Scanner Script — name, is_active, full script body. By default returns the snapshot of the version that runtime uses (default). Pass `version` to read a specific snapshot. Always returns default_version, viewing_version, versions[].",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["name"],
    },
  },
  {
    name: "list_scanner_script_versions",
    description: "List all versions of a Scanner Script with is_default + created_on metadata.",
    inputSchema: {
      type: "object",
      properties: { name: { type: "string" } },
      required: ["name"],
    },
  },
  {
    name: "add_scanner_script_version",
    description:
      "Create a new version on a Scanner Script. Auto-named v1, v2, … Snapshot is copied from `source_version` (defaults to current default version). Not made default automatically.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        source_version: { type: "string" },
        label: { type: "string" },
      },
      required: ["name"],
    },
  },
  {
    name: "remove_scanner_script_version",
    description: "Remove a version row from a Scanner Script. Blocked when only one version exists or when removing the current default.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        version: { type: "string" },
      },
      required: ["name", "version"],
    },
  },
  {
    name: "set_default_scanner_script_version",
    description: "Mark a Scanner Script version as the default (runtime uses it).",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        version: { type: "string" },
      },
      required: ["name", "version"],
    },
  },
  {
    name: "edit_scanner_script",
    description:
      "Create or update a Scanner Script. The script is a Python module — define top-level functions / constants. Inside Workplace Script state code, access symbols via `scripts.<name>.<symbol>` (the name is lowercased with spaces/dashes → underscores). On existing docs, targets the default version unless `version` is supplied.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Script name (becomes the key under `scripts.`)" },
        script: { type: "string", description: "Full Python source" },
        is_active: { type: "boolean", description: "Default true on create" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["name", "script"],
    },
  },

  // ── Reflectometer Script ────────────────────────────────────────────────
  {
    name: "list_reflectometer_scripts",
    description:
      "List all Reflectometer Scripts (run automatically after each OTDR measurement upload). Same versioning model as Scanner Script. Entry point: `on_event(ctx)` or `on_reflectometer(ctx)`; ctx exposes ctx.otdr, ctx.log_entry, ctx.payload (parsed SOR dict).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_reflectometer_script",
    description:
      "Read a Reflectometer Script — name, is_active, full script body. Defaults to the default version's snapshot. Pass `version` for a specific snapshot.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["name"],
    },
  },
  {
    name: "edit_reflectometer_script",
    description:
      "Create or update a Reflectometer Script. Define `def on_event(ctx)` (or `on_reflectometer(ctx)`). ctx fields: ctx.otdr (OTDR doc), ctx.log_entry (just-saved measurement row), ctx.payload (parsed SOR dict). Frappe and json modules in scope. Errors are logged to Error Log, never raised back to the desktop client.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        script: { type: "string", description: "Full Python source" },
        is_active: { type: "boolean", description: "Default true on create" },
        version: { type: "string", description: VERSION_NOTE },
      },
      required: ["name", "script"],
    },
  },

  // ── Scanner Command ─────────────────────────────────────────────────────
  {
    name: "list_scanner_commands",
    description: "List all Scanner Commands (barcode-encoded commands matched by state scripts).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "edit_scanner_command",
    description:
      "Create or update a Scanner Command. State scripts match it via `e.scan_type == \"command\" and e.doc.barcode_id == \"CMD-...\"`. Stack actions (Push/Pop/Toggle) live on the root Workplace Script's Subflow Entries table, not here.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Command name (e.g. Скинути стан)" },
        barcode_id: { type: "string", description: "Barcode id (e.g. CMD-RESET01)" },
        description: { type: "string" },
      },
      required: ["name"],
    },
  },

  // ── Subflow Entries (declarative root → subflow routing) ─────────────────
  {
    name: "list_subflow_entries",
    description:
      "List Subflow Entries on a (root) Workplace Script. Each row routes a scan to a target subflow when scanner is in the matching from_state. trigger_type=Command matches Scanner Command barcode_id; trigger_type='Scan Type' matches e.scan_type. On match the scanner switches to the target subflow's initial state and the subflow processes the same scan. Subflow exits via e.state.clear() (returns to root initial). First match wins.",
    inputSchema: {
      type: "object",
      properties: { script_name: { type: "string" } },
      required: ["script_name"],
    },
  },
  {
    name: "set_subflow_entries",
    description:
      "Replace the entire Subflow Entries table on a (root) Workplace Script. Pass all rows. Each row: from_state (required, state name in this script), trigger_type ('Command' | 'Scan Type'), trigger_value (barcode_id or scan_type), target_subflow (required). On match, scanner switches to target subflow's initial state and processes the same scan there. Subflow exits via e.state.clear().",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        entries: {
          type: "array",
          items: {
            type: "object",
            properties: {
              from_state: { type: "string", description: "State in this script that triggers entry." },
              trigger_type: { type: "string", enum: ["Command", "Scan Type"] },
              trigger_value: { type: "string" },
              target_subflow: { type: "string" },
              description: { type: "string" },
            },
            required: ["from_state", "trigger_type", "trigger_value", "target_subflow"],
          },
        },
      },
      required: ["script_name", "entries"],
    },
  },

  // ── Workplace Script meta (top-level fields) ─────────────────────────────
  {
    name: "edit_workplace_script_meta",
    description:
      "Update top-level (non-versioned) fields on a Workplace Script: workplace, is_active, parent_script. parent_script makes this script a subflow of another Workplace Script — subflows have no workplace and are exempt from the per-workplace uniqueness check. Use create_document via the generic ERPNext MCP to create a new Workplace Script.",
    inputSchema: {
      type: "object",
      properties: {
        script_name: { type: "string" },
        workplace: { type: "string", description: "Workplace link, or null/empty to clear. Mutually exclusive with parent_script." },
        is_active: { type: "boolean" },
        parent_script: { type: "string", description: "Workplace Script name. Setting marks this as a subflow. Pass empty string to clear." },
      },
      required: ["script_name"],
    },
  },
];

const SCRIPT_TOOL_NAMES = new Set(SCRIPT_TOOLS.map((t) => t.name));

export function isScriptTool(name: string): boolean {
  return SCRIPT_TOOL_NAMES.has(name);
}

type ToolResult = { content: { type: "text"; text: string }[]; isError?: boolean };

const ok = (text: string): ToolResult => ({ content: [{ type: "text", text }] });
const err = (text: string): ToolResult => ({ content: [{ type: "text", text }], isError: true });
const json = (data: unknown): ToolResult => ok(JSON.stringify(data, null, 2));

function arg<T = any>(args: any, key: string): T {
  return args?.[key] as T;
}

// ── Snapshot helpers ──────────────────────────────────────────────────────
type WorkplaceSnapshot = {
  script: string;
  states: any[];
  transitions: any[];
};
type ScannerSnapshot = { script: string };

function parseSnapshot<T>(raw: any): T {
  if (!raw) return {} as T;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return {} as T;
  }
}

function findVersion(doc: any, version?: string): any | undefined {
  const versions = doc.versions || [];
  if (version) return versions.find((v: any) => v.version === version);
  return versions.find((v: any) => v.is_default) || versions[0];
}

function workplaceSnapshot(row: any): WorkplaceSnapshot {
  const snap = parseSnapshot<Partial<WorkplaceSnapshot>>(row?.snapshot);
  return {
    script: snap.script ?? "",
    states: Array.isArray(snap.states) ? snap.states : [],
    transitions: Array.isArray(snap.transitions) ? snap.transitions : [],
  };
}

function scannerSnapshot(row: any): ScannerSnapshot {
  const snap = parseSnapshot<Partial<ScannerSnapshot>>(row?.snapshot);
  return { script: snap.script ?? "" };
}

function nextVersionName(versions: any[]): string {
  let n = 0;
  for (const v of versions || []) {
    const m = /^v(\d+)$/.exec(v.version || "");
    if (m) n = Math.max(n, parseInt(m[1], 10));
  }
  return `v${n + 1}`;
}

function versionsSummary(doc: any) {
  return (doc.versions || []).map((v: any) => ({
    version: v.version,
    is_default: !!v.is_default,
    label: v.label || null,
    created_on: v.created_on || null,
  }));
}

export async function handleScriptTool(
  name: string,
  args: any,
  erpnext: ERPNextClient,
): Promise<ToolResult> {
  if (!erpnext.isAuthenticated()) {
    return err("Not authenticated with ERPNext. Configure ERPNEXT_API_KEY / ERPNEXT_API_SECRET.");
  }

  try {
    switch (name) {
      // ── Workplace Script ────────────────────────────────────────────────
      case "list_workplace_scripts": {
        const docs = await erpnext.getDocList(
          "Workplace Script",
          undefined,
          ["name", "workplace", "parent_script", "is_active", "default_version"],
          200,
        );
        return json(docs);
      }

      case "get_workplace_script": {
        const scriptName = arg<string>(args, "script_name");
        const version = arg<string | undefined>(args, "version");
        if (!scriptName) return err("script_name is required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found on ${scriptName}`);
        const snap = workplaceSnapshot(row);
        return json({
          name: doc.name,
          workplace: doc.workplace,
          parent_script: doc.parent_script || null,
          is_active: doc.is_active,
          default_version: doc.default_version,
          viewing_version: doc.viewing_version,
          version: row.version,
          is_default: !!row.is_default,
          versions: versionsSummary(doc),
          script: snap.script,
          states: (snap.states || []).map((s: any) => ({
            state: s.state,
            label: s.label,
            is_initial: s.is_initial,
            is_final: s.is_final,
            script: s.on_enter_script,
          })),
          transitions: (snap.transitions || []).map((t: any) => ({
            from_state: t.from_state,
            event: t.event,
            to_state: t.to_state,
          })),
        });
      }

      case "list_workplace_script_versions": {
        const scriptName = arg<string>(args, "script_name");
        if (!scriptName) return err("script_name is required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        return json({
          name: doc.name,
          default_version: doc.default_version,
          viewing_version: doc.viewing_version,
          versions: versionsSummary(doc),
        });
      }

      case "add_workplace_script_version": {
        const scriptName = arg<string>(args, "script_name");
        const sourceVersion = arg<string | undefined>(args, "source_version");
        const label = arg<string | undefined>(args, "label");
        if (!scriptName) return err("script_name is required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        const sourceRow = findVersion({ versions }, sourceVersion);
        if (!sourceRow) return err(`Source version ${sourceVersion || "default"} not found`);
        const newName = nextVersionName(versions);
        versions.push({
          version: newName,
          is_default: 0,
          label: label ?? null,
          snapshot: sourceRow.snapshot,
          created_on: new Date().toISOString().replace("T", " ").slice(0, 19),
        });
        await erpnext.updateDocument("Workplace Script", scriptName, { versions });
        return ok(`Added version ${newName} on Workplace Script ${scriptName} (cloned from ${sourceRow.version})`);
      }

      case "remove_workplace_script_version": {
        const scriptName = arg<string>(args, "script_name");
        const version = arg<string>(args, "version");
        if (!scriptName || !version) return err("script_name and version are required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        if (versions.length <= 1) return err("Cannot remove the only version");
        const row = versions.find((v: any) => v.version === version);
        if (!row) return err(`Version ${version} not found`);
        if (row.is_default) {
          return err(`Cannot remove the default version ${version}. Switch default first with set_default_workplace_script_version.`);
        }
        const filtered = versions.filter((v: any) => v.version !== version);
        const payload: Record<string, any> = { versions: filtered };
        if (doc.viewing_version === version) payload.viewing_version = doc.default_version;
        await erpnext.updateDocument("Workplace Script", scriptName, payload);
        return ok(`Removed version ${version} from Workplace Script ${scriptName}`);
      }

      case "set_default_workplace_script_version": {
        const scriptName = arg<string>(args, "script_name");
        const version = arg<string>(args, "version");
        if (!scriptName || !version) return err("script_name and version are required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        if (!versions.find((v: any) => v.version === version)) return err(`Version ${version} not found`);
        for (const v of versions) v.is_default = v.version === version ? 1 : 0;
        await erpnext.updateDocument("Workplace Script", scriptName, {
          versions,
          default_version: version,
        });
        return ok(`Default version of Workplace Script ${scriptName} set to ${version}`);
      }

      case "edit_workplace_script_main": {
        const scriptName = arg<string>(args, "script_name");
        const script = arg<string>(args, "script");
        const version = arg<string | undefined>(args, "version");
        if (!scriptName || script === undefined) return err("script_name and script are required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found`);
        const snap = workplaceSnapshot(row);
        await erpnext.updateDocument("Workplace Script", scriptName, {
          viewing_version: row.version,
          script,
          states: snap.states,
          transitions: snap.transitions,
        });
        return ok(`Updated main script of Workplace Script ${scriptName} (version ${row.version})`);
      }

      case "edit_workplace_script_state": {
        const scriptName = arg<string>(args, "script_name");
        const stateName = arg<string>(args, "state");
        const version = arg<string | undefined>(args, "version");
        if (!scriptName || !stateName) return err("script_name and state are required");

        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found`);
        const snap = workplaceSnapshot(row);
        const states = (snap.states || []).map((s: any) => ({ ...s }));

        const stateScript = arg<string | undefined>(args, "script");
        const label = arg<string | undefined>(args, "label");
        const isInitial = arg<boolean | undefined>(args, "is_initial");
        const isFinal = arg<boolean | undefined>(args, "is_final");

        const idx = states.findIndex((s: any) => s.state === stateName);
        let action: "created" | "updated";
        if (idx >= 0) {
          if (stateScript !== undefined) states[idx].on_enter_script = stateScript;
          if (label !== undefined) states[idx].label = label;
          if (isInitial !== undefined) states[idx].is_initial = isInitial ? 1 : 0;
          if (isFinal !== undefined) states[idx].is_final = isFinal ? 1 : 0;
          action = "updated";
        } else {
          states.push({
            state: stateName,
            label: label ?? null,
            is_initial: isInitial ? 1 : 0,
            is_final: isFinal ? 1 : 0,
            on_enter_script: stateScript ?? null,
          });
          action = "created";
        }

        if (isInitial) {
          for (const s of states) {
            if (s.state !== stateName) s.is_initial = 0;
          }
        }

        await erpnext.updateDocument("Workplace Script", scriptName, {
          viewing_version: row.version,
          script: snap.script,
          states,
          transitions: snap.transitions,
        });
        return ok(`State '${stateName}' ${action} on ${scriptName} (version ${row.version})`);
      }

      case "delete_workplace_script_state": {
        const scriptName = arg<string>(args, "script_name");
        const stateName = arg<string>(args, "state");
        const version = arg<string | undefined>(args, "version");
        if (!scriptName || !stateName) return err("script_name and state are required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found`);
        const snap = workplaceSnapshot(row);
        const states = (snap.states || []).filter((s: any) => s.state !== stateName);
        if (states.length === (snap.states || []).length) {
          return err(`State '${stateName}' not found on ${scriptName} (version ${row.version})`);
        }
        await erpnext.updateDocument("Workplace Script", scriptName, {
          viewing_version: row.version,
          script: snap.script,
          states,
          transitions: snap.transitions,
        });
        return ok(`Deleted state '${stateName}' from ${scriptName} (version ${row.version})`);
      }

      case "edit_workplace_script_transitions": {
        const scriptName = arg<string>(args, "script_name");
        const transitions = arg<any[]>(args, "transitions");
        const version = arg<string | undefined>(args, "version");
        if (!scriptName || !Array.isArray(transitions)) {
          return err("script_name and transitions[] are required");
        }
        for (const t of transitions) {
          if (!t.from_state || !t.event || !t.to_state) {
            return err("Each transition must have from_state, event, to_state");
          }
        }
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found`);
        const snap = workplaceSnapshot(row);
        await erpnext.updateDocument("Workplace Script", scriptName, {
          viewing_version: row.version,
          script: snap.script,
          states: snap.states,
          transitions,
        });
        return ok(`Replaced ${transitions.length} transition(s) on ${scriptName} (version ${row.version})`);
      }

      // ── Scanner Script ──────────────────────────────────────────────────
      case "list_scanner_scripts": {
        const docs = await erpnext.getDocList(
          "Device Script",
          { script_type: "Scanner" },
          ["name", "is_active", "default_version", "script_type"],
          200,
        );
        return json(docs);
      }

      case "list_reflectometer_scripts": {
        const docs = await erpnext.getDocList(
          "Device Script",
          { script_type: "Reflectometer" },
          ["name", "is_active", "default_version", "script_type"],
          200,
        );
        return json(docs);
      }

      case "get_reflectometer_script": {
        const n = arg<string>(args, "name");
        const version = arg<string | undefined>(args, "version");
        if (!n) return err("name is required");
        const doc = await erpnext.getDocument("Device Script", n);
        if (doc.script_type !== "Reflectometer") return err(`${n} is not a Reflectometer script`);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found on ${n}`);
        const snap = scannerSnapshot(row);
        return json({
          name: doc.name,
          script_type: doc.script_type,
          is_active: doc.is_active,
          default_version: doc.default_version,
          viewing_version: doc.viewing_version,
          version: row.version,
          is_default: !!row.is_default,
          versions: versionsSummary(doc),
          script: snap.script,
        });
      }

      case "edit_reflectometer_script": {
        const n = arg<string>(args, "name");
        const script = arg<string>(args, "script");
        const isActive = arg<boolean | undefined>(args, "is_active");
        const version = arg<string | undefined>(args, "version");
        if (!n || script === undefined) return err("name and script are required");

        let exists = true;
        let doc: any = null;
        try {
          doc = await erpnext.getDocument("Device Script", n);
        } catch {
          exists = false;
        }

        if (exists) {
          if (doc.script_type !== "Reflectometer") return err(`${n} exists but is not a Reflectometer script`);
          const row = findVersion(doc, version);
          if (!row) return err(`Version ${version || "default"} not found on ${n}`);
          const data: Record<string, any> = {
            viewing_version: row.version,
            script,
          };
          if (isActive !== undefined) data.is_active = isActive ? 1 : 0;
          await erpnext.updateDocument("Device Script", n, data);
          return ok(`Updated Reflectometer Script ${n} (version ${row.version})`);
        } else {
          await erpnext.createDocument("Device Script", {
            script_name: n,
            script_type: "Reflectometer",
            script,
            is_active: isActive === false ? 0 : 1,
          });
          return ok(`Created Reflectometer Script ${n}`);
        }
      }

      case "get_scanner_script": {
        const n = arg<string>(args, "name");
        const version = arg<string | undefined>(args, "version");
        if (!n) return err("name is required");
        const doc = await erpnext.getDocument("Device Script", n);
        const row = findVersion(doc, version);
        if (!row) return err(`Version ${version || "default"} not found on ${n}`);
        const snap = scannerSnapshot(row);
        return json({
          name: doc.name,
          is_active: doc.is_active,
          default_version: doc.default_version,
          viewing_version: doc.viewing_version,
          version: row.version,
          is_default: !!row.is_default,
          versions: versionsSummary(doc),
          script: snap.script,
        });
      }

      case "list_scanner_script_versions": {
        const n = arg<string>(args, "name");
        if (!n) return err("name is required");
        const doc = await erpnext.getDocument("Device Script", n);
        return json({
          name: doc.name,
          default_version: doc.default_version,
          viewing_version: doc.viewing_version,
          versions: versionsSummary(doc),
        });
      }

      case "add_scanner_script_version": {
        const n = arg<string>(args, "name");
        const sourceVersion = arg<string | undefined>(args, "source_version");
        const label = arg<string | undefined>(args, "label");
        if (!n) return err("name is required");
        const doc = await erpnext.getDocument("Device Script", n);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        const sourceRow = findVersion({ versions }, sourceVersion);
        if (!sourceRow) return err(`Source version ${sourceVersion || "default"} not found`);
        const newName = nextVersionName(versions);
        versions.push({
          version: newName,
          is_default: 0,
          label: label ?? null,
          snapshot: sourceRow.snapshot,
          created_on: new Date().toISOString().replace("T", " ").slice(0, 19),
        });
        await erpnext.updateDocument("Device Script", n, { versions });
        return ok(`Added version ${newName} on Scanner Script ${n} (cloned from ${sourceRow.version})`);
      }

      case "remove_scanner_script_version": {
        const n = arg<string>(args, "name");
        const version = arg<string>(args, "version");
        if (!n || !version) return err("name and version are required");
        const doc = await erpnext.getDocument("Device Script", n);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        if (versions.length <= 1) return err("Cannot remove the only version");
        const row = versions.find((v: any) => v.version === version);
        if (!row) return err(`Version ${version} not found`);
        if (row.is_default) {
          return err(`Cannot remove the default version ${version}. Switch default first.`);
        }
        const filtered = versions.filter((v: any) => v.version !== version);
        const payload: Record<string, any> = { versions: filtered };
        if (doc.viewing_version === version) payload.viewing_version = doc.default_version;
        await erpnext.updateDocument("Device Script", n, payload);
        return ok(`Removed version ${version} from Scanner Script ${n}`);
      }

      case "set_default_scanner_script_version": {
        const n = arg<string>(args, "name");
        const version = arg<string>(args, "version");
        if (!n || !version) return err("name and version are required");
        const doc = await erpnext.getDocument("Device Script", n);
        const versions = (doc.versions || []).map((v: any) => ({ ...v }));
        if (!versions.find((v: any) => v.version === version)) return err(`Version ${version} not found`);
        for (const v of versions) v.is_default = v.version === version ? 1 : 0;
        await erpnext.updateDocument("Device Script", n, {
          versions,
          default_version: version,
        });
        return ok(`Default version of Scanner Script ${n} set to ${version}`);
      }

      case "edit_scanner_script": {
        const n = arg<string>(args, "name");
        const script = arg<string>(args, "script");
        const isActive = arg<boolean | undefined>(args, "is_active");
        const version = arg<string | undefined>(args, "version");
        if (!n || script === undefined) return err("name and script are required");

        let exists = true;
        let doc: any = null;
        try {
          doc = await erpnext.getDocument("Device Script", n);
        } catch {
          exists = false;
        }

        if (exists) {
          const row = findVersion(doc, version);
          if (!row) return err(`Version ${version || "default"} not found on ${n}`);
          const data: Record<string, any> = {
            viewing_version: row.version,
            script,
          };
          if (isActive !== undefined) data.is_active = isActive ? 1 : 0;
          await erpnext.updateDocument("Device Script", n, data);
          return ok(`Updated Scanner Script ${n} (version ${row.version})`);
        } else {
          await erpnext.createDocument("Device Script", {
            script_name: n,
            script_type: "Scanner",
            script,
            is_active: isActive === false ? 0 : 1,
          });
          return ok(`Created Scanner Script ${n}`);
        }
      }

      // ── Scanner Command ─────────────────────────────────────────────────
      case "list_scanner_commands": {
        const docs = await erpnext.getDocList(
          "Scanner Command",
          undefined,
          ["name", "barcode_id", "description"],
          200,
        );
        return json(docs);
      }

      case "edit_scanner_command": {
        const n = arg<string>(args, "name");
        const barcodeId = arg<string | undefined>(args, "barcode_id");
        const description = arg<string | undefined>(args, "description");
        if (!n) return err("name is required");

        let exists = true;
        try {
          await erpnext.getDocument("Scanner Command", n);
        } catch {
          exists = false;
        }

        if (exists) {
          const data: Record<string, any> = {};
          if (barcodeId !== undefined) data.barcode_id = barcodeId;
          if (description !== undefined) data.description = description;
          if (Object.keys(data).length === 0) return err("Nothing to update — provide barcode_id or description");
          await erpnext.updateDocument("Scanner Command", n, data);
          return ok(`Updated Scanner Command ${n}`);
        } else {
          await erpnext.createDocument("Scanner Command", {
            name: n,
            barcode_id: barcodeId,
            description: description ?? null,
          });
          return ok(`Created Scanner Command ${n}`);
        }
      }

      case "list_subflow_entries": {
        const scriptName = arg<string>(args, "script_name");
        if (!scriptName) return err("script_name is required");
        const doc = await erpnext.getDocument("Workplace Script", scriptName);
        return json({
          name: doc.name,
          entries: (doc.subflow_entries || []).map((r: any) => ({
            from_state: r.from_state,
            trigger_type: r.trigger_type,
            trigger_value: r.trigger_value,
            target_subflow: r.target_subflow,
            description: r.description || null,
          })),
        });
      }

      case "set_subflow_entries": {
        const scriptName = arg<string>(args, "script_name");
        const entries = arg<any[]>(args, "entries");
        if (!scriptName) return err("script_name is required");
        if (!Array.isArray(entries)) return err("entries must be an array");
        const rows = entries.map((r) => {
          if (!r.from_state) throw new Error("from_state is required");
          if (!r.target_subflow) throw new Error("target_subflow is required");
          return {
            from_state: r.from_state,
            trigger_type: r.trigger_type,
            trigger_value: r.trigger_value,
            target_subflow: r.target_subflow,
            description: r.description || null,
          };
        });
        await erpnext.updateDocument("Workplace Script", scriptName, { subflow_entries: rows });
        return ok(`Replaced ${rows.length} subflow entr(y/ies) on ${scriptName}`);
      }

      case "edit_workplace_script_meta": {
        const scriptName = arg<string>(args, "script_name");
        const workplace = arg<string | undefined>(args, "workplace");
        const isActive = arg<boolean | undefined>(args, "is_active");
        const parentScript = arg<string | undefined>(args, "parent_script");
        if (!scriptName) return err("script_name is required");

        const data: Record<string, any> = {};
        if (workplace !== undefined) data.workplace = workplace || null;
        if (isActive !== undefined) data.is_active = isActive ? 1 : 0;
        if (parentScript !== undefined) data.parent_script = parentScript || null;
        if (Object.keys(data).length === 0) return err("Nothing to update — provide workplace, is_active, or parent_script");

        if (data.parent_script && (data.workplace || (data.workplace === undefined))) {
          // subflow must have no workplace
          if (data.workplace) return err("Subflow (parent_script set) cannot have a workplace");
        }

        await erpnext.updateDocument("Workplace Script", scriptName, data);
        return ok(`Updated Workplace Script ${scriptName} (${Object.keys(data).join(", ")})`);
      }

      default:
        return err(`Unknown script tool: ${name}`);
    }
  } catch (e: any) {
    return err(e?.message || "Unknown error");
  }
}
