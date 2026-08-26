#!/usr/bin/env node

/**
 * ERPNext MCP Server
 * This server provides integration with the ERPNext/Frappe API, allowing:
 * - Authentication with ERPNext
 * - Fetching documents from ERPNext
 * - Querying lists of documents
 * - Creating and updating documents
 * - Running reports
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListResourcesRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListToolsRequestSchema,
  McpError,
  ReadResourceRequestSchema
} from "@modelcontextprotocol/sdk/types.js";
import axios, { AxiosInstance } from "axios";
import { SCRIPT_TOOLS, isScriptTool, handleScriptTool } from "./scripts.js";
import { LABEL_TEMPLATE_TOOLS, isLabelTemplateTool, handleLabelTemplateTool } from "./labelTemplate.js";

// ERPNext API client configuration
export class ERPNextClient {
  private baseUrl: string;
  private axiosInstance: AxiosInstance;
  private authenticated: boolean = false;

  constructor() {
    // Get ERPNext configuration from environment variables
    this.baseUrl = process.env.ERPNEXT_URL || '';
    
    // Validate configuration
    if (!this.baseUrl) {
      throw new Error("ERPNEXT_URL environment variable is required");
    }
    
    // Remove trailing slash if present
    this.baseUrl = this.baseUrl.replace(/\/$/, '');
    
    // Initialize axios instance
    this.axiosInstance = axios.create({
      baseURL: this.baseUrl,
      withCredentials: true,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    });
    
    // Configure authentication if credentials provided
    const apiKey = process.env.ERPNEXT_API_KEY;
    const apiSecret = process.env.ERPNEXT_API_SECRET;
    
    if (apiKey && apiSecret) {
      this.axiosInstance.defaults.headers.common['Authorization'] = 
        `token ${apiKey}:${apiSecret}`;
      this.authenticated = true;
    }
  }

  isAuthenticated(): boolean {
    return this.authenticated;
  }

  // Extract detailed error message from Frappe API response
  private extractErrorDetail(error: any): string {
    if (error?.response?.data) {
      const data = error.response.data;
      // Frappe sends _server_messages as JSON-encoded array of JSON strings
      if (data._server_messages) {
        try {
          const msgs = JSON.parse(data._server_messages);
          const parsed = msgs.map((m: string) => {
            try { return JSON.parse(m).message || m; } catch { return m; }
          });
          return parsed.join('; ');
        } catch { /* fall through */ }
      }
      if (data.message) return data.message;
      if (data.exc_type) return `${data.exc_type}: ${data.exc || ''}`;
      if (typeof data === 'string') return data;
    }
    return error?.message || 'Unknown error';
  }

  // Get a document by doctype and name
  async getDocument(doctype: string, name: string): Promise<any> {
    try {
      const response = await this.axiosInstance.get(`/api/resource/${doctype}/${name}`);
      return response.data.data;
    } catch (error: any) {
      throw new Error(`Failed to get ${doctype} ${name}: ${error?.message || 'Unknown error'}`);
    }
  }

  // Get list of documents for a doctype
  async getDocList(doctype: string, filters?: Record<string, any>, fields?: string[], limit?: number): Promise<any[]> {
    try {
      let params: Record<string, any> = {};
      
      if (fields && fields.length) {
        params['fields'] = JSON.stringify(fields);
      }
      
      if (filters) {
        params['filters'] = JSON.stringify(filters);
      }
      
      if (limit) {
        params['limit_page_length'] = limit;
      }
      
      const response = await this.axiosInstance.get(`/api/resource/${doctype}`, { params });
      return response.data.data;
    } catch (error: any) {
      throw new Error(`Failed to get ${doctype} list: ${error?.message || 'Unknown error'}`);
    }
  }

  // Create a new document
  async createDocument(doctype: string, doc: Record<string, any>): Promise<any> {
    try {
      const response = await this.axiosInstance.post(`/api/resource/${doctype}`, {
        data: doc
      });
      return response.data.data;
    } catch (error: any) {
      const detail = this.extractErrorDetail(error);
      throw new Error(`Failed to create ${doctype}: ${detail}`);
    }
  }

  // Update an existing document
  async updateDocument(doctype: string, name: string, doc: Record<string, any>): Promise<any> {
    try {
      const response = await this.axiosInstance.put(`/api/resource/${doctype}/${name}`, {
        data: doc
      });
      return response.data.data;
    } catch (error: any) {
      const detail = this.extractErrorDetail(error);
      throw new Error(`Failed to update ${doctype} ${name}: ${detail}`);
    }
  }

  // Run a report
  async runReport(reportName: string, filters?: Record<string, any>): Promise<any> {
    try {
      const response = await this.axiosInstance.get(`/api/method/frappe.desk.query_report.run`, {
        params: {
          report_name: reportName,
          filters: filters ? JSON.stringify(filters) : undefined
        }
      });
      return response.data.message;
    } catch (error: any) {
      throw new Error(`Failed to run report ${reportName}: ${error?.message || 'Unknown error'}`);
    }
  }

  // Delete a document
  async deleteDocument(doctype: string, name: string): Promise<any> {
    try {
      const response = await this.axiosInstance.delete(`/api/resource/${doctype}/${name}`);
      return response.data;
    } catch (error: any) {
      throw new Error(`Failed to delete ${doctype} ${name}: ${error?.message || 'Unknown error'}`);
    }
  }

  // Call a Frappe whitelisted method
  async callMethod(method: string, args?: Record<string, any>): Promise<any> {
    try {
      const response = await this.axiosInstance.post(`/api/method/${method}`, args || {});
      return response.data.message;
    } catch (error: any) {
      const detail = this.extractErrorDetail(error);
      throw new Error(`Failed to call method ${method}: ${detail}`);
    }
  }

  // Submit a document (set docstatus = 1)
  async submitDocument(doctype: string, name: string): Promise<any> {
    try {
      // First get the full document (required by frappe.client.submit)
      const doc = await this.getDocument(doctype, name);
      doc.docstatus = 1;
      const response = await this.axiosInstance.post(`/api/method/frappe.client.submit`, { doc });
      return response.data.message;
    } catch (error: any) {
      const detail = error?.response?.data?._server_messages || error?.response?.data?.message || error?.message || 'Unknown error';
      throw new Error(`Failed to submit ${doctype} ${name}: ${detail}`);
    }
  }

  // Cancel a submitted document (set docstatus = 2)
  async cancelDocument(doctype: string, name: string): Promise<any> {
    try {
      const response = await this.axiosInstance.post(`/api/method/frappe.client.cancel`, {
        doctype,
        name
      });
      return response.data.message;
    } catch (error: any) {
      const detail = error?.response?.data?._server_messages || error?.response?.data?.message || error?.message || 'Unknown error';
      throw new Error(`Failed to cancel ${doctype} ${name}: ${detail}`);
    }
  }

  // Amend a cancelled document (creates a new amended copy)
  async amendDocument(doctype: string, name: string): Promise<any> {
    try {
      const response = await this.axiosInstance.post(`/api/method/frappe.client.amend`, {
        doctype,
        name
      });
      return response.data.message;
    } catch (error: any) {
      const detail = error?.response?.data?._server_messages || error?.response?.data?.message || error?.message || 'Unknown error';
      throw new Error(`Failed to amend ${doctype} ${name}: ${detail}`);
    }
  }

  // Upload a file to ERPNext
  async uploadFile(
    filename: string,
    filedata: string,
    doctype?: string,
    docname?: string,
    isPrivate?: boolean
  ): Promise<any> {
    try {
      const FormData = (await import('form-data')).default;
      const form = new FormData();
      form.append('file', Buffer.from(filedata, 'base64'), { filename });
      if (doctype) form.append('doctype', doctype);
      if (docname) form.append('docname', docname);
      form.append('is_private', isPrivate ? '1' : '0');

      const response = await this.axiosInstance.post('/api/method/upload_file', form, {
        headers: form.getHeaders()
      });
      return response.data.message;
    } catch (error: any) {
      throw new Error(`Failed to upload file ${filename}: ${error?.message || 'Unknown error'}`);
    }
  }

  // Get DocType metadata (field definitions)
  async getDocTypeMeta(doctype: string): Promise<any> {
    try {
      const response = await this.axiosInstance.get(`/api/doctype/${doctype}`);
      return response.data;
    } catch (error: any) {
      throw new Error(`Failed to get metadata for ${doctype}: ${error?.message || 'Unknown error'}`);
    }
  }

  // Get child table records via frappe.client.get_list
  async getChildDocList(doctype: string, parentDoctype: string, filters?: Record<string, any>, fields?: string[], limit?: number): Promise<any[]> {
    try {
      const args: Record<string, any> = {
        doctype,
        parent_doctype: parentDoctype,
      };
      if (fields && fields.length) args.fields = fields;
      if (filters) args.filters = filters;
      if (limit) args.limit_page_length = limit;

      const response = await this.axiosInstance.post('/api/method/frappe.client.get_list', args);
      return response.data.message;
    } catch (error: any) {
      throw new Error(`Failed to get ${doctype} list: ${error?.message || 'Unknown error'}`);
    }
  }

  // Get all available DocTypes
  async getAllDocTypes(): Promise<string[]> {
    try {
      // Use the standard REST API to fetch DocTypes
      const response = await this.axiosInstance.get('/api/resource/DocType', {
        params: {
          fields: JSON.stringify(["name"]),
          limit_page_length: 500 // Get more doctypes at once
        }
      });
      
      if (response.data && response.data.data) {
        return response.data.data.map((item: any) => item.name);
      }
      
      return [];
    } catch (error: any) {
      console.error("Failed to get DocTypes:", error?.message || 'Unknown error');
      
      // Try an alternative approach if the first one fails
      try {
        // Try using the method API to get doctypes
        const altResponse = await this.axiosInstance.get('/api/method/frappe.desk.search.search_link', {
          params: {
            doctype: 'DocType',
            txt: '',
            limit: 500
          }
        });
        
        if (altResponse.data && altResponse.data.results) {
          return altResponse.data.results.map((item: any) => item.value);
        }
        
        return [];
      } catch (altError: any) {
        console.error("Alternative DocType fetch failed:", altError?.message || 'Unknown error');
        
        // Fallback: Return a list of common DocTypes
        return [
          "Customer", "Supplier", "Item", "Sales Order", "Purchase Order",
          "Sales Invoice", "Purchase Invoice", "Employee", "Lead", "Opportunity",
          "Quotation", "Payment Entry", "Journal Entry", "Stock Entry"
        ];
      }
    }
  }
}

// Cache for doctype metadata
const doctypeCache = new Map<string, any>();

// Initialize ERPNext client
const erpnext = new ERPNextClient();

// Create an MCP server with capabilities for resources and tools
const server = new Server(
  {
    name: "erpnext-server",
    version: "0.1.0"
  },
  {
    capabilities: {
      resources: {},
      tools: {}
    }
  }
);

/**
 * Handler for listing available ERPNext resources.
 * Exposes DocTypes list as a resource and common doctypes as individual resources.
 */
server.setRequestHandler(ListResourcesRequestSchema, async () => {
  // List of common DocTypes to expose as individual resources
  const commonDoctypes = [
    "Customer",
    "Supplier",
    "Item",
    "Sales Order",
    "Purchase Order",
    "Sales Invoice",
    "Purchase Invoice",
    "Employee"
  ];

  const resources = [
    // Add a resource to get all doctypes
    {
      uri: "erpnext://DocTypes",
      name: "All DocTypes",
      mimeType: "application/json",
      description: "List of all available DocTypes in the ERPNext instance"
    }
  ];

  return {
    resources
  };
});

/**
 * Handler for resource templates.
 * Allows querying ERPNext documents by doctype and name.
 */
server.setRequestHandler(ListResourceTemplatesRequestSchema, async () => {
  const resourceTemplates = [
    {
      uriTemplate: "erpnext://{doctype}/{name}",
      name: "ERPNext Document",
      mimeType: "application/json",
      description: "Fetch an ERPNext document by doctype and name"
    }
  ];

  return { resourceTemplates };
});

/**
 * Handler for reading ERPNext resources.
 */
server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  if (!erpnext.isAuthenticated()) {
    throw new McpError(
      ErrorCode.InvalidRequest,
      "Not authenticated with ERPNext. Please configure API key authentication."
    );
  }

  const uri = request.params.uri;
  let result: any;

  // Handle special resource: erpnext://DocTypes (list of all doctypes)
  if (uri === "erpnext://DocTypes") {
    try {
      const doctypes = await erpnext.getAllDocTypes();
      result = { doctypes };
    } catch (error: any) {
      throw new McpError(
        ErrorCode.InternalError,
        `Failed to fetch DocTypes: ${error?.message || 'Unknown error'}`
      );
    }
  } else {
    // Handle document access: erpnext://{doctype}/{name}
    const documentMatch = uri.match(/^erpnext:\/\/([^\/]+)\/(.+)$/);
    if (documentMatch) {
      const doctype = decodeURIComponent(documentMatch[1]);
      const name = decodeURIComponent(documentMatch[2]);
      
      try {
        result = await erpnext.getDocument(doctype, name);
      } catch (error: any) {
        throw new McpError(
          ErrorCode.InvalidRequest,
          `Failed to fetch ${doctype} ${name}: ${error?.message || 'Unknown error'}`
        );
      }
    }
  }

  if (!result) {
    throw new McpError(
      ErrorCode.InvalidRequest,
      `Invalid ERPNext resource URI: ${uri}`
    );
  }

  return {
    contents: [{
      uri: request.params.uri,
      mimeType: "application/json",
      text: JSON.stringify(result, null, 2)
    }]
  };
});

/**
 * Handler that lists available tools.
 */
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "get_doctypes",
        description: "Get a list of all available DocTypes",
        inputSchema: {
          type: "object",
          properties: {}
        }
      },
      {
        name: "get_doctype_fields",
        description: "Get fields list for a specific DocType",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Customer, Item)"
            }
          },
            required: ["doctype"]
        }
      },
      {
        name: "get_documents",
        description: "Get a list of documents for a specific doctype",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Customer, Item)"
            },
            fields: {
              type: "array",
              items: {
                type: "string"
              },
              description: "Fields to include (optional)"
            },
            filters: {
              type: "object",
              additionalProperties: true,
              description: "Filters in the format {field: value} (optional)"
            },
            limit: {
              type: "number",
              description: "Maximum number of documents to return (optional)"
            },
            parent_doctype: {
              type: "string",
              description: "Parent DocType name — required when querying child table DocTypes (e.g., 'Item Attribute' for 'Item Attribute Value')"
            }
          },
          required: ["doctype"]
        }
      },
      {
        name: "create_document",
        description: "Create a new document in ERPNext. Creates in Draft state (docstatus=0). For submittable doctypes (Stock Entry, Sales Invoice, etc.), use submit_document after creating. Child table rows should be passed as arrays in the data object (e.g., items: [{item_code: 'X', qty: 1}]). Note: maximum ~5 child rows per request due to payload limits.",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Customer, Item)"
            },
            data: {
              type: "object",
              additionalProperties: true,
              description: "Document data"
            }
          },
          required: ["doctype", "data"]
        }
      },
      {
        name: "update_document",
        description: "Update an existing document in ERPNext",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Customer, Item)"
            },
            name: {
              type: "string",
              description: "Document name/ID"
            },
            data: {
              type: "object",
              additionalProperties: true,
              description: "Document data to update"
            }
          },
          required: ["doctype", "name", "data"]
        }
      },
      {
        name: "add_custom_field",
        description: "Add a custom field to a DocType via Customize Form",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "Target DocType (e.g., Workstation, Item)"
            },
            label: {
              type: "string",
              description: "Field label (e.g., Barcode)"
            },
            fieldname: {
              type: "string",
              description: "Field name (e.g., custom_barcode)"
            },
            fieldtype: {
              type: "string",
              description: "Field type (e.g., Data, Link, Check, Select, Small Text)"
            },
            options: {
              type: "string",
              description: "Options - for Data with Barcode scanner use 'Barcode', for Link use DocType name, for Select use newline-separated values"
            },
            insert_after: {
              type: "string",
              description: "Fieldname to insert after (optional)"
            },
            reqd: {
              type: "number",
              description: "Required field (0 or 1, optional)"
            }
          },
          required: ["doctype", "label", "fieldname", "fieldtype"]
        }
      },
      {
        name: "run_report",
        description: "Run an ERPNext report",
        inputSchema: {
          type: "object",
          properties: {
            report_name: {
              type: "string",
              description: "Name of the report"
            },
            filters: {
              type: "object",
              additionalProperties: true,
              description: "Report filters (optional)"
            }
          },
          required: ["report_name"]
        }
      },
      {
        name: "delete_document",
        description: "Delete a document from ERPNext",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Customer, Item)"
            },
            name: {
              type: "string",
              description: "Document name/ID to delete"
            }
          },
          required: ["doctype", "name"]
        }
      },
      {
        name: "call_method",
        description: "Call a Frappe whitelisted method (API endpoint). Useful for: frappe.client.get (fetch full doc), frappe.client.insert (create with child tables), frappe.client.get_count, frappe.client.get_list. Args are passed as POST body. For frappe.client.insert, pass {doc: {doctype: 'X', ...fields, child_table: [{...}]}}.",
        inputSchema: {
          type: "object",
          properties: {
            method: {
              type: "string",
              description: "Full method path (e.g., frappe.client.get_count, erpnext.manufacturing.page.workplace_portal.workplace_portal.get_workplaces)"
            },
            args: {
              type: "object",
              additionalProperties: true,
              description: "Method arguments (optional)"
            }
          },
          required: ["method"]
        }
      },
      {
        name: "submit_document",
        description: "Submit a draft document in ERPNext (sets docstatus=1). The document must be in Draft state (docstatus=0). This is equivalent to clicking the Submit button in the UI. Works for Stock Entry, Sales Invoice, Purchase Invoice, Journal Entry, Work Order, BOM, etc.",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Stock Entry, Sales Invoice, BOM)"
            },
            name: {
              type: "string",
              description: "Document name/ID (e.g., MAT-STE-2026-00005)"
            }
          },
          required: ["doctype", "name"]
        }
      },
      {
        name: "cancel_document",
        description: "Cancel a submitted document in ERPNext (sets docstatus=2). The document must be in Submitted state (docstatus=1). This is equivalent to clicking Amend > Cancel in the UI.",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType (e.g., Stock Entry, Sales Invoice)"
            },
            name: {
              type: "string",
              description: "Document name/ID"
            }
          },
          required: ["doctype", "name"]
        }
      },
      {
        name: "amend_document",
        description: "Amend a cancelled document in ERPNext. Creates a new copy of the cancelled document in Draft state that can be modified and resubmitted.",
        inputSchema: {
          type: "object",
          properties: {
            doctype: {
              type: "string",
              description: "ERPNext DocType"
            },
            name: {
              type: "string",
              description: "Document name/ID of the cancelled document"
            }
          },
          required: ["doctype", "name"]
        }
      },
      {
        name: "upload_file",
        description: "Upload a file to ERPNext. File content must be base64 encoded.",
        inputSchema: {
          type: "object",
          properties: {
            filename: {
              type: "string",
              description: "File name (e.g., diagram.drawio, photo.png)"
            },
            filedata: {
              type: "string",
              description: "Base64-encoded file content"
            },
            doctype: {
              type: "string",
              description: "Attach to this DocType (optional)"
            },
            docname: {
              type: "string",
              description: "Attach to this document name (optional)"
            },
            is_private: {
              type: "boolean",
              description: "Upload as private file (default false)"
            }
          },
          required: ["filename", "filedata"]
        }
      },
      ...SCRIPT_TOOLS,
      ...LABEL_TEMPLATE_TOOLS
    ]
  };
});

/**
 * Handler for tool calls.
 */
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  switch (request.params.name) {
    case "get_documents": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      const doctype = String(request.params.arguments?.doctype);
      const fields = request.params.arguments?.fields as string[] | undefined;
      const filters = request.params.arguments?.filters as Record<string, any> | undefined;
      const limit = request.params.arguments?.limit as number | undefined;
      const parentDoctype = request.params.arguments?.parent_doctype as string | undefined;

      if (!doctype) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "Doctype is required"
        );
      }

      try {
        const documents = parentDoctype
          ? await erpnext.getChildDocList(doctype, parentDoctype, filters, fields, limit)
          : await erpnext.getDocList(doctype, filters, fields, limit);
        return {
          content: [{
            type: "text",
            text: JSON.stringify(documents, null, 2)
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to get ${doctype} documents: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
    
    case "create_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      const doctype = String(request.params.arguments?.doctype);
      const data = request.params.arguments?.data as Record<string, any> | undefined;
      
      if (!doctype || !data) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "Doctype and data are required"
        );
      }
      
      try {
        const result = await erpnext.createDocument(doctype, data);
        return {
          content: [{
            type: "text",
            text: `Created ${doctype}: ${result.name}\n\n${JSON.stringify(result, null, 2)}`
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to create ${doctype}: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
    
    case "update_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      const doctype = String(request.params.arguments?.doctype);
      const name = String(request.params.arguments?.name);
      const data = request.params.arguments?.data as Record<string, any> | undefined;
      
      if (!doctype || !name || !data) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "Doctype, name, and data are required"
        );
      }
      
      try {
        const result = await erpnext.updateDocument(doctype, name, data);
        return {
          content: [{
            type: "text",
            text: `Updated ${doctype} ${name}\n\n${JSON.stringify(result, null, 2)}`
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to update ${doctype} ${name}: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
    
    case "run_report": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      const reportName = String(request.params.arguments?.report_name);
      const filters = request.params.arguments?.filters as Record<string, any> | undefined;
      
      if (!reportName) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "Report name is required"
        );
      }
      
      try {
        const result = await erpnext.runReport(reportName, filters);
        return {
          content: [{
            type: "text",
            text: JSON.stringify(result, null, 2)
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to run report ${reportName}: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
    
    case "add_custom_field": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }

      const doctype = String(request.params.arguments?.doctype);
      const label = String(request.params.arguments?.label);
      const fieldname = String(request.params.arguments?.fieldname);
      const fieldtype = String(request.params.arguments?.fieldtype);
      const options = request.params.arguments?.options as string | undefined;
      const insert_after = request.params.arguments?.insert_after as string | undefined;
      const reqd = request.params.arguments?.reqd as number | undefined;

      if (!doctype || !label || !fieldname || !fieldtype) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "doctype, label, fieldname, and fieldtype are required"
        );
      }

      try {
        const data: Record<string, any> = {
          dt: doctype,
          label: label,
          fieldname: fieldname,
          fieldtype: fieldtype,
        };
        if (options) data.options = options;
        if (insert_after) data.insert_after = insert_after;
        if (reqd !== undefined) data.reqd = reqd;

        const result = await erpnext.createDocument("Custom Field", data);
        return {
          content: [{
            type: "text",
            text: `Added custom field '${label}' (${fieldtype}) to ${doctype}\n\n${JSON.stringify(result, null, 2)}`
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to add custom field to ${doctype}: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }

    case "get_doctype_fields": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      const doctype = String(request.params.arguments?.doctype);
      
      if (!doctype) {
        throw new McpError(
          ErrorCode.InvalidParams,
          "Doctype is required"
        );
      }
      
      try {
        const meta = await erpnext.getDocTypeMeta(doctype);
        const fields = (meta.docs?.[0]?.fields || []).map((f: any) => ({
          fieldname: f.fieldname,
          fieldtype: f.fieldtype,
          label: f.label,
          options: f.options || null,
          reqd: f.reqd || 0,
        }));

        return {
          content: [{
            type: "text",
            text: JSON.stringify(fields, null, 2)
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to get fields for ${doctype}: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
    
    case "delete_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext. Please configure API key authentication." }],
          isError: true
        };
      }

      const doctype = String(request.params.arguments?.doctype);
      const name = String(request.params.arguments?.name);

      if (!doctype || !name) {
        throw new McpError(ErrorCode.InvalidParams, "Doctype and name are required");
      }

      try {
        await erpnext.deleteDocument(doctype, name);
        return {
          content: [{ type: "text", text: `Deleted ${doctype}: ${name}` }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to delete ${doctype} ${name}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "call_method": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext. Please configure API key authentication." }],
          isError: true
        };
      }

      const method = String(request.params.arguments?.method);
      const args = request.params.arguments?.args as Record<string, any> | undefined;

      if (!method) {
        throw new McpError(ErrorCode.InvalidParams, "Method is required");
      }

      try {
        const result = await erpnext.callMethod(method, args);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to call ${method}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "submit_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext." }],
          isError: true
        };
      }

      const doctype = String(request.params.arguments?.doctype);
      const name = String(request.params.arguments?.name);

      if (!doctype || !name) {
        throw new McpError(ErrorCode.InvalidParams, "Doctype and name are required");
      }

      try {
        const result = await erpnext.submitDocument(doctype, name);
        return {
          content: [{ type: "text", text: `Submitted ${doctype}: ${name}\n\n${JSON.stringify(result, null, 2)}` }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to submit ${doctype} ${name}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "cancel_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext." }],
          isError: true
        };
      }

      const doctype = String(request.params.arguments?.doctype);
      const name = String(request.params.arguments?.name);

      if (!doctype || !name) {
        throw new McpError(ErrorCode.InvalidParams, "Doctype and name are required");
      }

      try {
        const result = await erpnext.cancelDocument(doctype, name);
        return {
          content: [{ type: "text", text: `Cancelled ${doctype}: ${name}\n\n${JSON.stringify(result, null, 2)}` }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to cancel ${doctype} ${name}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "amend_document": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext." }],
          isError: true
        };
      }

      const doctype = String(request.params.arguments?.doctype);
      const name = String(request.params.arguments?.name);

      if (!doctype || !name) {
        throw new McpError(ErrorCode.InvalidParams, "Doctype and name are required");
      }

      try {
        const result = await erpnext.amendDocument(doctype, name);
        return {
          content: [{ type: "text", text: `Amended ${doctype}: ${name}\n\nNew draft: ${JSON.stringify(result, null, 2)}` }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to amend ${doctype} ${name}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "upload_file": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{ type: "text", text: "Not authenticated with ERPNext. Please configure API key authentication." }],
          isError: true
        };
      }

      const filename = String(request.params.arguments?.filename);
      const filedata = String(request.params.arguments?.filedata);
      const doctype = request.params.arguments?.doctype as string | undefined;
      const docname = request.params.arguments?.docname as string | undefined;
      const is_private = request.params.arguments?.is_private as boolean | undefined;

      if (!filename || !filedata) {
        throw new McpError(ErrorCode.InvalidParams, "filename and filedata are required");
      }

      try {
        const result = await erpnext.uploadFile(filename, filedata, doctype, docname, is_private);
        return {
          content: [{ type: "text", text: `Uploaded file: ${filename}\n\n${JSON.stringify(result, null, 2)}` }]
        };
      } catch (error: any) {
        return {
          content: [{ type: "text", text: `Failed to upload ${filename}: ${error?.message || 'Unknown error'}` }],
          isError: true
        };
      }
    }

    case "get_doctypes": {
      if (!erpnext.isAuthenticated()) {
        return {
          content: [{
            type: "text",
            text: "Not authenticated with ERPNext. Please configure API key authentication."
          }],
          isError: true
        };
      }
      
      try {
        const doctypes = await erpnext.getAllDocTypes();
        return {
          content: [{
            type: "text",
            text: JSON.stringify(doctypes, null, 2)
          }]
        };
      } catch (error: any) {
        return {
          content: [{
            type: "text",
            text: `Failed to get DocTypes: ${error?.message || 'Unknown error'}`
          }],
          isError: true
        };
      }
    }
      
    default:
      if (isScriptTool(request.params.name)) {
        return await handleScriptTool(request.params.name, request.params.arguments, erpnext);
      }
      if (isLabelTemplateTool(request.params.name)) {
        return await handleLabelTemplateTool(request.params.name, request.params.arguments, erpnext);
      }
      throw new McpError(
        ErrorCode.MethodNotFound,
        `Unknown tool: ${request.params.name}`
      );
  }
});

/**
 * Start the server using stdio transport.
 */
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('ERPNext MCP server running on stdio');
}

main().catch((error) => {
  console.error("Server error:", error);
  process.exit(1);
});
