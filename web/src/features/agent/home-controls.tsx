'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import type { ModelCatalog } from '@/lib/api/types';
import { itemsOf } from '@/lib/content-library';
import { ContentLibraryDialog, type ContentLibraryValue } from './content-library-dialog';
import { contentChoice } from './content-choice';
import { LanguageDialog } from './language-dialog';
import { ModelDialog } from './model-dialog';
import { SettingButtons } from './setting-buttons';
import { CreditLimitField } from './credit-limit-field';
import type { DraftPlatform } from './composer';
import type { ChannelLanguages } from './use-channel-languages';
import type { useModelChoice } from './use-model';

type Choice = ReturnType<typeof useModelChoice>;
interface Props {
  languages: ChannelLanguages<DraftPlatform>;
  choice: Choice;
  catalog: ModelCatalog | undefined;
  content: ContentLibraryValue | null;
  onContent: (value: ContentLibraryValue) => void;
  channelsLabel: string;
  onChannels: () => void;
  accountLabel: (item: { platform: string; channelId?: string | null }) => string;
  voice: 'neutral' | 'personalized';
  onVoice: (value: 'neutral' | 'personalized') => void;
  voiceAvailable: boolean;
  credit?: { value: string; onChange: (value: string) => void; availableMilliCredits: number };
  sourceCount: number;
  onContext: () => void;
  onSubmit: () => void;
  disabled: boolean;
  busy: boolean;
  image: { enabled: boolean; available: boolean; onChange: (enabled: boolean) => void };
}

/** Existing v9 selectors, connected to the original composer rather than a second draft engine. */
export function HomeControls(props: Props) {
  const [panel, setPanel] = useState<'content' | 'language' | 'model' | 'voice' | null>(null);
  const [stagedVoice, setStagedVoice] = useState(props.voice);
  const libraryValue = props.content ?? { editorialId: itemsOf('editorial')[0].id, nativeId: itemsOf('native')[0].id };
  const close = (open: boolean) => { if (!open) setPanel(null); };
  const languageTags = [...new Set(props.languages.destinations.map((d) => d.language))];
  const mapping = props.content ? contentChoice(props.content) : null;
  return (
    <div className='flex min-w-0 flex-col gap-3 px-4 pb-4'>
      <div className='flex flex-wrap items-center justify-between gap-2 text-xs'>
        <Button variant='quiet' onClick={props.onContext} disabled={props.busy} className='inline-flex min-h-11 items-center gap-1.5 rounded-lg'>
          <Icons.paperclip className='size-4' /> Context {props.sourceCount > 0 ? `· ${props.sourceCount}` : ''}
        </Button>
        <Button variant='quiet' size='sm' aria-pressed={props.image.enabled} disabled={props.busy || !props.image.available} onClick={() => props.image.onChange(!props.image.enabled)}>
          <Icons.media className='size-4' /> {props.image.enabled ? 'Image on' : 'Add an image'}
        </Button>
      </div>
      <div className='rafii-glass grid grid-cols-2 gap-2 rounded-2xl p-2' role='group' aria-label='Content and channels'>
        <Button variant='quiet' className='h-auto min-h-14 justify-start whitespace-normal text-left' onClick={() => setPanel('content')} disabled={props.busy}>
          <Icons.page className='size-4 shrink-0' /> {mapping?.summary ?? 'Content type'}
        </Button>
        <Button variant='quiet' className='h-auto min-h-14 justify-start whitespace-normal text-left' onClick={props.onChannels} disabled={props.busy}>
          <Icons.broadcast className='size-4 shrink-0' /> Channels · {props.channelsLabel}
        </Button>
      </div>
      {mapping?.planningOnly && <p className='text-muted-foreground text-xs'>{mapping.planningOnly.title}: planning only. Draft format: {mapping.planningOnly.recordedFormatLabel}.</p>}
      <SettingButtons
        language={{ value: languageTags.join(' · ') || 'Choose language', onClick: () => setPanel('language'), expanded: panel === 'language', disabled: props.busy }}
        model={{ value: !props.catalog ? 'Loading models…' : props.choice.available ? props.choice.label : 'Choose an available model', onClick: () => setPanel('model'), expanded: panel === 'model', disabled: props.busy }}
        voice={{ value: props.voice === 'personalized' ? 'My writing voice' : 'Neutral', onClick: () => { setStagedVoice(props.voice); setPanel('voice'); }, expanded: panel === 'voice', disabled: props.busy }}
      />
      {props.catalog && !props.choice.available && <p role='status' className='text-muted-foreground text-sm'>This writer is unavailable. Choose another model to continue.</p>}
      {props.credit && <CreditLimitField {...props.credit} disabled={props.busy} />}
      <Button variant='action' className='min-h-14 w-full rounded-2xl text-base' onClick={props.onSubmit} disabled={props.disabled || props.busy || !props.choice.available}>
        {props.busy ? <><Icons.spinner className='size-4 animate-spin' /> Preparing drafts…</> : <>Generate drafts · {props.languages.destinations.length}</>}
      </Button>
      <ContentLibraryDialog open={panel === 'content'} onOpenChange={close} value={libraryValue} onApply={props.onContent} platformsForFit={props.languages.selectedPlatforms} />
      <LanguageDialog open={panel === 'language'} onOpenChange={close} selection={props.languages.selection} languages={props.languages} accountLabel={props.accountLabel} />
      <ModelDialog open={panel === 'model'} onOpenChange={close} catalog={props.catalog} value={{ model: props.choice.model, reasoning: props.choice.reasoningFor(props.choice.model) ?? props.choice.reasoning }} reasoningFor={props.choice.reasoningFor} onApply={(value) => { props.choice.choose(value.model); props.choice.setReasoningFor(value.model, value.reasoning); }} />
      <RafiiDialog open={panel === 'voice'} onOpenChange={close}>
        <RafiiDialogContent size='md'>
          <RafiiDialogHeader title='Writing voice' closeLabel='Close writing voice' />
          <RafiiDialogBody>
            <fieldset className='flex flex-col gap-4'><legend className='sr-only'>Writing voice</legend>
              <label className='flex min-h-11 items-center gap-3'><input type='radio' aria-label='Neutral voice' name='home-voice' checked={stagedVoice === 'neutral'} onChange={() => setStagedVoice('neutral')} /> Neutral</label>
              <label className='flex min-h-11 items-center gap-3'><input type='radio' aria-label='My writing voice' name='home-voice' checked={stagedVoice === 'personalized'} disabled={!props.voiceAvailable} onChange={() => setStagedVoice('personalized')} /> My writing voice</label>
            </fieldset>
            {!props.voiceAvailable && <Link href='/app/workspace/brand' className='inline-block py-3 text-sm underline'>Choose and approve writing samples</Link>}
          </RafiiDialogBody>
          <RafiiDialogFooter><Button variant='action' onClick={() => { props.onVoice(stagedVoice); setPanel(null); }}>Apply voice</Button></RafiiDialogFooter>
        </RafiiDialogContent>
      </RafiiDialog>
    </div>
  );
}
