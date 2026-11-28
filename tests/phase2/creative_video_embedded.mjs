// Optional offline QA transport for a disposable, in-memory PostgreSQL server.
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const root = resolve(process.argv[2]);
const pkg = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
if (pkg.name !== '@electric-sql/pglite' || pkg.version !== '0.5.8') {
  throw Error('Supply the extracted @electric-sql/pglite 0.5.8 test package.');
}
const { PGlite } = await import(pathToFileURL(resolve(root, 'dist/index.js')));
const { pg_trgm } = await import(pathToFileURL(resolve(root, 'dist/contrib/pg_trgm.js')));
const db = new PGlite({ extensions: { pg_trgm } });
await db.waitReady;
try {
  for await (const line of createInterface({ input: process.stdin })) {
    const { sql, params, script } = JSON.parse(line);
    let reply;
    try {
      const result = script ? (await db.exec(sql)).at(-1) : await db.query(sql, params, { rowMode: 'array' });
      reply = { rows: result?.rows ?? [], count: result?.affectedRows ?? 0 };
    } catch (error) {
      reply = { error: error.message, code: error.code };
    }
    process.stdout.write(JSON.stringify(reply, (_, v) => typeof v === 'bigint' ? Number(v) : v) + '\n');
  }
} finally {
  await db.close();
}
