# WhatsApp + CRM Integration — Gap Analysis & Implementation Plan

> On approval, this document is written to `plans/whatsapp-crm-integration.md` in the erpnext repo.

## Context

Goal: build WhatsApp-centric CRM on top of native ERPNext desk (Lead/Contact/Customer/Opportunity/Quotation/Sales Order). Requirements: two-way WhatsApp chat stored in ERPNext, Contact-centric, personal **and group** chats, a Chat Center page, chat→CRM actions, plus deep CRM upgrades (Opportunity participants + deal documents, Quotation version/status/line-item history, supply status).

Starting point: **frappe_whatsapp** (`github.com/shridarpatil/frappe_whatsapp`) — mature app wrapping Meta's official **WhatsApp Cloud API**.

Decisions taken:
- **Groups** → add an **unofficial bridge** (whatsapp-web.js / Baileys / Green API) alongside official Cloud API. Official API cannot do groups.
- **CRM surface** → native ERPNext desk (not the frappe/crm Vue app).
- **Scope** → full spec, all 6 sections.

## What frappe_whatsapp already gives us (reuse)

| Capability | Where |
|---|---|
| Multi-account Cloud API send/receive | `WhatsApp Account` doctype, `utils/webhook.py` |
| Message store (Incoming/Outgoing, status, media, reactions, replies) | `WhatsApp Message` doctype |
| **Dynamic Link to any doctype** (`reference_doctype`+`reference_name`) | `whatsapp_message.json` — basis for CRM linking |
| `conversation_id`, `from`/`to`, `profile_name` | webhook post handler |
| Templates, Flows, Notifications, Bulk messaging | respective doctypes |
| Webhook inbound pipeline | `utils/webhook.py:post()` |

## Gaps vs requirements

| # | Requirement | Gap |
|---|---|---|
| 1.1 | Chat stored, Contact-bound, shown in CRM entities | Only flat message list + single Dynamic Link. No conversation-as-object, no Contact binding. |
| 1.2 | Contact = center (phone, personal dialogs, groups, links to Lead/Customer/Opp/Quote/SO) | No Contact-centric aggregation. |
| 1.3 | One dialog linked to **many** entities | Single Dynamic Link only → need child link table. |
| 1.4 | From chat: create Opportunity / Task / Note / Event; jump to entities | None. |
| 2 | Chat Center page (personal+group, manager tabs/filter, phone/contact search, entity jump) | No chat UI at all. |
| 3 | Group chats as objects (name, participants, managers, linked entities, history, files) | **Not supported by Cloud API** → unofficial bridge required. |
| 4.1 | Opportunity participants (contacts + managers, with roles) | Opportunity has single `contact_person`; no participants table. |
| 4.2 | Deal documents on Opportunity, shared to Quotation+SO, no dup | None. |
| 5.1–5.2 | Quotation version history + negotiation statuses | Amend chain overwrites; no version/status history. |
| 5.3 | Per-line-item change history (qty/price/add/remove, reasons, comments) | None. |
| 5.4 | Per-item supply status (ready / needs production / needs R&D …) | None. |
| 5.5 | Funnel shows full negotiation path | None. |
| 6 | Contact↔Opportunity↔Quotation↔SO relational spine | Partial (Quotation.opportunity link exists). |

## Architecture

### A. WhatsApp transport layer (two providers, one inbox)
- Keep **frappe_whatsapp** as the official-API provider (1:1 business messaging, templates, notifications).
- Add an **unofficial bridge microservice** (recommend **whatsapp-web.js**, Node) for **group** + personal-account messaging that Cloud API can't reach. Runs as a sidecar container; talks to ERPNext via whitelisted REST + webhook, mirroring frappe_whatsapp's inbound shape so messages land in the same `WhatsApp Message` store.
- Normalize both providers into `WhatsApp Message` with a `provider` field (`cloud` | `bridge`) and a `chat` link (below).

### B. Conversation & Contact model (new doctypes)
- **`WhatsApp Chat`** (new): the conversation object. Fields: `chat_type` (Personal | Group), `wa_chat_id` (provider thread id), `title`, `contact` (Link Contact, personal), `phone`, `provider`, `assigned_managers` (Table → User), `last_message_on`. Group extras: `participants` (child table: phone, contact, name, role), attached files.
- **`WhatsApp Chat Link`** (new child table on `WhatsApp Chat`): `reference_doctype` + `reference_name` (Dynamic Link) → one chat ↔ many of Lead/Contact/Customer/Opportunity/Quotation/Sales Order. Replaces the single link on the message.
- `WhatsApp Message` gains `chat` (Link → WhatsApp Chat). Webhook resolves/creates the Chat by `wa_chat_id`, resolves Contact by phone (`Contact Phone` lookup), links.
- **Contact** becomes the hub via a "WhatsApp" dashboard connection: personal chat + group memberships + related Lead/Customer/Opportunity/Quotation/SO (standard `links` + queries).

### C. Chat Center page
- New Frappe **Page** (`whatsapp_chat_center`, desk JS bundle) or a Frappe UI list workspace: left = chat list (tabs Personal/Group, manager filter, search by phone/contact), center = message thread, right = context panel showing all linked ERPNext entities + group memberships with jump links, plus action buttons.
- Reuse frappe_whatsapp send endpoints for outbound; bridge endpoint for group/personal-account sends.

### D. Chat→CRM actions
- Right-panel buttons calling standard mappers: create **Opportunity** (`make_opportunity` pattern), **ToDo/Task**, **Note** (Comment/Note doctype), **Event** — each auto-linking back into `WhatsApp Chat Link`.

### E. Opportunity enhancements
- **`Opportunity Participant`** (new child table): `party_type` (Contact | User), `party`, `role` (Select: Main contact / Decision maker / Technical / Financial / Responsible manager / Involved manager). Add `participants` table to `opportunity.json`.
- **Deal documents**: reuse Frappe **File** attachments but centralize — add a "Deal Documents" view that surfaces Opportunity attachments on linked Quotation/Sales Order (query by opportunity chain) so no manual duplication. Files stay attached to Opportunity; Quotation/SO read-through.
- Files touched: `erpnext/crm/doctype/opportunity/opportunity.json`, `.py`, new child doctype dir.

### F. Quotation negotiation history (biggest CRM piece)
- **`Quotation Version`** (new doctype, one row per save/snapshot): `quotation`, `version_no`, `datetime`, `author`, `status`, `changes_summary`, `change_reason`, `amount_before`/`amount_after`, `qty_before`/`qty_after`, snapshot JSON.
- **`Quotation Item Change`** (new child/log): per line — `item`, `qty_before`/`qty_after`, `price_before`/`price_after`, `action` (add/remove/modify), `change_reason` (Select: client declined / budget / tech reqs / model swap / qty unavailable / long lead / needs R&D …), `manager_comment`, `client_comment`.
- **Negotiation status** on Quotation: new `negotiation_status` Select (draft / internal approval / sent / feedback received / needs edit / resent / approved / partially approved / rejected / converted). Distinct from ERPNext's built-in `status`. **Exact list to be confirmed with business** (spec 5.2 says so).
- **Supply status per item**: add `supply_status` Select to `Quotation Item` (ready / needs production / needs R&D / partially in stock / awaiting purchase / needs tech approval / unavailable).
- Capture: hook Quotation `on_update` / `before_save` to diff items vs last snapshot and write a `Quotation Version` + `Quotation Item Change` rows. Reuse Frappe's `get_version` diff util where possible.
- Files: `erpnext/selling/doctype/quotation/quotation.json`+`.py`, `quotation_item.json`, new doctypes under `erpnext/selling/doctype/`.

### G. Funnel / reporting (5.5)
- Report/dashboard over `Quotation Version` + `Opportunity`: revisions count, amount trajectory, qty trajectory, removed items, reasons, approval duration, final version. Build as Query Report or Insights dashboard.

### H. Relational spine (section 6)
- Contact ↔ Lead/Customer via existing `links`. Opportunity.participants (E). Quotation.opportunity (exists). Sales Order ← Quotation (exists) + surface Opportunity/Quotation/version history on SO via dashboard connections.

## Schema-change policy
Per repo CLAUDE.md: new **DocTypes** → JSON + `__init__.py` committed to repo, synced by `./deploy build`. New **Custom Fields** on stock doctypes (Opportunity/Quotation/Quotation Item/WhatsApp Message) → add to `erpnext/patches/setup_custom_fields.py` (idempotent, runs every deploy). All user-facing strings → `__()`/`_()` + Ukrainian pair in `erpnext/translations/uk.csv` same commit.

## Delivery phases
1. **Foundation**: install frappe_whatsapp (add to `apps.json`), Cloud API account, webhook. Verify 1:1 send/receive.
2. **Conversation model**: `WhatsApp Chat` + `WhatsApp Chat Link`, `chat`/`provider` fields, webhook rewrite to resolve Contact + Chat. Contact dashboard.
3. **Chat Center page** + chat→CRM actions.
4. **Bridge service** for groups/personal-account; group doctype fields + participants; merge into inbox.
5. **Opportunity**: participants + deal-documents view.
6. **Quotation**: versioning + item-change log + negotiation status + supply status.
7. **Funnel report/dashboard** + SO linkage.

## Open items to confirm with business
- Exact negotiation status list (spec 5.2 explicitly defers).
- Bridge provider choice (whatsapp-web.js self-host vs Green API SaaS) — ToS/ban tolerance.
- Whether personal-account 1:1 also routes through bridge or stays Cloud API.

## Verification
- **Transport**: send/receive 1:1 via Cloud API sandbox number → message appears as `WhatsApp Message`, linked to auto-resolved `WhatsApp Chat`+Contact. Group message via bridge → group `WhatsApp Chat` with participants.
- **Linking**: from a chat, link to an Opportunity → appears in Opportunity dashboard and in chat context panel; verify one chat linked to 2+ entities.
- **Actions**: create Opportunity/Task/Note/Event from chat → back-link present.
- **Quotation history**: edit a Quotation twice (change qty, price, remove an item) → two `Quotation Version` rows with correct before/after + item-change rows; funnel report shows the path.
- **Opportunity**: add participants with roles; attach a document → visible read-through on linked Quotation/SO.
- Run in local env; use `mcp__erp-local__*` MCP tools + `./deploy build --silent` to apply.
