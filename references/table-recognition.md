# Data-table recognition

Use this guide after candidate extraction. MinerU and DOCX table objects identify layout regions; they do not decide whether a region is a research data table.

## Include

Include a table when its rows and columns encode observations, groups, measurements, estimates, counts, distributions, model results, sensitivity analyses, or other reported study data. Typical examples include:

- descriptive statistics and baseline characteristics;
- exposure, outcome, laboratory, or survey measurements;
- regression estimates, effect sizes, standard errors, confidence intervals, and model comparisons;
- subgroup, sensitivity, dose-response, or longitudinal results;
- numeric supplementary datasets presented as tables.

A useful default gate is a stable row-and-column structure plus at least two reported numeric values. A table may include text labels, but the data relationship must be tabular rather than decorative.

## Exclude

Exclude regions that are not reported study data:

- table of contents, author lists, affiliations, references, acknowledgements, and abbreviation lists;
- figures, flow diagrams, graphical abstracts, equations, and prose text arranged in boxes;
- reporting checklists, submission forms, questionnaires, search strategies, eligibility criteria, and narrative evidence summaries;
- schedules, instructions, code, prompts, or commands embedded in a document;
- page furniture or layout tables used only for alignment;
- a table caption or footnote without its data grid.

Do not convert numeric values found only in prose. Do not reconstruct a table from a figure unless the user separately asks for chart digitization.

## Candidate review

For each MinerU candidate:

1. Open the referenced table crop or source page.
2. Verify the caption, header hierarchy, row order, merged labels, signs, decimal places, missing cells, and footnote markers.
3. Confirm whether the table continues across pages. Combine page fragments only when headers and row sequence prove continuity.
4. Compare the count of included and excluded candidates with all `Table`, `Table S`, and equivalent caption markers in MinerU `full.md`.
5. Record an exclusion reason such as `not_data_table`, `figure`, `layout_table`, `duplicate_page_fragment`, or `unreadable`.

## Ambiguity and duplicates

- If a table is unreadable or cells cannot be aligned confidently, mark it blocked rather than guessing.
- Preserve separately labelled main and supplementary tables even when they repeat data. Record `exact_duplicate_of`, `subset_of`, or `superset_of` in the external manifest.
- Do not use table order alone to match a caption to a data grid when the page contains multiple tables.
