/**
 * CSV rows as RFC 4180 defines them: a quoted field may hold commas, doubled quotes and line breaks.
 * Never throws; a quote that is never closed runs to the end of the text.
 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  let started = false;
  for (let index = text.charCodeAt(0) === 0xfeff ? 1 : 0; index < text.length; index++) {
    const char = text[index];
    if (quoted) {
      if (char !== '"') field += char;
      else if (text[index + 1] === '"') {
        field += '"';
        index++;
      } else quoted = false;
      continue;
    }
    if (char === '"' && field === '') {
      quoted = true;
      started = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
      started = true;
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index++;
      if (started || field !== '') {
        row.push(field);
        rows.push(row);
      }
      row = [];
      field = '';
      started = false;
    } else {
      field += char;
      started = true;
    }
  }
  if (started || field !== '') {
    row.push(field);
    rows.push(row);
  }
  return rows;
}
