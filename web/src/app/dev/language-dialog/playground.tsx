'use client';

import { useMemo, useState } from 'react';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { LanguageDialog, type LanguageDialogApi, type LanguageSelectionItem } from '@/features/agent/language-dialog';
import { SettingButtons } from '@/features/agent/setting-buttons';
import type { LocaleTag } from '@/lib/api/types';
import { locales } from '@/lib/locales';

type Item = LanguageSelectionItem & { account?: string };

const INITIAL: Item[] = [
  { platform: 'LinkedIn', languages: null },
  { platform: 'Instagram', channelId: 'ig-studio', account: '@jamesau.studio', languages: ['zh-Hant-HK', 'en-GB'] },
  { platform: 'Threads', languages: ['ja-JP'] }
];

/**
 * Mounts the dialog over local state that mirrors `useChannelLanguages`' contract: `change/add/remove`
 * are addressed by platform today (the hook's current API) and every call is logged so staging →
 * apply can be checked by eye. Nothing here talks to the API.
 */
export function LanguageDialogPlayground() {
  const [items, setItems] = useState<Item[]>(INITIAL);
  const [open, setOpen] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [suggestions] = useState(() => [{ tag: 'en-US', reason: 'Browser' }]);

  const api = useMemo<LanguageDialogApi>(() => {
    const languagesOf = (item: LanguageSelectionItem) => item.languages ?? [locales.usualFor(item.platform) ?? 'en-US'];
    const update = (target: string, next: (list: LocaleTag[]) => LocaleTag[]) =>
      setItems((current) => current.map((item) => (item.platform === target ? { ...item, languages: Array.from(new Set(next(languagesOf(item)))).slice(0, 4) } : item)));
    return {
      languagesOf,
      suggestions,
      settings: { channels: { Instagram: ['zh-Hant-HK', 'en-GB'] } },
      change(target, index, tag) {
        setLog((l) => [...l, `change(${target}, ${index}, ${tag})`]);
        update(target, (list) => list.map((current, i) => (i === index ? tag : current)));
      },
      add(target, tag) {
        setLog((l) => [...l, `add(${target}, ${tag})`]);
        update(target, (list) => [...list, tag]);
      },
      remove(target, index) {
        setLog((l) => [...l, `remove(${target}, ${index})`]);
        update(target, (list) => (list.length > 1 ? list.filter((_, i) => i !== index) : list));
      },
      useEverywhere(tag) {
        setLog((l) => [...l, `useEverywhere(${tag})`]);
        setItems((current) => current.map((item) => ({ ...item, languages: [tag] })));
      }
    };
  }, [suggestions]);

  const label = (item: LanguageSelectionItem) => {
    const found = items.find((entry) => entry === item || (entry.platform === item.platform && entry.channelId === item.channelId));
    return found?.account ? `${item.platform} · ${found.account}` : item.platform;
  };
  const summary = items.map((item) => api.languagesOf(item)).flat();
  const unique = Array.from(new Set(summary));

  return (
    <main className='bg-background text-foreground mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-6 px-4 py-8'>
      <header>
        <p className='rafii-eyebrow'>Dev · Rafii v9 stream C</p>
        <h1 className='mt-1 text-2xl font-medium tracking-tight'>Output language dialog</h1>
        <p className='text-muted-foreground mt-1 text-sm'>Local state only. Apply commits through the same calls the composer hook exposes.</p>
      </header>
      <SettingButtons
        language={{ value: unique.length === 1 ? <LanguageName language={unique[0]} /> : `${unique.length} languages across ${items.length} channels`, onClick: () => setOpen(true), expanded: open, controls: 'dev-language-dialog' }}
        model={{ value: 'Claude Code · sonnet', onClick: () => {}, disabled: true }}
        voice={{ value: 'Neutral', onClick: () => {}, popup: 'none', pressed: false, disabled: true }}
      />
      <LanguageDialog id='dev-language-dialog' open={open} onOpenChange={setOpen} selection={items} languages={api} accountLabel={label} />
      <section className='rafii-quiet rounded-[var(--rafii-radius-card)] p-4 text-sm'>
        <h2 className='mb-2 font-medium'>Applied configuration</h2>
        <output aria-label='Applied languages' className='block font-mono text-xs whitespace-pre-wrap'>
          {JSON.stringify(Object.fromEntries(items.map((item) => [label(item), api.languagesOf(item)])), null, 2)}
        </output>
      </section>
      <section className='rafii-quiet rounded-[var(--rafii-radius-card)] p-4 text-sm'>
        <h2 className='mb-2 font-medium'>Hook calls</h2>
        <output aria-label='Hook calls' className='block font-mono text-xs whitespace-pre-wrap'>
          {log.length ? log.join('\n') : '(none yet)'}
        </output>
      </section>
    </main>
  );
}
