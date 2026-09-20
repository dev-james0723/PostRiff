'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import type { LanguageSettings, LocaleTag, Snapshot } from '@/lib/api/types';
import { locales } from '@/lib/locales';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** Where the browser's own settings point; used only to suggest, never sent to the server. */
const ZONE_LOCALES: Record<string, LocaleTag> = {
  'Asia/Hong_Kong': 'zh-Hant-HK', 'Asia/Macau': 'zh-Hant-HK', 'Asia/Taipei': 'zh-Hant-TW', 'Asia/Shanghai': 'zh-Hans-CN', 'Asia/Singapore': 'en-SG',
  'Europe/London': 'en-GB', 'Europe/Dublin': 'en-IE', 'Australia/Sydney': 'en-AU', 'Australia/Melbourne': 'en-AU', 'Pacific/Auckland': 'en-NZ',
  'America/Toronto': 'en-CA', 'America/Vancouver': 'en-CA', 'Asia/Tokyo': 'ja-JP', 'Asia/Seoul': 'ko-KR', 'Europe/Paris': 'fr-FR', 'Europe/Berlin': 'de-DE',
  'America/Mexico_City': 'es-MX', 'America/Sao_Paulo': 'pt-BR', 'Europe/Madrid': 'es-ES', 'America/New_York': 'en-US', 'America/Chicago': 'en-US',
  'America/Denver': 'en-US', 'America/Los_Angeles': 'en-US'
};

export function browserSuggestions(): { tag: LocaleTag; reason: string }[] {
  if (typeof window === 'undefined') return [];
  const out: { tag: LocaleTag; reason: string }[] = [];
  try {
    const zone = ZONE_LOCALES[Intl.DateTimeFormat().resolvedOptions().timeZone];
    if (zone) out.push({ tag: zone, reason: 'Time zone' });
  } catch {
    /* no zone */
  }
  for (const language of navigator.languages ?? []) {
    const tag = locales.canonical(language);
    if (tag && locales.entry(tag)?.guide) {
      out.push({ tag, reason: 'Browser' });
      break;
    }
  }
  return out.filter((item, i) => out.findIndex((other) => other.tag === item.tag) === i);
}

export interface ChannelSelection<P extends string = string> {
  platform: P;
  /** null until the person picks: the channel then follows what the workspace remembers. */
  languages: LocaleTag[] | null;
}

export function settingsOf(snapshot: Snapshot | undefined): LanguageSettings {
  const raw = snapshot?.state?.languageSettings;
  const channels: Record<string, LocaleTag[]> = {};
  for (const [platform, tags] of Object.entries(raw?.channels ?? {})) {
    const clean = (Array.isArray(tags) ? tags : []).map((t) => locales.canonical(t)).filter((t): t is string => Boolean(t));
    if (clean.length) channels[platform] = clean;
  }
  return { default: locales.canonical(raw?.default) ?? null, channels, selfReference: raw?.selfReference ?? null };
}

/**
 * The composer's channels and each channel's languages (languages plan §4). A channel starts with the
 * languages last used on it, then its usual language, the workspace default, then a browser suggestion.
 * Only picks the person makes are saved (`language_settings`); a language named in the message is not.
 */
export function useChannelLanguages<P extends string>(initial: P[]) {
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const [selection, setSelection] = useState<ChannelSelection<P>[]>(() => initial.map((platform) => ({ platform, languages: null })));
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const settings = useMemo(() => settingsOf(snapshot.data), [snapshot.data]);
  const suggestions = useMemo(() => browserSuggestions(), []);

  const startingLanguages = useCallback(
    (platform: string): LocaleTag[] => {
      const remembered = settings.channels[platform];
      if (remembered?.length) return remembered;
      const usual = locales.usualFor(platform);
      if (usual) return [usual];
      return [settings.default ?? suggestions[0]?.tag ?? locales.catalogue.defaultLocale];
    },
    [settings, suggestions]
  );

  const languagesOf = useCallback((item: ChannelSelection<P>) => item.languages ?? startingLanguages(item.platform), [startingLanguages]);

  const save = useCallback(
    (payload: Partial<Pick<LanguageSettings, 'channels' | 'default' | 'selfReference'>>) => {
      if (!workspaceId) return;
      const attempt = async (retry: boolean): Promise<void> => {
        const current = client.getQueryData<Snapshot>(keys.snapshot(workspaceId));
        try {
          const after = await api.act(workspaceId, current?.revision ?? 0, 'language_settings', payload);
          client.setQueryData(keys.snapshot(workspaceId), after);
        } catch (error) {
          if (retry && error instanceof ApiError && error.status === 409) {
            await client.refetchQueries({ queryKey: keys.snapshot(workspaceId) });
            return attempt(false);
          }
          toast.error(error instanceof ApiError ? error.message : 'Your language choice could not be saved; it still applies to this draft.');
        }
      };
      saving.current = saving.current.then(() => attempt(true));
    },
    [api, client, workspaceId]
  );

  const update = useCallback(
    (platform: P, next: (languages: LocaleTag[]) => LocaleTag[]) => {
      const item = selection.find((entry) => entry.platform === platform) ?? { platform, languages: null };
      const saved = Array.from(new Set(next(languagesOf(item)))).slice(0, 4);
      setSelection((current) => current.map((entry) => (entry.platform === platform ? { ...entry, languages: saved } : entry)));
      save({ channels: { [platform]: saved } });
    },
    [languagesOf, save, selection]
  );

  return {
    selection,
    settings,
    suggestions,
    languagesOf,
    selectedPlatforms: selection.map((item) => item.platform),
    /** One destination per (channel, language), in chip order. */
    destinations: selection.flatMap((item) => languagesOf(item).map((language) => ({ platform: item.platform, language }))),
    toggle(platform: P) {
      setSelection((current) => (current.some((item) => item.platform === platform) ? current.filter((item) => item.platform !== platform) : [...current, { platform, languages: null }]));
    },
    setPlatforms(platforms: P[]) {
      setSelection((current) => platforms.map((platform) => current.find((item) => item.platform === platform) ?? { platform, languages: null }));
    },
    /** Rebuild from a conversation's last destinations ("draft again" keeps every channel's languages). */
    restore(destinations: { platform: string; language: string }[], allowed: readonly P[]) {
      const grouped = new Map<P, LocaleTag[]>();
      for (const d of destinations) {
        const tag = locales.canonical(d.language);
        if (!tag || !(allowed as readonly string[]).includes(d.platform)) continue;
        const list = grouped.get(d.platform as P) ?? [];
        if (!list.includes(tag)) list.push(tag);
        grouped.set(d.platform as P, list);
      }
      if (grouped.size) setSelection([...grouped].map(([platform, languages]) => ({ platform, languages })));
    },
    change(platform: P, index: number, tag: LocaleTag) {
      update(platform, (languages) => languages.map((current, i) => (i === index ? tag : current)));
    },
    add(platform: P, tag: LocaleTag) {
      update(platform, (languages) => [...languages, tag]);
    },
    remove(platform: P, index: number) {
      update(platform, (languages) => (languages.length > 1 ? languages.filter((_, i) => i !== index) : languages));
    },
    useEverywhere(tag: LocaleTag) {
      const channels = Object.fromEntries(selection.map((item) => [item.platform, [tag]]));
      setSelection((current) => current.map((item) => ({ ...item, languages: [tag] })));
      save({ channels });
    },
    setSelfReference(value: LanguageSettings['selfReference']) {
      save({ selfReference: value });
    }
  };
}

export type ChannelLanguages<P extends string = string> = ReturnType<typeof useChannelLanguages<P>>;
