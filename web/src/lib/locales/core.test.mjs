// node --test web/src/lib/locales/core.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { createLocales } from './core.ts';

const locales = createLocales(JSON.parse(readFileSync(new URL('./catalogue.generated.json', import.meta.url), 'utf8')));
const first = (query) => locales.search(query)[0]?.entry.tag;

test('search finds a language by nickname, native name, region, script or accent-free spelling', () => {
  assert.equal(first('canto'), 'yue-Hant-HK');
  assert.equal(locales.search('canto')[0].alias, 'canto');
  assert.equal(first('廣東'), 'yue-Hant-HK');
  assert.equal(first('hk'), 'zh-Hant-HK');
  assert.deepEqual(new Set(locales.search('繁').slice(0, 3).map((r) => r.entry.tag)), new Set(['zh-Hant-HK', 'yue-Hant-HK', 'zh-Hant-TW']));
  assert.equal(first('brasil'), 'pt-BR');
  assert.equal(first('scot'), 'en-GB-scotland');
  assert.match(first('espanol'), /^es(-|$)/);
  assert.deepEqual(locales.search('portugese'), []);
  assert.equal(locales.didYouMean('portugese'), 'Portuguese');
});

test('canonical reads old values, aliases and names, and refuses what is not a language', () => {
  const cases = { English: 'en', 繁體中文: 'zh-Hant', 'zh-HK': 'zh-Hant-HK', 'zh-hant-hk': 'zh-Hant-HK', yue: 'yue-Hant-HK', ja: 'ja-JP', '简体中文（中国）': 'zh-Hans-CN', 'es-cl': 'es-CL' };
  for (const [value, tag] of Object.entries(cases)) assert.equal(locales.canonical(value), tag, value);
  for (const value of [null, '', 'klingon', 'en-u-ca-gregory', 'zh']) assert.equal(locales.canonical(value), null, String(value));
  assert.ok(locales.same('繁體中文', 'zh-Hant'));
  assert.equal(locales.displayName('zh-Hans-CN'), '简体中文（中国）');
  assert.equal(locales.flag('English'), '🌐');
  assert.equal(locales.flag('zh-HK'), '🇭🇰');
});

test('languages named in the message pair with channels like the server does', () => {
  const pairs = (text) => Object.fromEntries([...locales.parseMessageLanguages(text).perPlatform].map(([p, hits]) => [p, hits.map((h) => h.tag)]));
  assert.deepEqual(pairs('Sunday recital post. Threads in British English, and 小紅書用台灣中文寫。'), { Threads: ['en-GB'], Xiaohongshu: ['zh-Hant-TW'] });
  assert.deepEqual(pairs('Instagram in Hong Kong Chinese and British English.'), { Instagram: ['zh-Hant-HK', 'en-GB'] });
  assert.deepEqual(locales.parseMessageLanguages('Write a post about Sunday’s recital in Japanese.').all.map((h) => h.tag), ['ja-JP']);
  const none = locales.parseMessageLanguages('A post about the Japanese food we had after the recital in Hong Kong.');
  assert.equal(none.all, null);
  assert.equal(none.perPlatform.size, 0);
  const chinese = locales.parseMessageLanguages('write it in Chinese');
  assert.deepEqual(locales.effectiveLanguages('Instagram', ['zh-Hant-HK'], chinese), [{ tag: 'zh-Hant-HK', fromMessage: false }]);
  assert.deepEqual(locales.effectiveLanguages('Threads', ['en-US'], chinese).map((l) => [l.tag, l.fromMessage]), [['zh-Hant', true]]);
});
