/**
 * Tools for editing Label Templates and the Label Template Example library.
 *
 * The reference text + curated examples come from the ERPNext backend method
 * `erpnext.devices.doctype.label_template.label_template.get_template_reference`,
 * which reads `erpnext/manufacturing/doctype/label_template/REFERENCE.md` plus all
 * published `Label Template Example` records. That same endpoint powers the in-app
 * "Template Reference" dialog, so the LLM and the human see the same authoring docs.
 *
 * render_label_preview returns the printer-exact PNG as an MCP image block, so the model can
 * look at the label, fix layout_json / html_template and render again.
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
 *   template_type            — "From DocType" | "Raw Data" | "Barcode" | "Other".
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
        editor_mode: {
          type: "string",
          enum: ["HTML", "Visual"],
          description: "Visual: html_template is generated from layout_json on save (do not edit html_template then)",
        },
        layout_json: {
          type: "string",
          description:
            "Visual layout JSON: {\"v\":1,\"grid_mm\":0.5,\"elements\":[{\"id\",\"type\":\"text|field|input|image|barcode|qr|table|repeat|line|rect\",\"x\",\"y\",\"w\",\"h\" (mm inside padding),\"rotate\",\"show_if\" (Jinja condition),\"style\":{font_size_pt,font_family,bold,italic,underline,align,valign,nowrap,invert,border_mm,line_height}, ...}], \"setup\": \"optional Jinja run before elements; put computed values on doc via {% set _ = doc.update({...}) %} and show them with field elements\"}. Text supports **bold** and ^^sup^^; tables accept col_styles; repeat draws one barcode/qr/text block per list item. See REFERENCE.md \"Visual editor\" (get_label_template_reference).",
        },
        inputs: {
          type: "array",
          description:
            "REPLACES the Print Inputs table (values asked in the Print dialog, available as {{ doc.<fieldname> }} and bound by visual elements of type \"input\"). Pass the full list.",
          items: {
            type: "object",
            properties: {
              fieldname: { type: "string", description: "Python identifier, e.g. qty" },
              label: { type: "string" },
              fieldtype: { type: "string", enum: ["Data", "Small Text", "Int", "Float", "Date", "Select", "Check"] },
              options: { type: "string", description: "Select: one option per line" },
              default_value: { type: "string" },
              reqd: { type: "boolean" },
            },
            required: ["fieldname", "label"],
          },
        },
      },
      required: ["name"],
    },
  },
  {
    name: "render_label_preview",
    description:
      "Render a Label Template exactly as the printer gets it (wkhtmltoimage, 300 dpi, 1-bit) and return the PNG image so you can look at it. Use it after every edit to verify layout, clipping and wrapping, then fix and render again. Works on the saved template; pass `overrides` to preview unsaved changes (e.g. a new layout_json) without saving. Pass `input_values` to fill Print Inputs (as the Print dialog does).",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Label Template name" },
        input_values: {
          type: "object",
          description: "Values for Print Inputs by fieldname, e.g. {\"qty\": 12}. Missing ones use the input's default.",
          additionalProperties: true,
        },
        reference_name: {
          type: "string",
          description: "From DocType templates: document of reference_doctype whose data fills the label",
        },
        use_preview_data: {
          type: "boolean",
          description:
            "Default true: when no reference_name, fill doc from the template's preview_data sample. false = exactly what a print without a document would show.",
        },
        overrides: {
          type: "object",
          description:
            "Unsaved field values to render instead of the saved ones: layout_json, html_template, editor_mode, label_size, padding_*_mm, preview_data, field_mapping, inputs (array like edit_label_template).",
          additionalProperties: true,
        },
        include_html: { type: "boolean", description: "Also return the rendered HTML (default false)" },
      },
      required: ["name"],
    },
  },
  {
    name: "list_label_images",
    description:
      "List the shared label image library (folder Home/Label Images): file_name and file_url of every image labels can use. Use file_name in a visual layout image element (\"type\":\"image\",\"file\":<file_name>) or in <attachment name=\"...\"> in HTML templates.",
    inputSchema: { type: "object", properties: { search: { type: "string", description: "Optional substring filter" } } },
  },
  {
    name: "get_label_image",
    description:
      "Load one image from the label image library so you can look at it (PNG/JPEG/GIF/WebP come back as an image, SVG as its source text).",
    inputSchema: {
      type: "object",
      properties: { file_name: { type: "string", description: "file_name from list_label_images" } },
      required: ["file_name"],
    },
  },
  {
    name: "upload_label_image",
    description:
      "Add an image to the shared label image library (visible to everyone who edits label templates). Give either file_path (a file on this machine) or content_base64 + file_name. Returns the stored file_name (made unique if the name was taken) to use in layouts.",
    inputSchema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "Local path of an image file (png, jpg, gif, svg, webp, bmp)" },
        content_base64: { type: "string", description: "Image bytes as base64 (alternative to file_path)" },
        file_name: { type: "string", description: "Name to store; defaults to the file_path basename" },
      },
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

type ToolContent = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };
type ToolResult = { content: ToolContent[]; isError?: boolean };

const PREVIEW_FIELDS = [
  "editor_mode",
  "html_template",
  "layout_json",
  "label_size",
  "field_mapping",
  "preview_data",
  "reference_doctype",
  "padding_top_mm",
  "padding_right_mm",
  "padding_bottom_mm",
  "padding_left_mm",
] as const;

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
  "editor_mode",
  "layout_json",
  "inputs",
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
          editor_mode: doc.editor_mode,
          layout_json: doc.layout_json,
          inputs: doc.inputs,
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
        for (const k of ["layout_json", "preview_data", "field_mapping"]) {
          if (data[k] && typeof data[k] !== "string") data[k] = JSON.stringify(data[k]);
        }
        if (Array.isArray(data.inputs)) {
          data.inputs = data.inputs.map((r: any) => ({ ...r, reqd: r.reqd ? 1 : 0 }));
        }
        await erpnext.updateDocument("Label Template", n, data);
        return ok(`Updated Label Template ${n}: ${Object.keys(data).join(", ")}`);
      }

      case "render_label_preview": {
        const n = arg<string>(args, "name");
        if (!n) return err("name is required");
        const overrides = arg<Record<string, any> | undefined>(args, "overrides");
        const callArgs: Record<string, any> = {
          inputs: JSON.stringify(arg<Record<string, any>>(args, "input_values") ?? {}),
          sample: arg<boolean | undefined>(args, "use_preview_data") === false ? 0 : 1,
        };
        const ref = arg<string | undefined>(args, "reference_name");
        if (ref) callArgs.reference_name = ref;
        if (overrides && Object.keys(overrides).length) {
          const saved = await erpnext.getDocument("Label Template", n);
          const doc: Record<string, any> = {};
          for (const f of PREVIEW_FIELDS) doc[f] = saved[f];
          doc.inputs = (saved.inputs ?? []).map((r: any) => ({
            fieldname: r.fieldname,
            label: r.label,
            default_value: r.default_value,
            reqd: r.reqd,
          }));
          Object.assign(doc, overrides);
          for (const k of ["layout_json", "preview_data", "field_mapping"]) {
            if (doc[k] && typeof doc[k] !== "string") doc[k] = JSON.stringify(doc[k]);
          }
          callArgs.doc = JSON.stringify(doc);
        } else {
          callArgs.label_template = n;
        }
        const r = await erpnext.callMethod(
          "erpnext.devices.doctype.label_template.label_template.render_template_preview",
          callArgs,
        );
        if (!r?.image_base64) return err("Nothing to render: set label_size and a template/layout first.");
        const content: ToolContent[] = [
          { type: "image", data: r.image_base64, mimeType: "image/png" },
          {
            type: "text",
            text:
              `${n}${overrides ? " (unsaved overrides)" : ""}: ${r.width_mm} × ${r.height_mm} mm, ` +
              `${r.width_dots} × ${r.height_dots} dots @ ${r.dpi} dpi. 1 mm = ${(r.dpi / 25.4).toFixed(2)} px.`,
          },
        ];
        if (arg<boolean>(args, "include_html")) content.push({ type: "text", text: r.html ?? "" });
        return { content };
      }

      case "list_label_images": {
        const files: any[] = (await erpnext.callMethod("erpnext.devices.label_images.get_label_images")) ?? [];
        const q = (arg<string>(args, "search") ?? "").toLowerCase();
        return json(
          files
            .filter((f) => !q || String(f.file_name).toLowerCase().includes(q))
            .map((f) => ({ file_name: f.file_name, file_url: f.file_url })),
        );
      }

      case "get_label_image": {
        const fileName = arg<string>(args, "file_name");
        if (!fileName) return err("file_name is required");
        const files: any[] = (await erpnext.callMethod("erpnext.devices.label_images.get_label_images")) ?? [];
        const file = files.find((f) => f.file_name === fileName);
        if (!file) return err(`No image "${fileName}" in the label image library. Use list_label_images.`);
        const { data, contentType } = await erpnext.getBinary(file.file_url);
        if (contentType.includes("svg") || fileName.toLowerCase().endsWith(".svg")) {
          return ok(`${fileName} (SVG, ${data.length} bytes):\n${data.toString("utf8")}`);
        }
        const mimeType = contentType.split(";")[0].trim() || "image/png";
        return {
          content: [
            { type: "image", data: data.toString("base64"), mimeType },
            { type: "text", text: `${fileName} — ${file.file_url}, ${data.length} bytes` },
          ],
        };
      }

      case "upload_label_image": {
        const filePath = arg<string | undefined>(args, "file_path");
        let content = arg<string | undefined>(args, "content_base64");
        let fileName = arg<string | undefined>(args, "file_name");
        if (filePath) {
          const fs = await import("node:fs/promises");
          const path = await import("node:path");
          content = (await fs.readFile(filePath)).toString("base64");
          fileName = fileName || path.basename(filePath);
        }
        if (!content || !fileName) return err("Give file_path, or content_base64 together with file_name");
        const r = await erpnext.callMethod("erpnext.devices.label_images.add_label_image", {
          file_name: fileName,
          content_base64: content,
        });
        return json(r);
      }

      case "get_label_template_reference": {
        const result = await erpnext.callMethod(
          "erpnext.devices.doctype.label_template.label_template.get_template_reference",
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
