#!/usr/bin/env node
/** Export validated normalized tables to one pure-data XLSX per table. */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";


function parseArgs(argv) {
  const positional = [];
  let force = false;
  for (const value of argv) {
    if (value === "--force") force = true;
    else positional.push(value);
  }
  if (positional.length !== 2) {
    throw new Error("Usage: export_pure_data.mjs normalized_tables.json output_directory [--force]");
  }
  return { normalizedPath: path.resolve(positional[0]), outputDir: path.resolve(positional[1]), force };
}


function columnLetter(number) {
  let value = number;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}


function safeSegment(value, fallback) {
  const normalized = String(value ?? "").normalize("NFKC")
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, " ")
    .replace(/[. ]+$/g, "")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .slice(0, 72);
  return normalized || fallback;
}


function numberFormat(column) {
  if (["integer", "year"].includes(column.type)) return "0";
  if (["number", "percent"].includes(column.type)) {
    const precision = Number.isInteger(column.precision) ? column.precision : 3;
    return precision > 0 ? `0.${"0".repeat(precision)}` : "0";
  }
  return "@";
}


function displayLength(value, precision) {
  if (value == null) return 0;
  if (typeof value === "number" && Number.isInteger(precision)) return value.toFixed(precision).length;
  return String(value).length;
}


function widthFor(column, columnIndex, rows) {
  const maximum = Math.max(
    String(column.name).length,
    ...rows.map((row) => displayLength(row[columnIndex], column.precision)),
  );
  return Math.max(10, Math.min(36, maximum + 2));
}


function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex").toUpperCase();
}


function assertPayload(payload) {
  if (!payload || !Array.isArray(payload.tables) || payload.tables.length === 0) {
    throw new Error("Normalized input must contain at least one table.");
  }
  for (const [tableIndex, table] of payload.tables.entries()) {
    if (!Array.isArray(table.columns) || !Array.isArray(table.rows) || table.columns.length === 0) {
      throw new Error(`Table ${tableIndex + 1} is missing columns or rows.`);
    }
    for (const [rowIndex, row] of table.rows.entries()) {
      if (!Array.isArray(row) || row.length !== table.columns.length) {
        throw new Error(`Table ${tableIndex + 1}, row ${rowIndex + 1} is not rectangular.`);
      }
    }
  }
}


function equalCell(expected, actual) {
  if (expected == null && actual == null) return true;
  return expected === actual;
}


function rowCounts(rows) {
  const counts = new Map();
  for (const row of rows) {
    const key = JSON.stringify(row);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}


function isSubset(left, right) {
  for (const [key, count] of left.entries()) {
    if ((right.get(key) ?? 0) < count) return false;
  }
  return true;
}


function detectDuplicates(tables) {
  const warnings = [];
  for (let leftIndex = 0; leftIndex < tables.length; leftIndex += 1) {
    const left = tables[leftIndex];
    const leftColumns = JSON.stringify(left.columns.map((column) => String(column.name).toLowerCase()));
    const leftRows = rowCounts(left.rows);
    for (let rightIndex = leftIndex + 1; rightIndex < tables.length; rightIndex += 1) {
      const right = tables[rightIndex];
      const rightColumns = JSON.stringify(right.columns.map((column) => String(column.name).toLowerCase()));
      if (leftColumns !== rightColumns) continue;
      const rightRows = rowCounts(right.rows);
      const leftInRight = isSubset(leftRows, rightRows);
      const rightInLeft = isSubset(rightRows, leftRows);
      let relation = null;
      if (leftInRight && rightInLeft) relation = "exact_duplicate";
      else if (leftInRight) relation = "left_subset_of_right";
      else if (rightInLeft) relation = "right_subset_of_left";
      if (relation) {
        warnings.push({
          kind: relation,
          left_table_id: left.table_id,
          right_table_id: right.table_id,
        });
      }
    }
  }
  return warnings;
}


const { normalizedPath, outputDir, force } = parseArgs(process.argv.slice(2));
const payload = JSON.parse(await fs.readFile(normalizedPath, "utf8"));
assertPayload(payload);
await fs.mkdir(outputDir, { recursive: true });
const previewDir = path.join(outputDir, "_previews");
await fs.mkdir(previewDir, { recursive: true });

const usedNames = new Set();
const outputs = [];

for (let index = 0; index < payload.tables.length; index += 1) {
  const table = payload.tables[index];
  const role = table.source_role === "main" ? "main" : "attachment";
  const tablePart = safeSegment(table.table_id, `table_${index + 1}`);
  const titlePart = safeSegment(table.title, "data").slice(0, 48);
  let base = `${String(index + 1).padStart(2, "0")}_${role}_${tablePart}_${titlePart}`;
  let suffix = 2;
  while (usedNames.has(base.toLowerCase())) {
    base = `${base}_${suffix}`;
    suffix += 1;
  }
  usedNames.add(base.toLowerCase());
  const filename = `${base}.xlsx`;
  const outputPath = path.join(outputDir, filename);
  try {
    await fs.access(outputPath);
    if (!force) throw new Error(`Refusing to overwrite existing workbook: ${outputPath}`);
  } catch (error) {
    if (error?.code !== "ENOENT" && !force) throw error;
  }

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Data");
  const headers = table.columns.map((column) => column.name);
  const columnCount = headers.length;
  const rowCount = table.rows.length;
  const lastColumn = columnLetter(columnCount);
  const lastRow = rowCount + 1;
  sheet.showGridLines = true;
  sheet.getRange("A1").write([headers, ...table.rows]);

  const header = sheet.getRange(`A1:${lastColumn}1`);
  header.format = {
    fill: "#1F4E78",
    font: { name: "Arial", size: 11, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#FFFFFF" },
  };
  header.format.rowHeight = 32;

  const body = sheet.getRange(`A2:${lastColumn}${lastRow}`);
  body.format = {
    font: { name: "Arial", size: 11, color: "#000000" },
    verticalAlignment: "center",
  };
  body.format.rowHeight = 21;

  for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
    const column = table.columns[columnIndex];
    const letter = columnLetter(columnIndex + 1);
    const range = sheet.getRange(`${letter}2:${letter}${lastRow}`);
    range.format.horizontalAlignment = column.type === "text" ? "left" : "right";
    range.format.numberFormat = numberFormat(column);
    sheet.getRange(`${letter}:${letter}`).format.columnWidth = widthFor(column, columnIndex, table.rows);
  }
  sheet.freezePanes.freezeRows(1);

  const preview = await workbook.render({
    sheetName: "Data",
    range: `A1:${lastColumn}${Math.min(lastRow, 51)}`,
    scale: 1.25,
    format: "png",
  });
  const previewPath = path.join(previewDir, `${base}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(outputPath);
  const bytes = await fs.readFile(outputPath);

  const reopened = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
  if (reopened.worksheets.items.length !== 1) {
    throw new Error(`Saved workbook must contain exactly one worksheet: ${filename}`);
  }
  const reopenedSheet = reopened.worksheets.getItem("Data");
  const reopenedValues = reopenedSheet.getRange(`A1:${lastColumn}${lastRow}`).values;
  if (reopenedValues.length !== lastRow || reopenedValues[0].length !== columnCount) {
    throw new Error(`Saved workbook shape mismatch: ${filename}`);
  }
  const expectedValues = [headers, ...table.rows];
  for (let rowIndex = 0; rowIndex < expectedValues.length; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
      if (!equalCell(expectedValues[rowIndex][columnIndex], reopenedValues[rowIndex][columnIndex])) {
        throw new Error(`Saved value mismatch in ${filename} at row ${rowIndex + 1}, column ${columnIndex + 1}`);
      }
    }
  }
  const usedAddress = reopenedSheet.getUsedRange().address;
  if (usedAddress !== `A1:${lastColumn}${lastRow}`) {
    throw new Error(`Unexpected used range in ${filename}: ${usedAddress}`);
  }
  const errors = await reopened.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 100 },
    summary: "saved workbook error scan",
  });
  if (!errors.ndjson.includes("matched 0 entries")) {
    throw new Error(`Spreadsheet error token found in ${filename}: ${errors.ndjson}`);
  }

  outputs.push({
    filename,
    sha256: sha256(bytes),
    bytes: bytes.length,
    sheet: "Data",
    header_row: 1,
    data_start_row: 2,
    rows: rowCount,
    columns: columnCount,
    table_id: table.table_id,
    title: table.title,
    source_role: table.source_role,
    source_file: table.source_file,
    source_sha256: table.source_sha256,
    source_locator: table.source_locator,
    candidate_id: table.candidate_id,
    warnings: table.warnings ?? [],
  });
}

const manifest = {
  schema_version: "1.0",
  normalized_input: path.basename(normalizedPath),
  workbook_count: outputs.length,
  workbooks: outputs,
  excluded_candidates: payload.excluded_candidates ?? [],
  duplicate_warnings: detectDuplicates(payload.tables),
};
const manifestPath = path.join(outputDir, "conversion_manifest.json");
await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2), "utf8");
process.stdout.write(`${JSON.stringify({ output_directory: outputDir, manifest: manifestPath, workbook_count: outputs.length }, null, 2)}\n`);
