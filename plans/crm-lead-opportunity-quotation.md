# CRM: Lead → Opportunity → Quotation — gap analysis and implementation plan

Source specs: `Ліди.md`, `# Пропозиція.md`, `# Угода.md`.

Naming decision: the Ukrainian names already shipped in `erpnext/translations/uk.csv` stay as they are —
**Lead = Звернення**, **Opportunity = Пропозиція**, **Quotation = Угода**. The specs' alternative
"Запит" for Lead is not adopted; wherever a spec says "Запит" read "Звернення".

All schema work goes into `erpnext/patches/setup_custom_fields.py` (Custom Fields + Property Setters),
never into stock DocType JSON. List/form behaviour goes into the existing
`lead.js` / `lead_list.js` / `opportunity.js` / `opportunity_list.js` / a new `quotation.js` addition.

---

## 1. Lead (Звернення) — mostly implemented

### Already done (no work needed)

- Status set `New Request / Contacted / Requirement Gathering / Awaiting Response /
  Result of Processing / Postponed / Converted to Opportunity / Not Relevant / Lost`.
- Final statuses read-only for Sales User, `revert_from_final_status` for Sales Manager,
  `Lead Status Reversal` history table.
- `Converted to Opportunity` set by the system only (`validate_conversion_status`).
- Per-status mandatory fields (`STATUS_REQUIRED_FIELDS`): next action, processing result,
  return date + hold reason, close reason.
- `customer_need`, `requirement` (`Lead Requirement` child), `conversion_probability`,
  `next_action` + `next_action_date` + `next_action_overdue` + daily Notification.
- Prospect / Customer link, Military Unit entry point, contact person query.
- List view: closed Leads filtered out by default, overdue indicator, quick-filter buttons.
- «Канал залучення» values exist as UTM Source records (Онлайн, Офлайн, Рекомендації,
  Холодний контакт, Державні закупівлі, Партнерські організації, Інше).

### Missing

1. **Hide the fields the spec drops.** Property Setters `hidden = 1` on Lead:
   `job_title`, `salutation`, `gender`, `annual_revenue`, `no_of_employees`, `industry`,
   `fax`, `market_segment`, and the whole qualification block
   (`qualification_section`, `qualification_status`, `qualified_by`, `qualified_on`).
   Note `lead_list.js` "Create Prospect" reads `no_of_employees / industry / market_segment / fax` —
   hidden fields still read fine, no change needed there.
2. **`request_type` → «Мета звернення».** Property Setter for `label` and for `options`:
   `Product Purchase / Commercial Proposal Request / Technical Information Request / Demonstration /
   Testing / Consultation / Partnership / Training / Other`. English msgids + uk.csv pairs.
3. **`utm_source` → «Канал залучення».** Property Setter `label`. Values already exist.
   The second-level examples in the spec are documentation only — do not create records for them.
4. **`conversion_probability` — 5 values, not 3.** Property Setter `options`:
   `Very Low / Low / Medium / High / Very High` (currently `Low/Medium/High Probability`).
   Migration: map existing rows to the new values in the same patch.
5. **`Lead Requirement`: add «Орієнтовні терміни постачання».** New field `delivery_timeline`
   (Data) in `lead_requirement.json`. Existing `item_group` / `qty` / `budget` / `comment` keep
   their names. All fields stay optional.
6. **Business quick filters.** `in_standard_filter = 1` via Property Setter on `status`,
   `lead_owner`, `request_type`, `utm_source` (`next_action_date` already has it).
7. **Drop the "default filter = unqualified" requirement** — the qualification block is hidden
   per the same spec, so it has no field to filter on. Default stays "active Leads".
8. **Translation gap**: `Result of Processing` is missing from `uk.csv`.

---

## 2. Opportunity (Пропозиція) — largest functional gap

Present today: Deal tab, `Opportunity Participant` table, deal documents HTML, military unit
autofill. Everything below is new.

1. **Status model.** Property Setter `options` → `New / Converted to Quotation / Lost`
   (stock: `Open/Quotation/Converted/Lost/Replied/Closed`), with a migration mapping existing rows.
   - `Converted to Quotation` set by the system only, on Quotation creation — mirror
     `Lead.validate_conversion_status` / `mark_converted_to_opportunity`. Stock
     `Quotation.update_opportunity_status` already writes a status; repoint it to the new value.
   - `Converted to Quotation` and `Lost` are final; make the doc read-only in a final status
     (reuse the Lead `has_permission` pattern), and exclude them from the default list view.
   - Editing an Opportunity **after** Quotation creation stays allowed (spec rule 5).
2. **Lost reason mandatory.** `order_lost_reason` becomes mandatory when status = `Lost`;
   seed the 10 `Opportunity Lost Reason` records from the spec.
3. **Hide fields.** Property Setters `hidden = 1`: `utm_source` (value is carried from the Lead),
   and the whole `organization_details_section` block (`no_of_employees`, `annual_revenue`,
   `industry`, `market_segment`, and its column breaks).
4. **`sales_stage` → «Етап переговорів»** (Property Setter `label`). Seed two `Sales Stage`
   records: `Requirement Clarification`, `Solution Shaping`. Mandatory for active Opportunities.
5. **«Бюджет клієнта (якщо відомо)» is free text**, not a currency amount (must hold
   `1 000 000 грн`, a range, or "до 2 000 000 грн"). New Custom Field `customer_budget` (Data);
   hide `opportunity_amount` / `base_opportunity_amount` rather than relabel them.
6. **Probability becomes subjective.** Fieldtype of stock `probability` (Percent) cannot be changed
   by a Property Setter — add `probability_level` (Select: `Low / Medium / High`) and hide
   `probability`.
7. **«Особа, що приймає рішення»** — new `decision_maker` (Link → Contact), optional, query
   filtered to contacts of the linked Prospect/Customer (reuse `military_unit_contact_query`
   shape from the Lead).
8. **Next Action block** (new section), mirroring the Lead implementation:
   `next_action_type` (Select: Call / Letter / Meeting / Internal Alignment /
   Awaiting Client Response / Other), `next_action_date` (Date), `next_action_comment` (Small Text),
   `next_action_overdue` (hidden Check).
   - Mandatory for every non-final Opportunity.
   - Overdue enforcement (spec rule 7): on save/refresh, an overdue next action forces one of —
     add a comment, move the date, advance the negotiation stage, or close the Opportunity.
   - Scheduler flag refresh + "due today" Notification: copy
     `Lead.refresh_overdue_flags` and `setup_lead_next_action_notification`.
9. **Key events** — three checkboxes: `demo_conducted`, `sample_sent`, `feedback_received`.
10. **Lead → Opportunity carry-over.** Extend `lead.make_opportunity` mapping with
    `customer_need`, the `requirement` rows (→ a mirrored child table or `Opportunity Item`
    rows where an item is known), `prospect`, `contact_person`, `utm_source`, `military_unit`,
    and copy attachments. Audit what the stock mapper already carries before adding.
11. **List view** (`opportunity_list.js`): columns Customer, Responsible Manager
    (`opportunity_owner`), Status, Negotiation Stage, Next Action, Next Action Date;
    overdue indicator; default filter excluding final statuses.
12. Translations for every new label, option and reason.

---

## 3. Quotation (Угода) — approval workflow does not exist

Present today: `negotiation_status` Custom Field (a different, older status model),
`Quotation Version` snapshots on `on_update`, the negotiation funnel report, stock `status`.

1. **Status model — decide first.** The spec's five statuses
   (`Опрацьовується / Погоджено / В роботі / Виконано / Скасовано`) do not match the
   `negotiation_status` option list. Recommended: drive them with a **Workflow** on
   `workflow_state`, leave stock `status` alone, and retire `negotiation_status` —
   `quotation_version.py:105` and `selling/report/quotation_negotiation_funnel/` both read it and
   must be migrated in the same change.
2. **`fulfilment_type`** (Select: `Finished Goods Sale / New Production / Combined`).
   Editable only in `Опрацьовується`; it selects the approval route.
3. **Approval routes** — one Workflow whose transitions are conditioned on `fulfilment_type`:
   - Finished Goods: Sales Manager → Warehouse → Finance Director → Production Head → Client confirmation
   - New Production: Sales Manager → Production → Finance Director → Production Head → Client confirmation
   - Combined: Sales Manager → Warehouse → Production → Finance Director → Production Head → Client confirmation
   Sequential only, no parallel approval. Needs new roles: Warehouse Approver, Production Approver,
   Finance Director, Production Head, Sales Manager Supervisor (names to be confirmed against
   existing roles before creating duplicates).
4. **Lock on workflow start.** Outside `Опрацьовується` the document is read-only (docstatus stays 0,
   so enforce in `validate` + `set_df_property` client-side): items, qty, rates, discounts, dates,
   `fulfilment_type`, payment and delivery terms.
5. **Return for rework** — mandatory comment; returning resets the route to its first step
   (Workflow does this naturally) and invalidates earlier approvals.
6. **Cancellation at any stage** — `cancel_reason` + `cancel_comment`, both mandatory; document
   read-only afterwards.
7. **Role-based field visibility** (MVP requirement). Warehouse and Production must not see
   prices, discounts, totals, payment terms or financial comments. Implement with
   **permlevel 1** on those fields (Property Setters) plus Custom DocPerm rows granting
   permlevel-1 read only to Sales Manager / Sales Supervisor / Finance Director / Production Head.
   This is the single largest piece of work in the Quotation scope.
8. **Quantity control against Sales Orders.** A `Sales Order` `validate` hook must reject:
   more qty than approved, re-use of already allocated qty, and items absent from the Quotation.
   Cancelling a Sales Order returns its qty to the remaining balance. Stock
   `get_ordered_status` / `is_fully_ordered` / `get_ordered_items` cover part of this — extend,
   do not duplicate (watch for `F811`).
9. **Automatic status transitions**: `В роботі` on the first submitted Sales Order,
   `Виконано` when the whole approved qty is allocated — hook on Sales Order
   `on_submit` / `on_cancel`.
10. **Linked Sales Orders panel** on the Quotation: each SO with its status and ordered qty,
    total ordered, remaining available.
11. **"Close without Sales Order"** action, for the case where the subject of the agreement
    changes and a new Quotation must be raised inside the same Opportunity.
12. Translations for states, actions, `fulfilment_type` and cancellation reasons.

---

## Suggested order of work

| Phase | Scope | Why first |
|---|---|---|
| 1 | Lead gaps (§1.1–1.8) | Small, isolated, finishes an almost-complete doctype |
| 2 | Opportunity fields + statuses (§2.1–2.7, 2.9) | Unblocks the Lead → Opportunity handover |
| 3 | Opportunity next action + list view + mapping (§2.8, 2.10–2.12) | Reuses Lead code verbatim |
| 4 | Quotation status model decision + `fulfilment_type` (§3.1–3.2) | Everything else depends on it |
| 5 | Workflow + lock + rework + cancel (§3.3–3.6) | Core MVP approval flow |
| 6 | Permlevel field visibility (§3.7) | Independent, testable on its own |
| 7 | Sales Order qty control + auto statuses + panel (§3.8–3.10) | Last, needs a stable Quotation |

## Explicitly out of MVP (per `# Угода.md`)

Automatic `fulfilment_type` detection, per-warehouse / per-site approval, parallel approval,
approval SLA, automatic reminders and escalations, a separate approval journal, workflow timing
analytics.

## Cross-cutting, every phase

- Every new string wrapped in `__()` / `_()` with an English→Ukrainian pair in
  `erpnext/translations/uk.csv`.
- Schema changes only via `erpnext/patches/setup_custom_fields.py` (idempotent).
- `pre-commit run --files <changed>` before committing; watch `F811` when appending to
  `quotation.py` / `opportunity.py`.
- Release note appended to `erpnext/release_notes/vYYYY.MM.DD.md` (Ukrainian).
