'use client';

import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@/components/ui/combobox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { keys, useMe } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { ProfileChanges } from '@/lib/api/types';
import { usePreferences } from '@/lib/preferences';
import { formatDateTime } from '@/lib/time';
import { useWorkspace } from '@/lib/workspace/provider';

/** Languages the formatting layer is exercised with. The app's own copy is English for now. */
const LANGUAGES: { value: string; label: string }[] = [
  { value: 'en', label: 'English (US)' },
  { value: 'en-GB', label: 'English (UK)' },
  { value: 'zh-Hant', label: '繁體中文' },
  { value: 'zh-Hans', label: '简体中文' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'es', label: 'Español' },
  { value: 'pt-BR', label: 'Português (Brasil)' }
];

const DEVICE = 'device';

function allZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone');
  } catch {
    return ['UTC'];
  }
}

/** "Asia/Hong Kong (GMT+8)": the IANA name people recognise, plus the offset they can check. */
export function zoneLabel(zone: string, at = new Date()): string {
  try {
    const offset = new Intl.DateTimeFormat('en', { timeZone: zone, timeZoneName: 'shortOffset' })
      .formatToParts(at)
      .find((part) => part.type === 'timeZoneName')?.value;
    return `${zone.replace(/_/g, ' ')}${offset ? ` (${offset})` : ''}`;
  } catch {
    return zone;
  }
}

export function PreferencesCard() {
  const prefs = usePreferences();
  const me = useMe();
  const { api } = useWorkspace();
  const client = useQueryClient();
  const [saving, setSaving] = useState(false);
  const zones = useMemo(allZones, []);
  const savedZone = me.data?.preferences.timeZone ?? '';
  const savedLocale = me.data?.preferences.locale ?? '';

  async function save(changes: ProfileChanges, done: string) {
    setSaving(true);
    try {
      await api.updateProfile(changes);
      await client.invalidateQueries({ queryKey: keys.me });
      toast.success(done);
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'The preference could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
        <CardDescription>
          How times and numbers read for you, in every workspace. Leave either on “this device” to follow the browser you are using.
        </CardDescription>
      </CardHeader>
      <CardContent className='grid gap-6 sm:grid-cols-2'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='pref-time-zone'>Time zone</Label>
          {me.isLoading ? (
            <Skeleton className='h-9 w-full' />
          ) : (
            <Combobox
              items={zones}
              value={savedZone || null}
              onValueChange={(zone) => void save({ timeZone: zone ?? '' }, zone ? `Times now follow ${zoneLabel(zone)}.` : 'Times follow this device again.')}
              itemToStringLabel={(zone: string) => zoneLabel(zone)}
              disabled={saving}
            >
              <ComboboxInput id='pref-time-zone' placeholder={`This device: ${zoneLabel(prefs.browserTimeZone)}`} />
              <ComboboxContent>
                <ComboboxEmpty>No time zone matches.</ComboboxEmpty>
                <ComboboxList>{(zone: string) => <ComboboxItem key={zone} value={zone}>{zoneLabel(zone)}</ComboboxItem>}</ComboboxList>
              </ComboboxContent>
            </Combobox>
          )}
          <p className='text-muted-foreground text-xs'>
            {savedZone
              ? `Schedules and times are written in ${zoneLabel(savedZone)}.${savedZone !== prefs.browserTimeZone ? ` This device is on ${zoneLabel(prefs.browserTimeZone)}.` : ''}`
              : `Following this device: ${zoneLabel(prefs.browserTimeZone)}. Set a zone if you schedule from more than one place.`}
          </p>
        </div>

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='pref-locale'>Language for dates and numbers</Label>
          {me.isLoading ? (
            <Skeleton className='h-9 w-full' />
          ) : (
            <Select
              value={savedLocale || DEVICE}
              onValueChange={(value) => {
                const locale = value === DEVICE ? '' : (value as string);
                void save({ locale }, locale ? 'Dates and numbers now follow that language.' : 'Dates and numbers follow this device again.');
              }}
            >
              <SelectTrigger id='pref-locale' disabled={saving}>
                <SelectValue>
                  {savedLocale ? (LANGUAGES.find((item) => item.value === savedLocale)?.label ?? savedLocale) : `This device (${prefs.browserLocale})`}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEVICE}>This device ({prefs.browserLocale})</SelectItem>
                {LANGUAGES.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <p className='text-muted-foreground text-xs'>
            Changes how dates and numbers are written, for example {formatDateTime(Date.now() / 1000)}. The app&apos;s own text stays in English for now.
          </p>
        </div>

        {(savedZone || savedLocale) && (
          <Button
            variant='link'
            size='sm'
            className='w-fit px-0 sm:col-span-2'
            disabled={saving}
            onClick={() => void save({ timeZone: '', locale: '' }, 'Both preferences follow this device again.')}
          >
            Follow this device for both
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
