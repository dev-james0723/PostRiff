/**
 * Client-side parser/renderer watchdog (React-free; 02-CONTRACTS §7 "C controls a parser/renderer watchdog").
 *
 * Candidate source while streaming is untrusted preview text. Before it reaches OpenUI's streaming parser (which
 * re-parses the whole text on every update) the renderer checks it here: too large, too deeply nested or too many
 * statements stops progressive rendering and keeps the native answer, without throwing and without asking for a repair
 * (repairs are decided by the server). Accepted canonical sources were bounded by the trusted validator already; they
 * are checked again because a stored artifact is still data.
 */
import { BOUNDS } from '@/lib/agent-runtime/ui-contracts';
import { maxBracketDepth, utf8Bytes } from '@/lib/agent-runtime/ui-parser/source-scan';

export type WatchdogReason = 'source_too_large' | 'nesting_too_deep' | 'too_many_statements';

export const WATCHDOG = {
  sourceBytes: BOUNDS.sourceBytes,
  bracketDepth: 64,
  statements: BOUNDS.statements,
  /** While streaming, hand the parser a new text at most this often (it re-parses everything each time). */
  streamUpdateMs: 120,
} as const;

/** Rough statement count: lines that look like `name = …` at bracket depth 0 (cheap; the parser counts exactly). */
export function roughStatementCount(source: string): number {
  let count = 0;
  let depth = 0;
  let inStr: string | false = false;
  let lineStart = true;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (inStr) {
      if (c === '\\') i++;
      else if (c === inStr) inStr = false;
      continue;
    }
    if (c === '"' || c === "'") inStr = c;
    else if (c === '(' || c === '[' || c === '{') depth++;
    else if (c === ')' || c === ']' || c === '}') depth = Math.max(0, depth - 1);
    else if (c === '\n') {
      lineStart = true;
      continue;
    } else if (lineStart && depth === 0 && c !== ' ' && c !== '\t') {
      count++;
    }
    lineStart = false;
  }
  return count;
}

export function checkSource(source: string | null | undefined): WatchdogReason | null {
  if (!source) return null;
  if (source.length > WATCHDOG.sourceBytes || utf8Bytes(source) > WATCHDOG.sourceBytes) return 'source_too_large';
  if (maxBracketDepth(source) > WATCHDOG.bracketDepth) return 'nesting_too_deep';
  if (roughStatementCount(source) > WATCHDOG.statements + 8) return 'too_many_statements';
  return null;
}
