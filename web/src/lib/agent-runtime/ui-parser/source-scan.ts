/**
 * Character-level pre-scans for the trusted OpenUI validator (no regular expressions over DSL, no evaluation).
 *
 * `stripLineComments` mirrors lang-core 0.3.2 `stripComments` (dist/index.mjs:2912-2934) exactly, so the canonical source
 * the validator stores is what the official parser would see after its own preprocessing. The parser itself still does
 * all parsing; these helpers only bound the input before it reaches the (recursive) parser.
 */

const encoder = new TextEncoder();

export function utf8Bytes(text: string): number {
  return encoder.encode(text).length;
}

/** `//` and `#` line comments outside '…' / "…" strings are removed; string state carries across lines like upstream. */
export function stripLineComments(input: string): string {
  let inStr: string | false = false;
  return input
    .split('\n')
    .map((line) => {
      for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (inStr) {
          if (c === '\\' && i + 1 < line.length) {
            i++;
            continue;
          }
          if (c === inStr) inStr = false;
          continue;
        }
        if (c === '"' || c === "'") {
          inStr = c;
          continue;
        }
        if (c === '/' && line[i + 1] === '/') return line.substring(0, i).trimEnd();
        if (c === '#') return line.substring(0, i).trimEnd();
      }
      return line;
    })
    .join('\n');
}

/** Deepest (, [ or { nesting outside strings, with the same string rules as lang-core `autoClose`. */
export function maxBracketDepth(input: string): number {
  let depth = 0;
  let max = 0;
  let inStr: string | false = false;
  let esc = false;
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (esc) {
      esc = false;
      continue;
    }
    if (c === '\\' && inStr) {
      esc = true;
      continue;
    }
    if (inStr) {
      if (c === inStr) inStr = false;
      continue;
    }
    if (c === '"' || c === "'") {
      inStr = c;
      continue;
    }
    if (c === '(' || c === '[' || c === '{') {
      depth += 1;
      if (depth > max) max = depth;
    } else if (c === ')' || c === ']' || c === '}') {
      depth = Math.max(0, depth - 1);
    }
  }
  return max;
}

/** True when the text contains a Markdown code fence (```) outside strings; canonical source never does. */
export function hasFence(input: string): boolean {
  let inStr: string | false = false;
  let esc = false;
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (esc) {
      esc = false;
      continue;
    }
    if (c === '\\' && inStr) {
      esc = true;
      continue;
    }
    if (inStr) {
      if (c === inStr) inStr = false;
      continue;
    }
    if (c === '"' || c === "'") {
      inStr = c;
      continue;
    }
    if (c === '`' && input[i + 1] === '`' && input[i + 2] === '`') return true;
  }
  return false;
}
