# Packing after stock: variable consumables via a reusable Consumption Recipe

Status: draft for discussion. Nothing here is implemented.

## Why

Today a line with `manufacture_at_packing = 1` keeps a unit out of stock until the packing
station closes the "Упаковка" card, because `Stock Entry.check_if_operations_completed`
refuses a Manufacture entry while any operation of the Work Order is open. Consequences:

* a finished spool has no warehouse until it is boxed (ghost stock, no counts, nothing to reserve);
* packaging consumables are BOM rows of the spool with `operation = Упаковка`, so they are
  per unit and cannot express "4 per box, the last box has 3";
* the mode is a flag on the whole line, read when the unit finishes, so switching it at noon
  changes the fate of units already on the bench.

Decisions taken in discussion:

* Goods are sold as the spool SKU only; packaging cost is already inside the price. So no
  separate "boxed" SKU and no Repack (same item as input and output in one entry is an unproven
  serial-bundle case).
* Units go into stock right after the bench. Packing is a separate later step, driven by the order.
* The customer decides how many units go into a box and how it is packed, per order line.
* Consumables are described by a reusable doctype with formulas, so the same engine can serve
  packing now and manufacturing operations later.

## Data model

### `Consumption Recipe` (new, ours — no upstream conflict)

| field | notes |
|---|---|
| `recipe_name`, `is_active`, `description` | |
| `items` (table `Consumption Recipe Item`) | |

`Consumption Recipe Item`: `item_code`, `uom`, `source_warehouse` (optional, else the caller's),
`qty_formula` (default `1`), `condition` (optional, e.g. `units >= 3`), `notes`.

Formulas are evaluated with `frappe.safe_eval` over a context the caller supplies. Packing
supplies `units` (serials actually in the box); an operation would supply `qty`. Helpers
`ceil`, `floor`, `round`, `min`, `max` are exposed. Rounding to the item's UOM precision is
done by the engine, not by the author of the formula.

Form calculator: a list of test values (`1, 2, 3, 4, 6`) and a button that calls a whitelisted
`preview(recipe, values)` and renders item x value. Formula mistakes show up before any stock moves.

### Where the recipe is chosen (first hit wins)

1. `Sales Order Item.packing_template` / `units_per_box` (Custom Field, set from 2 and editable)
2. customer + item default (Custom Fields on `Item Customer Detail`)
3. `Item.default_packing_template`

`Packing Template` gets `consumption_recipe` (Link). The template keeps what it already owns
(box, label, printer, `expected_qty`); the recipe owns the consumables.

All new fields on stock doctypes go through `erpnext/patches/setup_custom_fields.py`.

## Engine

`erpnext/manufacturing/consumption.py` (our module):

```
consume(recipe, variables, source_doctype, source_name, warehouse=None, posting_date=None)
```

* computes quantities (`preview` uses the same function);
* posts one Material Issue, one row per recipe item, expense account taken from the recipe row or a default;
* stamps the entry with its source (`source_doctype`, `source_name`) so a second call for the
  same source is a no-op, and cancelling the source cancels the entry;
* refuses nothing silently: shortage policy is a Stock Settings style switch (block, or allow
  negative with a warning) — the packer must not be stopped by a stock error mid-shift.

Packing close, in one transaction:

1. Material Transfer of the N scanned serials, staging warehouse to finished goods;
2. `consume(recipe, {"units": N}, ...)`.

Same SKU, same serials, so serial history is untouched. Packaging cost leaves stock as an
expense instead of being capitalised into the spool. If margin reports must stay as before,
`Stock Entry.additional_costs` on the transfer can carry the consumed value onto the
incoming rows — read from code, not tested, so out of the first iteration.

## Change to the existing flow

* `finish_unit` (production_line.py) stops deferring Manufacture: the unit always lands in
  stock at the bench. Where the unit lands (`fg_warehouse` vs a new staging warehouse on the
  line) is the only per-line choice left.
* The "Упаковка" card must not block Manufacture. Precedent: the rejected-unit path already
  closes remaining cards with a zero-length log (`_close_remaining_cards`). Packing is then no
  longer a Job Card operation of the spool's Work Order.
* `manufacture_at_packing`, `finish_packed_unit(s)` and the `waiting_packing` state stay for
  units already in flight; remove them once a day passes with none.
* Mode is stamped on the unit when `next_unit` hands it out, never re-read from the plan
  afterwards. State comes from the serial's warehouse: staging = needs packing, finished
  goods = done. The scanner shows one line for a scanned serial ("PACK: box of 4" / "ALREADY
  PACKED").

## Box plan for an order line

`ceil(order_qty / units_per_box)` boxes; all but the last hold `units_per_box`, the last holds
the remainder (123 by 4 = 30 x 4 + 1 x 3). The scanner shows "box 31 of 31: 3 pcs". The
consumables for a box come from the N actually scanned, not from the plan.

## Open points to settle before coding

1. `Package` is wired to purchase receipts, BpAK, pallets and QC auto-pass; it does not move
   stock and does not consume anything. Whether spool boxes are `Package` records or only the
   scanner scripts' own bookkeeping decides where the close action lives. Needs a read of
   the "Пакування FO — Котушки" / "Упаковка FO" scripts (Workplace Script, live in the DB;
   prod listing returned 417 and dev timed out when this was written).
2. What `Packing Template.items` holds today (contents vs consumables).
3. Staging warehouse: a separate "Комплектування" or the finished-goods warehouse itself with
   packing as a status. Separate warehouse is the more honest stock picture.
4. Shortage policy for consumables.
5. Test on dev or local only; unreleased code must not run on prod.

## Order of work

1. `Consumption Recipe` + calculator, no stock movement. Safe to ship alone.
2. Engine `consume()` with idempotency and cancel handling, unit-tested.
3. Order-line fields and recipe resolution.
4. Packing close action (transfer + consume) behind the scanner script.
5. `finish_unit` change and migration of units in flight.
6. Optional: call the same engine from Job Card submit for manufacturing operations.
