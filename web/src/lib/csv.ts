/**
 * Minimal CSV writer for the transfers report.
 *
 * French spreadsheets expect a semicolon separator and a UTF-8 BOM; every
 * field containing the separator, a quote or a line break is quoted, and inner
 * quotes are doubled (RFC 4180).
 */
export type CsvValue = string | number | null | undefined;

// Leading characters Excel/LibreOffice interpret as a formula. A display name
// such as `=HYPERLINK("http://evil")` must stay inert when the CSV is opened.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

export function escapeCsv(value: CsvValue): string {
  const raw = value === null || value === undefined ? "" : String(value);
  // Prefix with an apostrophe (the spreadsheet "treat as text" marker) BEFORE
  // quoting, so the payload never starts a formula.
  const text = FORMULA_PREFIX.test(raw) ? `'${raw}` : raw;
  if (/[;"\r\n\t]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function toCsv(
  headers: readonly string[],
  rows: ReadonlyArray<ReadonlyArray<CsvValue>>,
): string {
  return [headers, ...rows]
    .map((row) => row.map(escapeCsv).join(";"))
    .join("\r\n");
}

/** Trigger a browser download without keeping the object URL alive. */
export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob(["\ufeff", content], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
