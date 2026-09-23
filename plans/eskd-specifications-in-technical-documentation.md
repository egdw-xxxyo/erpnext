# ЄСКД specifications in Technical Documentation — reverted, to redo

> Built 2026-09-19 … 22, **reverted 2026-09-23 in `aef32f4703`**. The code is back to the flat
> `Specification` doctype (state of `d27fa6b028`, 18 Sep); Technical Documentation is back to
> PR #24 (`f27d9d4089`). Nothing was lost — every change lives in the commits below.
> Workbook findings and mismatches from the prod import: [eskd-workbook-import.md](eskd-workbook-import.md).

## What was reverted

| commit | what it did |
|---|---|
| `81969cfd2e` | Imported the rest of `ЄСКД.xlsx`: register sheets (Сводная, Сводна таблиця ТУ, Технологічні карти) as Technical Documents in a new section «Конструкторська документація» with ЄСКД types (Специфікація, Складальний кресленик, Схема електрична, Технологічна карта, Деталь, Інструкція користувача). Radio boards, Укропчик Штурм, «Для нового ТУ», previous codes / old names as parameters. «New Modification» button on the modification list page. |
| `aca29272fc` | **Specification doctype removed.** A catalog designation became a Technical Document of type «Специфікація»; type flag `has_specification_data` shows a Specification section (kind, organization, ordinal, «Призначення», number template, display code, parameters, components). A modification list became a «Відомість модифікацій» document, each row a Product Modification (Борт / НСУ). Item.specification → Technical Document. Patch `retire_specification` replaced `flatten_specification` (drops Specification, variant doctypes, ESKD register; clears Item links). |
| `9a3718768f` | A catalog = one «Специфікація» document named by its prefix (УКРП.563562.003-ХХС); **every designation = a Product Modification** (number, name, intended use, components, attributes). Catalog parameters → Product Attributes on Котушка / БпЛА / Батарея. Item.specification → Product Modification; display code + Number Template override on the modification. Specification Component links Product Modification. Fix: Product Attribute empty numeric range; `apply_override` reads template uncached. |
| `0bd9fd6a8d` | Item form: picker puts matching designations first (★), «Suggest Specification» button with matched words (`technical_documentation/item_match.py`, `public/js/custom/item_specification.js`). Product Modification «Create Kit»: non-stock «КОМПЛЕКТ <code>» Item + Product Bundle of component Items (`technical_documentation/kit.py`); «Items» button. |
| `99a48d685d` | Picker shows the ЄСКД code first (`title_field = modification_code`, `show_title_field_in_link`). Item field «Тип специфікації» (`specification_product_type`, Link → Product Type) filters the picker; `_sync_custom_field_properties` carries `insert_after`. |
| `317adedbf7` | `technical_documentation/item_link.run`: links coils (winding length + fibre), ground stations (configuration), batteries (brand Укропчик → УКРП, Магура → ВРНК, S/P layout). Boards deliberately not linked. Product Modification `default_kit_item`, Specification Component row `item` override; kit resolves row → default → single linked Item, else «Kit Ambiguous». |
| `1c718280ee` | Kit Item UOM from Stock Settings default (was «Nos» → random «Рулон»). |
| `92973a6ef1` | `eskd_import.run()` defaults to catalogs only; register sheets via `only=["register", "tu", "process_cards"]`. |
| `b5503fdba1` | Findings doc — restored as [eskd-workbook-import.md](eskd-workbook-import.md). |

Released before the revert: `81969cfd2e`, `aca29272fc` and the 19 Sep notes shipped in tag
`v2026.09.21` (release notes `v2026.09.18.md` / `v2026.09.19.md` were kept as history).

## How to redo

1. `git revert aef32f4703` — brings every change above back in one step. Resolve conflicts in
   `erpnext/translations/uk.csv` (keep both sides), `setup_custom_fields.py`, `hooks.py`.
2. In that commit, undo the two revert-only tweaks:
   - `setup_custom_fields.py`: drop `specification_product_type` from the old-field removal list;
     props tuple back to `("options", "link_filters", "fetch_from", "insert_after")`.
   - `release_notes/v2026.09.22.md`: remove the «знову окремим довідником» line; write a new note
     for the release that brings it back (the 21 Sep lines about default kit Item, kit UOM,
     catalog-only import and `item_link` come back with the revert).
3. Before deploying, decide on the open points below, then fix the workbook ([§4 of the findings](eskd-workbook-import.md#4-workbook-defects)).
4. Deploy, `eskd_import.run()` dry run first, then real; `item_link.run()`; relink Item.specification.

## Open points before redoing

- **Data on the target site.** `retire_specification` drops `tabSpecification`, so any
  Specification data there is lost; the catalog must be re-imported. After the 23 Sep revert, sites
  that had the new code may hold Items whose `specification` names a Product Modification that no
  longer matches the Link target — clear or relink them first.
- **Register import.** 457 register documents nothing links to — keep it an explicit opt-in.
- **Boards.** No БпЛА Item attribute carries coil length / battery, so boards can't be auto-linked.
- **Why reverted.** Record the reason here before redoing, so the same problem is not rebuilt.
