'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import type { Destination, LanguageSettings, LocaleTag, Snapshot } from '@/lib/api/types';
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

/** A drafting target: an account (`channelId` = `Phase2State.channels[].id`) or a platform drafted without one. */
export interface ChannelTarget<P extends string = string> {
  platform: P;
  channelId?: string;
}

/** The selection key: the account id, else the platform. Two accounts on one platform are two items. */
export const selectionKey = (target: { platform: string; channelId?: string }): string => target.channelId ?? target.platform;

export interface ChannelSelection<P extends string = string> extends ChannelTarget<P> {
  /** `selectionKey(item)`: what `toggle`, `add`, `change` and `remove` address. */
  key: string;
  /** null until the person picks: the channel then follows what the workspace remembers. */
  languages: LocaleTag[] | null;
}

function toItem<P extends string>(target: ChannelTarget<P>): ChannelSelection<P> {
  return target.channelId ? { key: target.channelId, platform: target.platform, channelId: target.channelId, languages: null } : { key: target.platform, platform: target.platform, languages: null };
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
 *
 * Items are keyed by `selectionKey` (Rafii v9 D4): an account is its connection id, a platform drafted
 * without an account is the platform. Languages stay remembered per platform, so two accounts on one
 * platform start from the same remembered languages but can diverge for a draft.
 */
export function useChannelLanguages<P extends string>(initial: P[]) {
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const [selection, setSelection] = useState<ChannelSelection<P>[]>(() => initial.map((platform) => toItem({ platform })));
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const settings = useMemo(() => settingsOf(snapshot.data), [snapshot.data]);
  const [suggestions, setSuggestions] = useState<{ tag: LocaleTag; reason: string }[]>([]);
  useEffect(() => { setSuggestions(browserSuggestions()); }, []);

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

  const languagesOf = useCallback((item: { platform: string; languages: LocaleTag[] | null }) => item.languages ?? startingLanguages(item.platform), [startingLanguages]);

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
          toast.error(error instanceof ApiError ? error.message : 'Couldn’t save your language choice. It still applies to this draft.');
        }
      };
      saving.current = saving.current.then(() => attempt(true));
    },
    [api, client, workspaceId]
  );

  /** The item a key addresses; a bare platform also reaches that platform's first account item. */
  const itemFor = useCallback((key: string): ChannelSelection<P> => selection.find((entry) => entry.key === key) ?? selection.find((entry) => entry.platform === key) ?? toItem({ platform: key as P }), [selection]);

  const update = useCallback(
    (key: string, next: (languages: LocaleTag[]) => LocaleTag[]) => {
      const item = itemFor(key);
      const saved = Array.from(new Set(next(languagesOf(item)))).slice(0, 4);
      setSelection((current) =>
        current.map((entry) => {
          if (entry.key === item.key) return { ...entry, languages: saved };
          // Saving the platform's memory must not silently re-language another account on that platform:
          // it keeps the languages it shows now (two accounts on one app stay separate destinations).
          if (entry.platform === item.platform && entry.languages === null) return { ...entry, languages: languagesOf(entry) };
          return entry;
        })
      );
      save({ channels: { [item.platform]: saved } });
    },
    [itemFor, languagesOf, save]
  );

  return {
    selection,
    settings,
    suggestions,
    languagesOf,
    /** Each platform once, in chip order (two accounts on one platform are still one platform). */
    selectedPlatforms: Array.from(new Set(selection.map((item) => item.platform))),
    /** One destination per (item, language), in chip order; `channelId` names the account when there is one. */
    destinations: selection.flatMap((item): Destination[] => languagesOf(item).map((language) => (item.channelId ? { platform: item.platform, language, channelId: item.channelId } : { platform: item.platform, language }))),
    /**
     * Toggle one target by key. A bare platform toggles at platform level: off removes every item on
     * that platform (accounts included), on adds the platform drafted without an account.
     */
    toggle(target: P | ChannelTarget<P>) {
      const wanted: ChannelTarget<P> = typeof target === 'string' ? { platform: target } : target;
      const key = selectionKey(wanted);
      setSelection((current) => {
        if (current.some((item) => item.key === key)) return current.filter((item) => item.key !== key);
        if (!wanted.channelId && current.some((item) => item.platform === wanted.platform)) return current.filter((item) => item.platform !== wanted.platform);
        return [...current, toItem(wanted)];
      });
    },
    /** Platform-level selection (modes, Quick Starts): items keyed by platform, languages kept where the key already exists. */
    setPlatforms(platforms: P[]) {
      setSelection((current) => platforms.map((platform) => current.find((item) => item.key === platform) ?? toItem({ platform })));
    },
    /** Account-level selection (Channel Bloom's Done): one item per target, languages kept where the key already exists. */
    setTargets(targets: ChannelTarget<P>[]) {
      const unique = targets.filter((target, i, all) => all.findIndex((other) => selectionKey(other) === selectionKey(target)) === i);
      setSelection((current) => unique.map((target) => current.find((item) => item.key === selectionKey(target)) ?? toItem(target)));
    },
    /** Rebuild from a conversation's last destinations ("draft again" keeps every channel's languages and accounts). */
    restore(destinations: { platform: string; language: string; channelId?: string }[], allowed: readonly P[]) {
      const grouped = new Map<string, ChannelSelection<P>>();
      for (const d of destinations) {
        const tag = locales.canonical(d.language);
        if (!tag || !(allowed as readonly string[]).includes(d.platform)) continue;
        const target: ChannelTarget<P> = d.channelId ? { platform: d.platform as P, channelId: d.channelId } : { platform: d.platform as P };
        const key = selectionKey(target);
        const item = grouped.get(key) ?? { ...toItem(target), languages: [] as LocaleTag[] };
        const list = item.languages ?? [];
        if (!list.includes(tag)) list.push(tag);
        grouped.set(key, { ...item, languages: list });
      }
      if (grouped.size) setSelection([...grouped.values()]);
    },
    change(key: string, index: number, tag: LocaleTag) {
      update(key, (languages) => languages.map((current, i) => (i === index ? tag : current)));
    },
    add(key: string, tag: LocaleTag) {
      update(key, (languages) => [...languages, tag]);
    },
    remove(key: string, index: number) {
      update(key, (languages) => (languages.length > 1 ? languages.filter((_, i) => i !== index) : languages));
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
