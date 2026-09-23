# ЄСКД Workbook Import — Findings, Mismatches & Plan

> **2026-09-23:** the code this doc refers to was reverted in `aef32f4703`. What was reverted and how to redo it: [eskd-specifications-in-technical-documentation.md](eskd-specifications-in-technical-documentation.md).
>
> Source: `ЄСКД.xlsx` (281 KB, 12 sheets). Imported to prod `172.16.51.10` on 2026-09-21,
> reviewed, then **fully reverted** the same day. This document records what the workbook
> actually contains, what the import produced, and every mismatch found, so the re-import
> starts from knowledge instead of from the spreadsheet again.

## Status

| | |
|---|---|
| Workbook parsed and understood | done |
| Import run on prod | done, then reverted (0 designations, 0 documents remain) |
| Item ↔ designation linking | written and proven on real data, reverted with the rest |
| Kits (drone + battery + spool) | 18 built and inspected, reverted |
| Code changes | merged, pushed: `317adedbf7`, `1c718280ee`, `92973a6ef1` |
| Re-import | blocked on the workbook fixes in [§4](#4-workbook-defects) |

Only `ТУ-2026-00001` survives on prod — hand-created by `k.plodovskyi@kalheon.com`, not ours.

## 1. What the workbook holds

| Sheet | Rows | Content | In scope |
|---|---|---|---|
| `Сводная` | 123 | Document register, 11 product columns × drawings / parts / manuals | **no** |
| `Аркуш1` | 1 | empty | — |
| `Сводная таблиця ТУ` | 12 | 10 ТУ numbers per product | partly |
| `Сперцифікація на FPV` | 221 | Board designation grammar + 3 blocks + 2 «ПЕРЕЛІК» tables | **yes** |
| `Специфікація на котушку` | 78 | 60 coil slots, 13 filled | **yes** |
| `Специфікація на батарею` | 63 | 2 side-by-side blocks (УКРП / ВРНК) × 60 slots | **yes** |
| `Специфікація НСУ FO` | 64 | 60 ground-station slots, 5 filled | **yes** |
| `Відомість модифікацій ТУ14` | 148 | БпАК modification matrix, board × ground station | **yes** |
| `!OLD_Відомість модифікацій БпАК` | 244 | superseded | no |
| `Лист1` | 148 | duplicate of the ВМ sheet | no |
| `Технологічні карти` | 313 | 300 process cards | **no** |
| `ВАРНЕКС` | 51 | ВРНК-branded coil and ground-station lists | **yes** |

### Code grammar, as documented on the FPV sheet

```
УКРП.XXXXXX.YYQQWWEEС
  XXXXXX  ЄСКД classifier
  YY      frame size — 7 / 8 / 10 / 13 / 15 / 23 (+ 99 "other frame")
  QQ      camera — 01 day analogue, 02 thermal analogue, 03 day+thermal analogue,
                   04 day digital, 05 thermal digital, 06 day+thermal digital
  WW      ordinal of the coil specification
  EE      ordinal of the battery specification
  С       specification
```

Coil naming: `Укропчик FO <length> <fibre>`, where fibre is `AF` = 125 µm / 0,25 mm,
`AT` = 125 / 0,2, `GF` = 150 / 0,25, `GT` = 150 / 0,2.

### Code grammar, as the codes are actually written

The legend allows **8 digits** (`YYQQWWEE`). Every real board code carries **10**, and the
order of the last two pairs is reversed from the legend:

```
УКРП.200121.15 01 21 00 13 C   →  YY=15  QQ=01  battery=21 (8S4P)  "00"  coil=13 (15 км AF)
УКРП.200121.10 01 12 00 11 С   →  YY=10  QQ=01  battery=12 (6S3P)  "00"  coil=11 (5 км AF)
```

So the effective grammar is `YY QQ EE 00 WW` — **battery before coil, with a literal `00`
pair between them**. Verified across the 10 FO and 15 FO blocks; it holds everywhere. Either
the legend or the codes are wrong, and this needs a ruling before anyone generates a new code
from the legend.

## 2. The ERPNext model it lands in

- **Technical Document** — the catalog itself (`УКРП.200121.002-ХХС` «Специфікація на котушку»),
  with revisions, status, files and an audit log.
- **Product Modification** — one per designation (`УКРП.200121.002-13C`), carrying
  `modification_code`, `full_name`, `purpose` (the catalog's own column text), typed attributes,
  and **components** (a board names its coil and battery; a БпАК row names its board and НСУ).
- **Item.specification** → Product Modification, `Item.specification_code` → its display code.
- **Kit** — `create_kit()` makes a non-stock Item `КОМПЛЕКТ <шифр>` plus a Product Bundle of
  the component Items. One order line, warehouse ships the parts.

Entry points: `erpnext.manufacturing.eskd_import.run(path, dry_run=True)` and
`erpnext.technical_documentation.item_link.run(dry_run=True)`.

## 3. What the import produced (before revert)

```
157 designations created, 67 updated   →  106 board, 23 coil, 18 battery, 10 ground station
 87 БпАК modification rows             →  all with both Борт and НСУ components
510 register documents                 →  300 process cards, 96 parts, 35 assembly drawings,
                                          13 ТУ, 11 passports, 11 manuals, 4 wiring diagrams,
                                          40 specifications, 1 modification list
 24 specifications skipped             →  placeholder codes (`??`, `ХХ`)
  8 documents skipped                  →  placeholder codes
 57 ВМ rows skipped                    →  no ground station marked, see §4.10
```

### Item linking result

| Template | Linked | Basis | Left |
|---|---|---|---|
| `OPT-SPOOL` | 10 / 10 | winding length + fibre code, exact | — |
| `OPT-GS` | 5 / 5 | configuration, after folding three spellings | — |
| `BATT-PACK` | 38 / 42 | brand → organisation + S/P layout | 4, see §5.1 |
| `BPLA-UKR` | 0 / 17 | — | by design, see §5.3 |

18 kits built for the Укропчик 15 FO analogue family (DA / TA / DTA, 20–40 km), each
airframe + exact spool + exact battery. 6 more were blocked on a missing battery Item.

## 4. Workbook defects

These are in the spreadsheet, not the import. Fix at source, then re-import.

1. **Camera code `00` does not exist.** `УКРП.200121.1500210013C` is named «Укропчик 15 FO 15
   TAAF» — thermal analogue — so `QQ` should be `02`. Every other thermal row uses `1502…`.
2. **Four rows carry day-analogue names inside the thermal-digital block.**
   `1505220032C`, `1505220033C`, `1505230041C`, `1505240042C` are named `DAGF` / `DAGT` but sit
   in the *термальна цифрова* section and the «Тип сигналу» column says `цифровий`. The import
   followed the name. One of the two is wrong.
3. **`1004130013С` is named «Укропчик 10 FO 15 DDAAF»** — one `A` too many; siblings are `DDAF`.
4. **`УКРП.463145.106C/15`, `/20`, `/25` have no coil and no battery.** Their parts exist only
   in the sheet's «Для нового ТУ» column as `1501220031С` / `32C` / `33C`, which were never
   issued as designations. Consequence: the day-analogue 150 mm family (15A / 20A / 25A) has no
   complete code, and no kit can be built for it.
5. **`УКРП.464135.150122С` / `150222С` / `150422С` / `150722С`** (Укропчик 15 Д / Т / Ц / С,
   the radio boards) have no components at all.
6. **Both Штурм boards** (`0701100102С`, `0701100202С`) name a battery but no coil.
7. **Three ТУ numbers are issued twice**, to different products, in two different sheets:

   | ТУ | `Сводная` says | `Сводная таблиця ТУ` says |
   |---|---|---|
   | `ТУ У 30.3-40265219-010:2024` | Укропчик 10 | Укропчик 10 FO |
   | `ТУ У 30.3-40265219-011:2024` | Укропчик 13 | Укропчик 13 FO |
   | `ТУ У 30.3-40265219-014:2025` | *(blank)* | Укропчик 15 FO |

8. **`УКРП.200121.002 ІК`, ` ПС` and `СК` are repeated across five product columns** in
   `Сводная` — НСК FO, НСУ FO Ц, both coil types, and one blank column. A *coil* specification
   number is being used as the ground station's manual, passport and assembly-drawing number.
   Produced 5 documents per code, one of them with no product at all.
9. **Truncated code** `УКРП.200121.00С` in the НСУ column of `Сводная`.
10. **57 of 144 ВМ rows have no shaded ground-station cell**, so the modification cannot be
    paired with an НСУ and was skipped. That is 40 % of the modification list.
11. **The НСУ sheet header says `УКРП.200121.003-ХХС`, every row says `УКРП.563562.003-ХХС`.**
    Header and body disagree on the classifier.
12. **Three spellings of one configuration** on the НСУ sheet: «компактная» (Russian),
    «компактра» (typo), «компактна». The importer folds them; the sheet should not need it.
13. **`ВРНК.563562.001-40С`** is «батарея додаткова для DJI Matrice 4T з адаптером» — not a
    cell layout, sitting in a layout table. `УКРП` has no counterpart at slot 40.
14. **`УКРП.563562.001-10С` has no «Призначення» in the sheet** but imported as `6S1P`. Verify
    `import_batteries` — it may be filling a value the sheet does not state.
15. **Battery layouts absent from the ВРНК block** although the packs are manufactured:
    `6S10P`, `6S14P`, `8S3P`. See §5.1.

## 5. Item ↔ designation mismatches

### 5.1 Manufactured, but no designation exists — the only real gap

| Item | Layout |
|---|---|
| `BATT-PACK-M-LI-6S-10P-RS55` | 6S10P |
| `BATT-PACK-M-LI-6S-14P-RS55` | 6S14P |
| `BATT-PACK-M-LI-6S-14P-S50S` | 6S14P |
| `BATT-PACK-M-LI-8S-3P-RS55` | 8S3P |

Магура packs in production with no ЄСКД code. Everything else is the catalog running *ahead*
of production, which is normal; this is the one case where production is ahead of the catalog.

### 5.2 Designation exists, no Item yet — expected, no action

`УКРП` 8S4P / 6S1P / 6S5P · `ВРНК` 6S5P / 8S6P / 8S7P / `-40С` · 10 VARNEX coils
(`ВРНК.200121.002-11…42C`) · 5 VARNEX ground stations (`ВРНК.563562.003-01…41С`) · 22
digital-camera boards. Their kits appear when the Item does.

`УКРП.563562.001-21С` (8S4P) is the one that bites: six 15 FO **15 km** boards need it, so
those kits stay unbuildable until the Item exists. The only 8S4P Item on the site is
`BATT-PACK-M-LI-8S-4P-RS55`, which is **Магура → ВРНК**, a different organisation's code.

### 5.3 Boards cannot be linked 1:1, by design

A board designation encodes its coil length and battery layout — `УКРП.200121.1501220022C` is
«Укропчик 15 FO **25** DAAT». The `BPLA-UKR` Item attributes are only Торгова марка / Номер ТУ /
Тип камери / Призначення, so 17 Items would have to answer for 106 designations. Linking any
one of them writes a length and a battery the drone was not built to.

**Decision taken:** the Item stays generic; the **kit** carries the designation. `КОМПЛЕКТ
УКРП.200121.1503220033C` holds airframe + `Укропчик FO 25 GF` + `BATT-PACK-U-LI-8S-5P-RS55`,
and the length and battery are read off the bundle lines.

Alternative, if ever wanted: add `Довжина котушки` and `Конфігурація батареї` Item Attributes to
`BPLA-UKR` and generate ~106 variants. Exact, but the Item list grows by an order of magnitude.

### 5.4 Smaller ones

- **No digital-camera `BPLA-UKR` variants exist at all**, so the whole `1504` / `1505` / `1506`
  line (22 designations) finds no airframe, and the БпАК rows referencing them cannot be kitted.
- Item Attribute Value `« Samsung 21700 50S»` has a **leading space**.
- `OPT-GS` Item names use «компактна»; the designations use «компактная» / «компактра» (§4.12).

## 6. A designation is a code, not a part number

The finding that changed the model. Every 6S3P pack answers to `УКРП.563562.001-12С` whatever
cell it is built from — six Items (`P42A`, `P45B`, `P50B`, `P60B`, `RS55`, `SP40`) share one
designation, legitimately. `create_kit` used to throw «made as several Items — link only one».

Now: **`Product Modification.default_kit_item`** says which Item ships for a designation, and
**`Specification Component.item`** overrides it for one kit. Resolution order is row override →
designation default → the single linked Item, and «Kit Ambiguous» is thrown only when none of
the three answers. The board's own bundle line comes from the same resolution, which is what
lets a board with no Item of its own still produce a complete kit.

`RS55` was chosen as the default cell because it is the only one present across every layout in
both the Укропчик and Магура lines. Changing a designation's card changes the kit.

## 7. Code changes, merged

| Commit | Change |
|---|---|
| `317adedbf7` | `item_link.py` — link coils, ground stations and batteries; `default_kit_item` + per-row `item`; kit resolution; БпАК rows get `product_type`; `Item._inherit_specification_from_template` reads `display_code` off Product Modification, not Technical Document |
| `1c718280ee` | kit `stock_uom` comes from Stock Settings — the `"Nos"` lookup missed on a Ukrainian UOM table and the fallback `get_value("UOM", {}, "name")` handed every kit «Рулон» |
| `92973a6ef1` | `DEFAULT_SHEETS` — a plain `run()` takes the catalogs only; `register` / `tu` / `process_cards` are opt-in via `only=[…]`, so the 457 register documents cannot return by accident |

## 8. Operational notes

- **`openpyxl` is not in the backend image.** `pip install openpyxl` inside `docker-backend-1`
  before importing; it does not survive a rebuild. Worth adding to the image if the import
  becomes routine.
- **Getting the workbook in:** `scp` to the host, then `docker cp … docker-backend-1:/tmp/`.
- **`bench console < script.py` mangles scripts** that contain a blank line inside a `def` —
  IPython's autoindent swallows the body and you get `NameError` on names defined at the top.
  Use `bench execute <module>.<fn>` on an installed module, or `bench mariadb < query.sql`.
- **`bench execute` masks in-function exceptions.** A `MySQLdb.OperationalError` inside the
  called function surfaced as `NameError: name 'erpnext' is not defined`. Read the *head* of the
  output, not the tail.
- **`Technical Document Audit Entry` links via `document`**, not `technical_document`.
- The purge script guarded on `Stock Ledger Entry` before deleting kit Items. Keep that guard in
  anything that deletes Items on prod.

## 9. Next steps

1. **Take the §4 defects to whoever owns the workbook.** Blocking items are the `QQ=00` code
   (§4.1), the four mis-named `1505` rows (§4.2), the 57 unshaded ВМ rows (§4.10) and the
   `106C/xx` missing components (§4.4).
2. **Rule on the code grammar** — 8 digits as documented, or 10 as written, and which order
   (§1). Anything generating a new designation depends on this.
3. **Issue designations for the four Магура layouts** in §5.1, or confirm they are not products.
4. **Re-import** with `eskd_import.run(path, dry_run=False)` — catalogs only now — then
   `item_link.run(dry_run=False)` and `item_link.set_default_kit_items(dry_run=False)`.
5. **Add `item_link.build_kits()`** — walk every board, build the kits whose parts resolve, skip
   the rest silently. Makes kit creation an idempotent command to re-run as Items appear,
   instead of a hand-listed set of codes.
6. **Decide on the register sheets.** 457 documents of drawings, parts and process cards are
   available behind `only=["register", "tu", "process_cards"]` and currently unused. They are
   worth importing only once someone will attach files and revisions to them — see §10.
7. **Create the `BATT-PACK` 8S-4P Укропчик variant** if that pack is made, to unblock the six
   15 km kits.

## 10. Known consequence of importing the register

Nothing populates revisions. All 510 documents imported with zero
`Technical Document Revision` rows, no responsible person and no attached files, so the
Technical Documentation Completeness report read "everything missing" for every one of them.
That is data entry, not import work, and it is the reason the register is now opt-in.
