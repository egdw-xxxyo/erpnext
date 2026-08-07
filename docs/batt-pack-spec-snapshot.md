# BATT-PACK Specification Snapshot (prod, 2026-04-03)

## Template: BATT-PACK

- **item_name**: Батарейний блок
- **item_group**: Батареї
- **has_variants**: 1
- **variant_based_on**: Item Attribute
- **serial_number_template**: СН батарейного блоку
- **serial_no_series**: `UB0.{ATTR:Конфігурація S}.{ATTR:Конфігурація P}.{ATTR:Елемент}.#####`
- **quality_inspection_template**: Вхідний контроль АКБ
- **inspection_required_before_purchase**: 1

### Template Attributes

| idx | Attribute        |
|-----|------------------|
| 1   | Хімія            |
| 2   | Конфігурація S   |
| 3   | Конфігурація P   |
| 4   | Елемент          |

### Template Spec Parameters (formulas)

| idx | Parameter                      | numeric | formula                                              | tolerance% | uom  |
|-----|--------------------------------|---------|------------------------------------------------------|------------|------|
| 1   | Напруга комірки                | 1       | `{Елемент.Напруга комірки}`                          | 0          | В    |
| 2   | Тип елемента                   | 0       | -                                                    | 0          | -    |
| 3   | Струм заряду                   | 1       | `{Елемент.Струм заряду} * {Конфігурація P}`          | 0          | А    |
| 4   | Конфігурація                   | 0       | -                                                    | 0          | -    |
| 5   | Напруга повна                  | 1       | `{Елемент.Напруга повна} * {Конфігурація S}`         | 0          | В    |
| 6   | Візуальний огляд               | 0       | -                                                    | 0          | -    |
| 7   | Переполюсовка                  | 0       | -                                                    | 0          | -    |
| 8   | Напруга номінальна             | 1       | `{Елемент.Напруга комірки} * {Конфігурація S}`       | 5          | В    |
| 9   | Ємність                        | 1       | `{Елемент.Ємність} * {Конфігурація P}`               | 5          | мАг  |
| 10  | Маса                           | 1       | `{Елемент.Маса} * {Конфігурація S} * {Конфігурація P} + 50` | 5    | г    |
| 11  | Тип розʼєму силового           | 0       | -                                                    | 0          | -    |
| 12  | Тип розʼєму балансувального    | 0       | -                                                    | 0          | -    |

---

## Variants (30 total)

### 6S variants — have spec parameters filled in

**Note**: Some variants have `value` field filled with resolved numbers (manually set), others have `formula` + `calculated_value` (auto-calculated). The parameter name for idx=1 differs: older variants have "Напруга повна комірки" (value=4.2), newer ones (SP40, 6S-4P-RS55) have "Напруга комірки" with formula.

| Variant                      | S  | P  | Елемент          | serial_no_series          | specs filled |
|------------------------------|----|----|------------------|---------------------------|--------------|
| BATT-PACK-LI-6S-2P-P42A     | 6S | 2P | Molicel P42A     | UB0.6S.2P.P42A.#####     | 12 params    |
| BATT-PACK-LI-6S-2P-P45B     | 6S | 2P | Molicel P45B     | UB0.6S.2P.P45B.#####     | 12 params    |
| BATT-PACK-LI-6S-2P-P50B     | 6S | 2P | Molicel P50B     | UB0.6S.2P.P50B.#####     | 12 params    |
| BATT-PACK-LI-6S-2P-P60B     | 6S | 2P | Molicel P60B     | UB0.6S.2P.P60B.#####     | 12 params    |
| BATT-PACK-LI-6S-2P-RS55     | 6S | 2P | Reliance RS55    | UB0.6S.2P.RS55.#####     | 12 params    |
| BATT-PACK-LI-6S-2P-SP40     | 6S | 2P | SunPower         | UB0.6S.2P.SP40.#####     | 12 params (formulas, not resolved) |
| BATT-PACK-LI-6S-3P-P42A     | 6S | 3P | Molicel P42A     | UB0.6S.3P.P42A.#####     | 12 params    |
| BATT-PACK-LI-6S-3P-P45B     | 6S | 3P | Molicel P45B     | UB0.6S.3P.P45B.#####     | 12 params    |
| BATT-PACK-LI-6S-3P-P50B     | 6S | 3P | Molicel P50B     | UB0.6S.3P.P50B.#####     | 12 params    |
| BATT-PACK-LI-6S-3P-P60B     | 6S | 3P | Molicel P60B     | UB0.6S.3P.P60B.#####     | 12 params    |
| BATT-PACK-LI-6S-3P-RS55     | 6S | 3P | Reliance RS55    | UB0.6S.3P.RS55.#####     | 12 params    |
| BATT-PACK-LI-6S-4P-P42A     | 6S | 4P | Molicel P42A     | UB0.6S.4P.P42A.#####     | 12 params    |
| BATT-PACK-LI-6S-4P-P45B     | 6S | 4P | Molicel P45B     | UB0.6S.4P.P45B.#####     | 12 params    |
| BATT-PACK-LI-6S-4P-P50B     | 6S | 4P | Molicel P50B     | UB0.6S.4P.P50B.#####     | 12 params (formulas, not resolved) |
| BATT-PACK-LI-6S-4P-P60B     | 6S | 4P | Molicel P60B     | UB0.6S.4P.P60B.#####     | 12 params    |
| BATT-PACK-LI-6S-4P-RS55     | 6S | 4P | Reliance RS55    | UB0.6S.4P.RS55.#####     | 12 params (param1="Напруга комірки" val=3.6) |

### 8S variants — NO spec parameters (empty item_spec_parameters)

| Variant                      | S  | P  | Елемент          | serial_no_series          |
|------------------------------|----|----|------------------|---------------------------|
| BATT-PACK-LI-8S-5P-P42A     | 8S | 5P | Molicel P42A     | UB0.8S.5P.P42A.#####     |
| BATT-PACK-LI-8S-5P-P45B     | 8S | 5P | Molicel P45B     | UB0.8S.5P.P45B.#####     |
| BATT-PACK-LI-8S-5P-P50B     | 8S | 5P | Molicel P50B     | UB0.8S.5P.P50B.#####     |
| BATT-PACK-LI-8S-5P-P60B     | 8S | 5P | Molicel P60B     | UB0.8S.5P.P60B.#####     |
| BATT-PACK-LI-8S-5P-RS55     | 8S | 5P | Reliance RS55    | UB0.8S.5P.RS55.#####     |
| BATT-PACK-LI-8S-6P-P42A     | 8S | 6P | Molicel P42A     | UB0.8S.6P.P42A.#####     |
| BATT-PACK-LI-8S-6P-P45B     | 8S | 6P | Molicel P45B     | UB0.8S.6P.P45B.#####     |
| BATT-PACK-LI-8S-6P-P50B     | 8S | 6P | Molicel P50B     | UB0.8S.6P.P50B.#####     |
| BATT-PACK-LI-8S-6P-P60B     | 8S | 6P | Molicel P60B     | UB0.8S.6P.P60B.#####     |
| BATT-PACK-LI-8S-6P-RS55     | 8S | 6P | Reliance RS55    | UB0.8S.6P.RS55.#####     |
| BATT-PACK-LI-8S-7P-P42A     | 8S | 7P | Molicel P42A     | UB0.8S.7P.P42A.#####     |
| BATT-PACK-LI-8S-7P-P45B     | 8S | 7P | Molicel P45B     | UB0.8S.7P.P45B.#####     |
| BATT-PACK-LI-8S-7P-P50B     | 8S | 7P | Molicel P50B     | UB0.8S.7P.P50B.#####     |
| BATT-PACK-LI-8S-7P-P60B     | 8S | 7P | Molicel P60B     | UB0.8S.7P.P60B.#####     |
| BATT-PACK-LI-8S-7P-RS55     | 8S | 7P | Reliance RS55    | UB0.8S.7P.RS55.#####     |

---

## Resolved Spec Values for 6S Variants

### Resolved values (value field set, no formula — "old-style" variants)

| Variant               | Напруга повна комірки (В) | Тип елемента    | Струм заряду (А) | Конфігурація | Напруга повна (В) | Візуальний огляд | Переполюсовка | Напруга номінальна (В) [tol 5%] | Ємність (мАг) [tol 5%] | Маса (г) [tol 5%] | Розʼєм силовий | Розʼєм балансув. |
|-----------------------|---------------------------|-----------------|-------------------|--------------|--------------------|------------------|---------------|----------------------------------|-------------------------|--------------------|----------------|------------------|
| 6S-2P-P42A            | 4.2                       | Molicel P42A    | 8.4               | 6S2P         | 25.2               |                  |               | 22.2 (21.1–23.3)                | 9000 (8550–9450)        | 875 (831–919)      | XT60           | XH-07Y           |
| 6S-2P-P45B            | 4.2                       | Molicel P45B    | 9.0               | 6S2P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 9000 (8550–9450)        | 866 (823–909)      | XT60           | XH-07Y           |
| 6S-2P-P50B            | 4.2                       | Molicel P50B    | 10.0              | 6S2P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 10000 (9500–10500)      | 890 (846–934)      | XT60           | XH-07Y           |
| 6S-2P-P60B            | 4.2                       | Molicel P60B    | 12.0              | 6S2P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 12000 (11400–12600)     | 914 (868–960)      | XT60           | XH-07Y           |
| 6S-2P-RS55            | 4.2                       | Reliance RS55   | 11.0              | 6S2P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 11000 (10450–11550)     | 890 (846–934)      | XT60           | XH-07Y           |
| 6S-3P-P42A            | 4.2                       | Molicel P42A    | 12.6              | 6S3P         | 25.2               |                  |               | 22.2 (21.1–23.3)                | 13500 (12825–14175)     | 1255 (1192–1318)   | XT60           | XH-07Y           |
| 6S-3P-P45B            | 4.2                       | Molicel P45B    | 13.5              | 6S3P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 13500 (12825–14175)     | 1274 (1210–1338)   | XT60           | XH-07Y           |
| 6S-3P-P50B            | 4.2                       | Molicel P50B    | 15.0              | 6S3P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 15000 (14250–15750)     | 1310 (1244–1376)   | XT60           | XH-07Y           |
| 6S-3P-P60B            | 4.2                       | Molicel P60B    | 18.0              | 6S3P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 18000 (17100–18900)     | 1346 (1279–1413)   | XT60           | XH-07Y           |
| 6S-3P-RS55            | 4.2                       | Reliance RS55   | 16.5              | 6S3P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 16500 (15675–17325)     | 1310 (1244–1376)   | XT60           | XH-07Y           |
| 6S-4P-P42A            | 4.2                       | Molicel P42A    | 16.8              | 6S4P         | 25.2               |                  |               | 22.2 (21.1–23.3)                | 18000 (17100–18900)     | 1730 (1644–1816)   | XT60           | XH-07Y           |
| 6S-4P-P45B            | 4.2                       | Molicel P45B    | 18.0              | 6S4P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 18000 (17100–18900)     | 1682 (1598–1766)   | XT60           | XH-07Y           |
| 6S-4P-P60B            | 4.2                       | Molicel P60B    | 24.0              | 6S4P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 24000 (22800–25200)     | 1778 (1689–1867)   | XT60           | XH-07Y           |
| 6S-4P-RS55            | 3.6 (param="Напруга комірки") | Reliance RS55 | 6.0             | 6S4P         | 25.2               |                  |               | 21.6 (20.5–22.7)                | 22000 (20900–23100)     | 1730 (1644–1816)   | XT60           | XH-07Y           |

### Formula-based variants (value=null, calculated_value set)

| Variant               | Напруга комірки (calc) | Тип елемента | Струм заряду (calc) | Конфігурація | Напруга повна (calc) | Напруга номін. (calc) [tol 5%] | Ємність (calc) [tol 5%] | Маса (calc) [tol 5%] | Розʼєм силовий | Розʼєм балансув. |
|-----------------------|------------------------|--------------|---------------------|--------------|----------------------|--------------------------------|-------------------------|-----------------------|----------------|------------------|
| 6S-2P-SP40            | 3.6                    | SunPower     | 6                   | 6S2P         | 25.2                 | 21.6 (20.52–22.68)            | 8000 (7600–8400)        | 866 (822.7–909.3)     | (null)         | (null)           |
| 6S-4P-P50B            | (uses formula)         | Molicel P50B | 20                  | 6S4P         | 25.2                 | 21.6 (20.52–22.68)            | 20000 (19000–21000)     | 1730 (1643.5–1816.5)  | (null)         | (null)           |

---

## Key Observations

1. **All 8S variants (15 items) have NO spec parameters** — they need to be populated
2. **P42A variants have Напруга номінальна = 22.2В** (cell voltage 3.7V), all others = 21.6В (cell voltage 3.6V)
3. **SP40 and 6S-4P-P50B** still have formulas (not resolved to values), unlike other 6S variants
4. **6S-4P-RS55** has different param1 name ("Напруга комірки" instead of "Напруга повна комірки") and value=3.6
5. **Розʼєм values are null** on SP40 and 6S-4P-P50B variants
6. **All variants share**: quality_inspection_template="Вхідний контроль АКБ", serial_number_template="СН батарейного блоку"

## Cell Data (derived from spec values)

| Елемент          | Напруга комірки (В) | Напруга повна (В) | Ємність (мАг) | Струм заряду на 1P (А) | Маса 1 cell (г) |
|------------------|---------------------|--------------------|---------------|-------------------------|-----------------|
| Molicel P42A     | 3.7                 | 4.2                | 4500          | 4.2                     | ~68.75          |
| Molicel P45B     | 3.6                 | 4.2                | 4500          | 4.5                     | ~68             |
| Molicel P50B     | 3.6                 | 4.2                | 5000          | 5.0                     | ~70             |
| Molicel P60B     | 3.6                 | 4.2                | 6000          | 6.0                     | ~72             |
| Reliance RS55    | 3.6                 | 4.2                | 5500          | 5.5                     | ~70             |
| SunPower         | 3.6                 | 4.2                | 4000          | 3.0                     | ~68             |
