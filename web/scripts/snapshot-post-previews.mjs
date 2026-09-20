#!/usr/bin/env node
/**
 * Snapshots every post preview template from the dev gallery (/dev/post-previews) with headless Chrome and
 * compares the set with the previous run, so the monthly re-check sees which drawings changed. Needs the web dev
 * server running. Time and zone are pinned, so the status-bar clock never reads as a change.
 *
 *   node scripts/snapshot-post-previews.mjs [--base http://localhost:3100] [--only instagram,threads] [--media none,one] [--appearance light,dark]
 *
 * Writes .snapshots/post-previews/<YYYY-MM-DD>/<channel>-<media>-<appearance>.png and manifest.json (SHA-256 per
 * image; a template without a dark palette draws the same image twice), then
 * prints which images are new, changed or unchanged against the latest earlier run.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const argument = (name) => {
  const index = process.argv.indexOf(name);
  return index > -1 ? process.argv[index + 1] : undefined;
};

const base = (argument('--base') ?? process.env.POSTRIFF_WEB_ORIGIN ?? 'http://localhost:3100').replace(/\/$/, '');
const chrome = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const media = (argument('--media') ?? 'none,one').split(',');
const appearances = (argument('--appearance') ?? 'light,dark').split(',');
const AT = '2026-09-16T09:41:00Z';
const TIME_ZONE = 'UTC';

const registry = readFileSync(join(root, 'src/components/application/post-preview/templates/index.ts'), 'utf8');
const all = [...registry.matchAll(/^\s+'?([a-z0-9-]+)'?: \(\) => import/gm)].map((match) => match[1]).filter((slug) => slug !== 'generic');
const only = argument('--only')?.split(',');
const channels = only ? all.filter((slug) => only.includes(slug)) : all;

if (!existsSync(chrome)) {
  console.error(`Chrome not found at ${chrome}. Set CHROME_PATH.`);
  process.exit(1);
}
try {
  const response = await fetch(`${base}/dev/post-previews`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
} catch (error) {
  console.error(`The gallery at ${base}/dev/post-previews is not reachable (${error.message}). Start the web dev server first.`);
  process.exit(1);
}

const snapshots = join(root, '.snapshots/post-previews');
const now = new Date();
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
const folder = join(snapshots, today);
mkdirSync(folder, { recursive: true });

const manifest = {};
for (const slug of channels) {
  for (const [choice, appearance] of media.flatMap((item) => appearances.map((look) => [item, look]))) {
    const name = `${slug}-${choice}-${appearance}.png`;
    const url = `${base}/dev/post-previews?snapshot&channel=${slug}&media=${choice}&appearance=${appearance}&at=${encodeURIComponent(AT)}&tz=${TIME_ZONE}`;
    execFileSync(
      chrome,
      ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=2', '--window-size=420,860', '--virtual-time-budget=10000', `--screenshot=${join(folder, name)}`, url],
      { stdio: 'ignore', timeout: 90_000 }
    );
    manifest[name] = createHash('sha256').update(readFileSync(join(folder, name))).digest('hex');
    process.stdout.write('.');
  }
}
process.stdout.write('\n');
writeFileSync(join(folder, 'manifest.json'), `${JSON.stringify({ at: AT, timeZone: TIME_ZONE, base, images: manifest }, null, 2)}\n`);

const earlier = readdirSync(snapshots)
  .filter((entry) => entry < today && statSync(join(snapshots, entry)).isDirectory() && existsSync(join(snapshots, entry, 'manifest.json')))
  .toSorted()
  .at(-1);
if (!earlier) {
  console.log(`Saved ${Object.keys(manifest).length} images to ${folder}. No earlier run to compare with.`);
  process.exit(0);
}
const previous = JSON.parse(readFileSync(join(snapshots, earlier, 'manifest.json'), 'utf8')).images;
const changed = Object.keys(manifest).filter((name) => previous[name] && previous[name] !== manifest[name]);
const added = Object.keys(manifest).filter((name) => !previous[name]);
const unchanged = Object.keys(manifest).length - changed.length - added.length;
console.log(`Compared with ${earlier}: ${changed.length} changed, ${added.length} new, ${unchanged} unchanged.`);
for (const name of changed) console.log(`  changed  ${name}   ${join(snapshots, earlier, name)} -> ${join(folder, name)}`);
for (const name of added) console.log(`  new      ${name}`);
