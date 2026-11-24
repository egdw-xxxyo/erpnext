/**
 * Tools for the Import Center: edit "Import Script" documents and dry-run them on a real file.
 *
 * Server side lives in erpnext/import_center/ (engine.py, doctypes, seed.py).
 * An Import Script holds: detection markers, Python code, required permissions, changed fields,
 * preview layout. Saving changed code appends a row to its `versions` table automatically.
 *
 * Script contract (exec'd with globals `frappe`, `json`; the file's own imports go inside):
 *   def parse(ctx)                 -> {"header": {...}, "<source>": [...], "warnings": [str]}
 *   def plan(ctx, parsed)          -> [{doctype, name, label, changes:[{field,label,old,new}], problem?, unchanged?}]
 *                                     NO writes. name=None means "entity not found" and blocks the import.
 *   def apply(ctx, parsed, plan)   -> stats dict. Writes via doc.save() (permission-checked).
 * ctx: file_path, run, user, stage, progress(percent, message).
 * Forbidden in code: ignore_permissions, frappe.db.sql, subprocess, os.system.
 */

import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import type { ERPNextClient } from "./index.js";

const CONTRACT = `
Import Script contract (Python, exec'd; globals: frappe, json — put other imports inside the functions):

  def parse(ctx):                 # read ctx.file_path, no DB writes
      ctx.progress(30, "Reading")
      return {"header": {...}, "months": [...], "warnings": ["text shown in yellow"]}

  def plan(ctx, parsed):          # read-only: decide what would change
      return [{"doctype": "Employee", "name": "HR-EMP-0001" | None, "label": "Full name",
               "changes": [{"field": "2026-10", "label": "10.2026", "old": 30, "new": 31}],
               "unchanged": 3, "problem": "text or None"}]
      # name=None -> entity not found, the Import button stays disabled.

  def apply(ctx, parsed, plan):   # writes; use doc.save() (permission-checked). Never ignore_permissions.
      ctx.stage = "import"; ctx.progress(50, "Writing")
      return {"created": 1, "updated": 2}   # shown after the import

ctx: file_path, run, user, stage ("parse"|"import"), progress(percent, message).
Forbidden tokens in code: ignore_permissions, frappe.db.sql, subprocess, os.system.

preview_config (JSON): {"sections": [
  {"kind": "key_value", "title": "...", "source": "header", "columns": [{"key": "x", "label": "X"}]},
  {"kind": "table", "title": "...", "source": "rows", "max_rows": 30, "columns": [{"key": "a", "label": "A"}]},
  {"kind": "grid", "title": "...", "source": "months"}   # rows {year, month, days} as a year x 12 matrix
]}  -- "source" is a key of the dict returned by parse().

markers: [{"where": "Text|Filename|Sheet Cell", "kind": "Contains|Regex", "value": "..."}]; ALL must match.
  Text = first 2 PDF pages / first 20 xlsx|csv rows (whitespace-insensitive, case-insensitive for Contains).
required_permissions: [{"reference_doctype": "Employee", "ptype": "read|write|create|delete"}]
change_fields: [{"reference_doctype": "Employee", "fieldname": "...", "label": "...", "mode": "Update|Create|Append"}]
file_types: pdf | xlsx | csv   (one per script)
`.trim();

export const IMPORT_SCRIPT_TOOLS = [
  {
    name: "get_import_script_reference",
    description:
      "Reference for writing an Import Script: function contract (parse/plan/apply), ctx API, preview_config, markers, permissions. Read before edit_import_script.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "list_import_scripts",
    description: "List Import Scripts (Import Center): title, file type, enabled, priority, version.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_import_script",
    description:
      "Get one Import Script: code, markers, required permissions, change fields, preview layout, version list. Pass `version` (number) to read the code of an older version.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Script name (= title)" },
        version: { type: "number", description: "Return the code saved as this version instead of the current one" },
      },
      required: ["name"],
    },
  },
  {
    name: "edit_import_script",
    description:
      "Create or update an Import Script. Only the fields you pass change; markers / required_permissions / change_fields replace the whole table when given. Changing `code` is validated (syntax, forbidden tokens) and appends a version. Run test_import_script on a real file afterwards (or before saving, with its `code` argument). See get_import_script_reference for the contract.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Existing script name (= title). Omit to create (then `title`, `file_types`, `code` are required)." },
        title: { type: "string" },
        code: { type: "string", description: "Full Python source defining parse/plan/apply" },
        file_types: { type: "string", enum: ["pdf", "xlsx", "csv"] },
        enabled: { type: "boolean" },
        priority: { type: "number", description: "Higher wins when several scripts match" },
        description: { type: "string" },
        preview_config: { description: "Preview layout: object or JSON string (see reference)" },
        markers: {
          type: "array",
          items: {
            type: "object",
            properties: {
              where: { type: "string", enum: ["Text", "Filename", "Sheet Cell"] },
              kind: { type: "string", enum: ["Contains", "Regex"] },
              value: { type: "string" },
            },
            required: ["value"],
          },
        },
        required_permissions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              reference_doctype: { type: "string" },
              ptype: { type: "string", enum: ["read", "write", "create", "delete"] },
            },
            required: ["reference_doctype", "ptype"],
          },
        },
        change_fields: {
          type: "array",
          items: {
            type: "object",
            properties: {
              reference_doctype: { type: "string" },
              fieldname: { type: "string" },
              label: { type: "string" },
              mode: { type: "string", enum: ["Update", "Create", "Append"] },
            },
            required: ["reference_doctype", "fieldname"],
          },
        },
      },
    },
  },
  {
    name: "restore_import_script_version",
    description: "Restore the code of an older Import Script version (saved as a new version).",
    inputSchema: {
      type: "object",
      properties: { name: { type: "string" }, version: { type: "number" } },
      required: ["name", "version"],
    },
  },
  {
    name: "test_import_script",
    description:
      "Dry-run an import on a real file and return the FULL output: file head text, per-marker detection of every script, chosen script, permission check, parsed data, plan (what would change), progress log, and with run_apply=true the result of apply() — executed in a transaction that is ALWAYS rolled back, so nothing is saved. Pass `code` to test an unsaved draft. Provide the file as a local `file_path` (uploaded privately and removed afterwards) or an existing server `file_url`. Needs System Manager.",
    inputSchema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "Absolute local path of the file to import" },
        file_url: { type: "string", description: "Existing File url on the server (alternative to file_path)" },
        script: { type: "string", description: "Force this script instead of auto-detection" },
        code: { type: "string", description: "Draft code to test instead of the saved code (not saved)" },
        run_apply: { type: "boolean", description: "Also run apply() inside a rolled-back transaction (default false)" },
        max_chars: { type: "number", description: "Truncate the returned JSON to this many characters (default 60000)" },
      },
    },
  },
];

const NAMES = new Set(IMPORT_SCRIPT_TOOLS.map((t) => t.name));

export function isImportScriptTool(name: string): boolean {
  return NAMES.has(name);
}

type ToolResult = { content: { type: "text"; text: string }[]; isError?: boolean };
const ok = (text: string): ToolResult => ({ content: [{ type: "text", text }] });
const err = (text: string): ToolResult => ({ content: [{ type: "text", text }], isError: true });
const json = (data: unknown): ToolResult => ok(JSON.stringify(data, null, 2));

const TABLES = ["markers", "required_permissions", "change_fields"] as const;
const SCALARS = ["title", "code", "file_types", "enabled", "priority", "description"] as const;

export async function handleImportScriptTool(
  name: string,
  args: any,
  erpnext: ERPNextClient,
): Promise<ToolResult> {
  if (!erpnext.isAuthenticated()) {
    return err("Not authenticated with ERPNext. Configure ERPNEXT_API_KEY / ERPNEXT_API_SECRET.");
  }

  try {
    switch (name) {
      case "get_import_script_reference":
        return ok(CONTRACT);

      case "list_import_scripts": {
        const docs = await erpnext.getDocList(
          "Import Script",
          undefined,
          ["name", "title", "file_types", "enabled", "priority", "version", "modified"],
          200,
        );
        return json(docs);
      }

      case "get_import_script": {
        if (!args?.name) return err("name is required");
        const doc = await erpnext.getDocument("Import Script", args.name);
        let code = doc.code;
        if (args.version !== undefined) {
          const row = (doc.versions || []).find((v: any) => Number(v.version) === Number(args.version));
          if (!row) return err(`Version ${args.version} not found on ${args.name}`);
          code = row.code;
        }
        return json({
          name: doc.name,
          title: doc.title,
          enabled: !!doc.enabled,
          priority: doc.priority,
          file_types: doc.file_types,
          description: doc.description,
          version: doc.version,
          markers: (doc.markers || []).map((m: any) => ({ where: m.where, kind: m.kind, value: m.value })),
          required_permissions: (doc.required_permissions || []).map((r: any) => ({
            reference_doctype: r.reference_doctype,
            ptype: r.ptype,
          })),
          change_fields: (doc.change_fields || []).map((c: any) => ({
            reference_doctype: c.reference_doctype,
            fieldname: c.fieldname,
            label: c.label,
            mode: c.mode,
          })),
          preview_config: doc.preview_config ? safeParse(doc.preview_config) : null,
          versions: (doc.versions || []).map((v: any) => ({
            version: v.version,
            saved_on: v.saved_on,
            saved_by: v.saved_by,
          })),
          code,
        });
      }

      case "edit_import_script": {
        const payload: Record<string, any> = {};
        for (const key of SCALARS) if (args?.[key] !== undefined) payload[key] = args[key];
        for (const key of TABLES) if (args?.[key] !== undefined) payload[key] = args[key];
        if (args?.preview_config !== undefined) {
          payload.preview_config =
            typeof args.preview_config === "string"
              ? args.preview_config
              : JSON.stringify(args.preview_config, null, 1);
        }
        for (const key of ["enabled"] as const) if (key in payload) payload[key] = payload[key] ? 1 : 0;

        if (args?.name) {
          const saved = await erpnext.updateDocument("Import Script", args.name, payload);
          return json({ updated: saved.name, version: saved.version });
        }
        for (const required of ["title", "file_types", "code"]) {
          if (!payload[required]) return err(`${required} is required to create an Import Script`);
        }
        const created = await erpnext.createDocument("Import Script", payload);
        return json({ created: created.name, version: created.version });
      }

      case "restore_import_script_version": {
        const doc = await erpnext.getDocument("Import Script", args?.name);
        const row = (doc.versions || []).find((v: any) => Number(v.version) === Number(args?.version));
        if (!row) return err(`Version ${args?.version} not found on ${args?.name}`);
        const saved = await erpnext.updateDocument("Import Script", args.name, { code: row.code });
        return json({ restored_from: args.version, new_version: saved.version });
      }

      case "test_import_script": {
        let fileUrl: string | undefined = args?.file_url;
        let temporary = false;
        let fileDoc: string | undefined;
        if (!fileUrl) {
          if (!args?.file_path) return err("file_path or file_url is required");
          const data = await readFile(args.file_path);
          const uploaded = await erpnext.uploadFile(
            basename(args.file_path),
            data.toString("base64"),
            undefined,
            undefined,
            true,
          );
          fileUrl = uploaded.file_url;
          temporary = true;
          fileDoc = uploaded.name as string;
        }

        try {
          const report = await erpnext.callMethod("erpnext.import_center.engine.test_import", {
            file_url: fileUrl,
            script: args?.script,
            code: args?.code,
            run_apply: args?.run_apply ? 1 : 0,
          });
          const text = JSON.stringify(report, null, 2);
          const limit = Number(args?.max_chars) || 60000;
          return ok(text.length > limit ? `${text.slice(0, limit)}\n… truncated (${text.length} chars)` : text);
        } finally {
          if (temporary) {
            try {
              await erpnext.deleteDocument("File", fileDoc!);
            } catch {
              /* temp file is private and purged with the site; ignore */
            }
          }
        }
      }
    }
    return err(`Unknown tool ${name}`);
  } catch (e: any) {
    return err(e?.message || String(e));
  }
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
