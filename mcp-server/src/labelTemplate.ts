/**
 * Tools for editing Label Templates and the Label Template Example library.
 *
 * The reference text + curated examples come from the ERPNext backend method
 * `erpnext.manufacturing.doctype.label_template.label_template.get_template_reference`,
 * which reads `erpnext/manufacturing/doctype/label_template/REFERENCE.md` plus all
 * published `Label Template Example` records. That same endpoint powers the in-app
 * "Template Reference" dialog, so the LLM and the human see the same authoring docs.
 *
 * Field model on Label Template (HTML mode):
 *   html_template            — Body content. <html>/<head>/<body> + .label-content
 *                              wrapper are added at render time.
 *   padding_top_mm,
 *   padding_right_mm,
 *   padding_bottom_mm,
 *   padding_left_mm          — Float (mm). Applied to the .label-content wrapper.
 *   field_mapping            — JSON string. Maps template field names → spec/doc
 *                              parameters with optional transforms (e.g. chemistry).
 *   preview_data             — JSON string used by the Preview pane.
 *   label_size               — Link to Label Size.
 *   template_type            — "EZPL" | "HTML".
 *   description              — Free text.
 */

import type { ERPNextClient } from "./index.js";

export const LABEL_TEMPLATE_TOOLS = [
  {
    name: "list_label_templates",
    description:
      "List Label Templates with name, label_size, template_type. Use before editing to find the right template.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_label_template",
    description:
      "Read a Label Template — html_template, padding fields, field_mapping, preview_data, label_size. Use this before editing to see the current state.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Label Template name (the document name)" },
      },
      required: ["name"],
    },
  },
  {
    name: "edit_label_template",
    description:
      "Update fields on a Label Template. Provide only the fields you want to change. To validate the result, fetch get_label_template_reference first to check available utility classes (pl_Nmm/lr_Nmm/w_Nmm/...) and rendering rules. The body is wrapped in <body><div class=\"label-content\">...</div></body> at render time, so do NOT include <html>/<head>/<body> tags. Padding fields apply to the .label-content wrapper.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Label Template name" },
        html_template: {
          type: "string",
          description:
            "Body HTML only. Children with position:absolute;width:100%;height:100% fill the padded area, not the full label. Use <table> for layout (wkhtmltoimage has no flexbox).",
        },
        padding_top_mm: { type: "number" },
        padding_right_mm: { type: "number" },
        padding_bottom_mm: { type: "number" },
        padding_left_mm: { type: "number" },
        field_mapping: {
          type: "string",
          description: "JSON string. Format: {\"field\": {\"source\": \"spec|doc\", \"param\": \"Parameter Name\", \"transform\": \"chemistry\"}}",
        },
        preview_data: { type: "string", description: "JSON string used by the Preview pane" },
        description: { type: "string" },
        label_size: { type: "string", description: "Link to Label Size doc name" },
      },
      required: ["name"],
    },
  },
  {
    name: "get_label_template_reference",
    description:
      "Fetch the canonical Label Template authoring reference (utility classes, padding model, custom tags, layout tips) plus all published Label Template Examples. Read this BEFORE writing or editing a Label Template — it tells you what classes exist, how the wrapper works, and provides curated snippets you can adapt. Same source the in-app dialog reads.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "list_label_template_examples",
    description:
      "List Label Template Example records (the curated snippet library). Each example has title, category, html_snippet, description.",
    inputSchema: {
      type: "object",
      properties: {
        category: {
          type: "string",
          description: "Optional category filter: Basics | Layout | Barcode | Padding | Utility classes | Full example",
        },
        include_unpublished: { type: "boolean", description: "Default false" },
      },
    },
  },
  {
    name: "upsert_label_template_example",
    description:
      "Create or update a Label Template Example. Use this to grow the shared snippet library — examples surface in the in-app reference dialog and to subsequent get_label_template_reference calls. If a record with the given title exists, it is updated; otherwise a new one is created.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string" },
        category: {
          type: "string",
          description: "Basics | Layout | Barcode | Padding | Utility classes | Full example",
        },
        description_uk: { type: "string", description: "Short Ukrainian explanation shown above the snippet" },
        html_snippet: { type: "string" },
        notes: { type: "string" },
        display_order: { type: "number" },
        is_published: { type: "boolean" },
      },
      required: ["title", "category", "html_snippet"],
    },
  },
  {
    name: "delete_label_template_example",
    description: "Delete a Label Template Example by title.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string" },
      },
      required: ["title"],
    },
  },
];

const LABEL_TEMPLATE_TOOL_NAMES = new Set(LABEL_TEMPLATE_TOOLS.map((t) => t.name));

export function isLabelTemplateTool(name: string): boolean {
  return LABEL_TEMPLATE_TOOL_NAMES.has(name);
}

type ToolResult = { content: { type: "text"; text: string }[]; isError?: boolean };

const ok = (text: string): ToolResult => ({ content: [{ type: "text", text }] });
const err = (text: string): ToolResult => ({ content: [{ type: "text", text }], isError: true });
const json = (data: unknown): ToolResult => ok(JSON.stringify(data, null, 2));

function arg<T = any>(args: any, key: string): T {
  return args?.[key] as T;
}

const EDITABLE_FIELDS = [
  "html_template",
  "padding_top_mm",
  "padding_right_mm",
  "padding_bottom_mm",
  "padding_left_mm",
  "field_mapping",
  "preview_data",
  "description",
  "label_size",
] as const;

export async function handleLabelTemplateTool(
  name: string,
  args: any,
  erpnext: ERPNextClient,
): Promise<ToolResult> {
  if (!erpnext.isAuthenticated()) {
    return err("Not authenticated with ERPNext. Configure ERPNEXT_API_KEY / ERPNEXT_API_SECRET.");
  }

  try {
    switch (name) {
      case "list_label_templates": {
        const docs = await erpnext.getDocList(
          "Label Template",
          undefined,
          ["name", "label_size", "template_type", "reference_doctype"],
          200,
        );
        return json(docs);
      }

      case "get_label_template": {
        const n = arg<string>(args, "name");
        if (!n) return err("name is required");
        const doc = await erpnext.getDocument("Label Template", n);
        return json({
          name: doc.name,
          template_type: doc.template_type,
          label_size: doc.label_size,
          reference_doctype: doc.reference_doctype,
          source_field: doc.source_field,
          html_template: doc.html_template,
          zpl_template: doc.zpl_template,
          field_mapping: doc.field_mapping,
          preview_data: doc.preview_data,
          padding_top_mm: doc.padding_top_mm,
          padding_right_mm: doc.padding_right_mm,
          padding_bottom_mm: doc.padding_bottom_mm,
          padding_left_mm: doc.padding_left_mm,
          description: doc.description,
        });
      }

      case "edit_label_template": {
        const n = arg<string>(args, "name");
        if (!n) return err("name is required");
        const data: Record<string, any> = {};
        for (const f of EDITABLE_FIELDS) {
          const v = arg<any>(args, f);
          if (v !== undefined) data[f] = v;
        }
        if (Object.keys(data).length === 0) {
          return err("Provide at least one field to update");
        }
        await erpnext.updateDocument("Label Template", n, data);
        return ok(`Updated Label Template ${n}: ${Object.keys(data).join(", ")}`);
      }

      case "get_label_template_reference": {
        const result = await erpnext.callMethod(
          "erpnext.manufacturing.doctype.label_template.label_template.get_template_reference",
        );
        const payload = result?.message ?? result;
        return json({
          reference_md: payload?.reference_md,
          examples: payload?.examples,
        });
      }

      case "list_label_template_examples": {
        const category = arg<string | undefined>(args, "category");
        const includeUnpublished = arg<boolean | undefined>(args, "include_unpublished") ?? false;
        const filters: Record<string, any> = {};
        if (!includeUnpublished) filters.is_published = 1;
        if (category) filters.category = category;
        const docs = await erpnext.getDocList(
          "Label Template Example",
          filters,
          ["title", "category", "description_uk", "html_snippet", "notes", "display_order", "is_published"],
          500,
        );
        return json(docs);
      }

      case "upsert_label_template_example": {
        const title = arg<string>(args, "title");
        const category = arg<string>(args, "category");
        const html_snippet = arg<string>(args, "html_snippet");
        if (!title || !category || !html_snippet) {
          return err("title, category and html_snippet are required");
        }
        const data: Record<string, any> = {
          title,
          category,
          html_snippet,
          description_uk: arg<string | undefined>(args, "description_uk"),
          notes: arg<string | undefined>(args, "notes"),
          display_order: arg<number | undefined>(args, "display_order") ?? 0,
          is_published: arg<boolean | undefined>(args, "is_published") === false ? 0 : 1,
        };

        let exists = true;
        try {
          await erpnext.getDocument("Label Template Example", title);
        } catch {
          exists = false;
        }

        if (exists) {
          await erpnext.updateDocument("Label Template Example", title, data);
          return ok(`Updated Label Template Example "${title}"`);
        } else {
          await erpnext.createDocument("Label Template Example", data);
          return ok(`Created Label Template Example "${title}"`);
        }
      }

      case "delete_label_template_example": {
        const title = arg<string>(args, "title");
        if (!title) return err("title is required");
        await erpnext.deleteDocument("Label Template Example", title);
        return ok(`Deleted Label Template Example "${title}"`);
      }

      default:
        return err(`Unknown label template tool: ${name}`);
    }
  } catch (e: any) {
    return err(e?.message || "Unknown error");
  }
}
