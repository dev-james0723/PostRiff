#!/usr/bin/env node
/**
 * Copy audit for customer-facing UI (UI simplification spec §36).
 *
 *   node scripts/copy-audit.mjs          list every suspicious phrase for manual review
 *   node scripts/copy-audit.mjs --check  fail on implementation words, or on a product name other than "Rafii"
 *
 * It reads string literals and JSX text in the app's customer surfaces, skipping comments,
 * tests and /dev pages. Review matches by hand; nothing is rewritten automatically. A line that
 * legitimately needs a flagged word (a developer-only surface) carries `copy-audit: allow`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));

/** Customer surfaces. Marketing and legal pages are out of scope for wording: they are documents, not app UI. */
export const ROOTS = ['src/features', 'src/components', 'src/app/app', 'src/app/auth', 'src/app/invite', 'src/app/channels', 'src/config', 'src/lib', 'src/hooks'];
/** The product name is checked everywhere a person can read it, marketing and legal pages included. */
export const NAME_ROOTS = [...ROOTS, 'src/app', 'src/content'];
const SKIP = [/\.test\./, /\/dev\//, /\/components\/ui\//, /\.d\.ts$/];

/** Words that expose how Rafii is built. None of them belongs in normal product UI. */
export const BANNED = [/\bdeployment\b/i, /\bbackend\b/i, /\bdatabase\b/i, /\bpayload\b/i, /\bschema\b/i, /\bstaging\b/i];

/**
 * The public name is "Rafii". The legacy "PostRiff" survives only in identifiers (packages, env vars, headers,
 * storage keys, type names), which are lower case or excluded below; any spelling a person could read is flagged.
 */
export const NAMING = [/PostRiff/, /Post Riff/i, /\bRaffi\b/, /\bRafi\b/, /\bRaffii\b/i, /\bRAFII\b/];
const NAME_IDENTIFIERS = /X-PostRiff-Request|PostRiffApi/g;

/** Phrases worth a second look: often filler, defensive or engineering language. */
export const SUSPICIOUS = [
  /\bprovider\b/i,
  /\bimplementation\b/i,
  /\bsuccessfully\b/i,
  /\bcurrently\b/i,
  /\bplease note\b/i,
  /\bplease be aware\b/i,
  /\bthis means\b/i,
  /\bin order to\b/i,
  /\bat this time\b/i,
  /\bfunctionality\b/i,
  /\bdon[’']t worry\b/i,
  /\bkeep in mind\b/i
];

function files(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...files(path));
    else if (/\.(tsx|ts)$/.test(name) && !SKIP.some((re) => re.test(path))) out.push(path);
  }
  return out;
}

/** Text a person could read: quoted strings with a space or a capital, and JSX text. Class names and keys are skipped. */
export function copySegments(line) {
  const segments = [];
  for (const match of line.matchAll(/(['"`])((?:\\.|(?!\1).)*)\1/g)) {
    const text = match[2];
    if (/\s/.test(text.trim()) || /^[A-Z]/.test(text)) segments.push(text);
  }
  for (const match of line.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)</g)) if (!/[;=]|\w\(|:\s*\w+\s*[,|)]/.test(match[1])) segments.push(match[1]);
  return segments.filter((text) => !/^(?:[\w-]+:)?[a-z0-9-[\]/.:]+(?:\s+(?:[\w-]+:)?[a-z0-9-[\]/.:()%]+)*$/.test(text.trim()));
}

export function audit({ patterns, root = WEB, roots = ROOTS, wholeLine = false } = {}) {
  const findings = [];
  const seen = new Set();
  for (const base of roots) {
    for (const file of files(join(root, base))) {
      if (seen.has(file)) continue;
      seen.add(file);
      let inBlock = false;
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((raw, index) => {
          const trimmed = raw.trim();
          if (inBlock) {
            if (trimmed.includes('*/')) inBlock = false;
            return;
          }
          if (trimmed.startsWith('/*') || trimmed.startsWith('{/*')) {
            if (!trimmed.includes('*/')) inBlock = true;
            return;
          }
          if (trimmed.startsWith('//') || trimmed.startsWith('*') || raw.includes('copy-audit: allow')) return;
          const line = raw.replace(/\s\/\/\s.*$/, '').replace(NAME_IDENTIFIERS, '');
          for (const text of wholeLine ? [line] : copySegments(line)) {
            const hit = patterns.find((re) => re.test(text));
            if (hit) findings.push({ file: relative(root, file), line: index + 1, term: hit.source, text: text.trim() });
          }
        });
    }
  }
  return findings;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const check = process.argv.includes('--check');
  const findings = [...audit({ patterns: check ? BANNED : [...BANNED, ...SUSPICIOUS] }), ...audit({ patterns: NAMING, roots: NAME_ROOTS, wholeLine: true })];
  for (const f of findings) console.log(`${f.file}:${f.line}  [${f.term}]  ${f.text.slice(0, 140)}`);
  console.log(`\n${findings.length} ${check ? 'banned' : 'flagged'} phrase${findings.length === 1 ? '' : 's'}${check ? '' : ' for manual review'}.`);
  if (check && findings.length) process.exit(1);
}
