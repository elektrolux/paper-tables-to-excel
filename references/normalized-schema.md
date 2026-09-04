# Normalized table schema

Create one UTF-8 JSON file before workbook export.

```json
{
  "schema_version": "1.0",
  "tables": [
    {
      "table_id": "Table 3",
      "title": "Effects of exposure on outcome",
      "source_role": "main",
      "source_file": "paper.pdf",
      "source_sha256": "UPPERCASE_SHA256",
      "source_locator": "PDF page 4",
      "candidate_id": "main_p004_t01",
      "columns": [
        {"name": "Pollutant", "type": "text"},
        {"name": "Estimate", "type": "number", "precision": 3},
        {"name": "Confidence interval lower", "type": "number", "precision": 3},
        {"name": "Confidence interval upper", "type": "number", "precision": 3}
      ],
      "rows": [
        ["PM2.5", -4.937, -9.828, -0.046]
      ],
      "warnings": []
    }
  ],
  "excluded_candidates": [
    {
      "candidate_id": "main_p001_t01",
      "reason": "not_data_table"
    }
  ]
}
```

## Required table fields

- `table_id`: source label such as `Table 2` or `Table S3`. Add a panel suffix only when incompatible panel schemas require separate workbooks.
- `title`: source caption without footnotes. It is used for filenames and the external manifest, not written into the worksheet.
- `source_role`: `main` or `attachment`.
- `source_file`, `source_sha256`, `source_locator`, and `candidate_id`: provenance kept outside the workbook.
- `columns`: unique one-row column definitions.
- `rows`: rectangular arrays matching the column count.
- `warnings`: source or extraction uncertainties. Never hide uncertainty in a data cell.

## Column types

- `text`: identifiers and categories only.
- `integer`: counts and other whole numbers.
- `number`: continuous values and statistical results.
- `percent`: percentage points with the percent sign removed. Source `24.4%` becomes numeric `24.4`, not `0.244`.
- `year`: four-digit numeric year.
- `boolean`: true or false only.

Use `precision` from 0 through 10 for numeric display. Preserve the source precision when known. Number formatting must not add a percent sign, currency symbol, thousands separator, brackets, or units.

## Required structural transformations

### Compound statistics

- `3384 (407.05)` under Mean and SD becomes `Mean = 3384`, `Standard deviation = 407.05`.
- `3448.39 ± 432.42` becomes separate mean and standard-deviation columns.
- `10915 (27)` becomes separate sample-size and missing-count columns.
- `4.94 (-9.828, -0.046)` becomes estimate, confidence-interval lower, and confidence-interval upper columns.
- Multiple stacked values in one source cell become separate records after aligning them with their row labels.

### Numeric categories

Do not retain multiple numeric bounds in one text cell. Use separate fields:

| Source label | Relation | Lower bound | Upper bound |
|---|---|---:|---:|
| `<20` | Below | null | 20 |
| `20–34` | Range | 20 | 34 |
| `≥35` | At least | 35 | null |

For inclusivity that affects interpretation, add boolean columns such as `Lower bound inclusive` and `Upper bound inclusive`.

### Symbols and missing values

- Convert symbolic relations to words.
- Put units in headers using words where necessary.
- Remove significance stars rather than storing them separately.
- Use JSON `null` for blank or unreported cells. Use numeric zero only when the source explicitly reports zero.
- Preserve negative numbers as numeric values.

## Workbook boundary

Only `columns[].name` and `rows` enter the workbook. All other fields stay in `conversion_manifest.json`, which remains outside the ZIP.
