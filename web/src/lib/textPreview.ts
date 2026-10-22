/**
 * Helpers for the text-family preview (plain text, CSV/TSV, JSON). Everything
 * here returns data; the UI renders it as escaped text, never as markup.
 */

/** Read at most `maxBytes` from the start of a response, then stop the transfer. */
export async function readTextHead(
  url: string,
  maxBytes: number,
  signal?: AbortSignal,
): Promise<{ text: string; truncated: boolean }> {
  const response = await fetch(url, {
    signal,
    credentials: "omit",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const reader = response.body?.getReader();
  if (!reader) {
    const text = await response.text();
    return { text: text.slice(0, maxBytes), truncated: text.length > maxBytes };
  }
  const chunks: Uint8Array[] = [];
  let received = 0;
  let truncated = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    if (received >= maxBytes) {
      truncated = true;
      await reader.cancel();
      break;
    }
  }
  const bytes = new Uint8Array(Math.min(received, maxBytes));
  let offset = 0;
  for (const chunk of chunks) {
    const room = bytes.length - offset;
    if (room <= 0) break;
    bytes.set(chunk.subarray(0, room), offset);
    offset += Math.min(chunk.byteLength, room);
  }
  return { text: new TextDecoder("utf-8", { fatal: false }).decode(bytes), truncated };
}

/** Indented JSON, or null when the text is not valid JSON (show it raw then). */
export function prettyJson(text: string): string | null {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

export interface CsvTable {
  rows: string[][];
  /** Rows or columns were dropped to keep the table readable. */
  clipped: boolean;
}

/** Pick `,`, `;` or tab from the first line (the one that occurs most). */
export function detectDelimiter(firstLine: string): string {
  const candidates = [",", ";", "\t"];
  let best = ",";
  let bestCount = -1;
  for (const candidate of candidates) {
    const count = firstLine.split(candidate).length - 1;
    if (count > bestCount) {
      best = candidate;
      bestCount = count;
    }
  }
  return best;
}

/** Small RFC 4180 parser (quotes, doubled quotes, CRLF), bounded in rows/columns. */
export function parseCsv(
  text: string,
  opts: { maxRows?: number; maxCols?: number; delimiter?: string } = {},
): CsvTable {
  const maxRows = opts.maxRows ?? 200;
  const maxCols = opts.maxCols ?? 30;
  const delimiter = opts.delimiter ?? detectDelimiter(text.split(/\r?\n/, 1)[0] ?? "");
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let clipped = false;

  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    if (row.length > maxCols) {
      row = row.slice(0, maxCols);
      clipped = true;
    }
    // A blank line is not a record.
    if (!(row.length === 1 && row[0] === "")) rows.push(row);
    row = [];
  };

  for (let i = 0; i < text.length && rows.length < maxRows; i += 1) {
    const ch = text[i]!;
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"' && field === "") {
      quoted = true;
    } else if (ch === delimiter) {
      endField();
    } else if (ch === "\n") {
      endRow();
    } else if (ch === "\r") {
      if (text[i + 1] !== "\n") endRow();
    } else {
      field += ch;
    }
  }
  if (rows.length < maxRows && (field !== "" || row.length > 0)) endRow();
  else if (rows.length >= maxRows) clipped = true;
  return { rows, clipped };
}
