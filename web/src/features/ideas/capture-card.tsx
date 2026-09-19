'use client';

import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { keys, useAct, useSnapshot, useUsage } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Snapshot } from '@/lib/api/types';
import { formatBytes } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useDraftHandoff } from './use-draft';
import { hostOf, ideaSources, LINK_PATTERN, plural, useActError } from './use-sources';

type Kind = 'idea' | 'text' | 'link' | 'file';

const KINDS: { id: Kind; label: string; icon: keyof typeof Icons }[] = [
  { id: 'idea', label: 'Idea', icon: 'bolt' },
  { id: 'text', label: 'Paste text', icon: 'text' },
  { id: 'link', label: 'Link', icon: 'link' },
  { id: 'file', label: 'File', icon: 'page' }
];

/** The `source` action's document limit (`domain.py`): UTF-8 .txt or .md, at most 20 KB. */
const MAX_FILE_BYTES = 20000;
const IDEA_LIMIT = 500;
const TEXT_LIMIT = 20000;

interface LoadedFile {
  name: string;
  text: string;
  bytes: number;
}

/** The source action refuses the same kind and text twice; a quick start may file the text under another kind. */
function existing(snap: Snapshot | undefined, item: { kind: string; text: string }, anyKind = false) {
  return ideaSources(snap?.state).find((s) => s.active && (anyKind || s.kind === item.kind) && s.text === item.text);
}

export interface CaptureCardHandle {
  focus: () => void;
}

interface CaptureCardProps {
  /** A saved (or already existing) source to open in the inspector. */
  onSelect: (sourceId: string) => void;
}

/**
 * Keeps raw material without drafting it (`source` action), or hands it straight to a
 * conversation with the same quick start Home uses. Saving never reaches a model.
 */
export const CaptureCard = forwardRef<CaptureCardHandle, CaptureCardProps>(function CaptureCard({ onSelect }, ref) {
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const usage = useUsage();
  const act = useAct();
  const onError = useActError();
  const draft = useDraftHandoff();

  const [kind, setKind] = useState<Kind>('idea');
  const [idea, setIdea] = useState('');
  const [pasted, setPasted] = useState('');
  const [pastedTitle, setPastedTitle] = useState('');
  const [url, setUrl] = useState('');
  const [linkTitle, setLinkTitle] = useState('');
  const [file, setFile] = useState<LoadedFile | null>(null);
  const [own, setOwn] = useState(true);
  const [saveState, setSaveState] = useState<ButtonState>('idle');
  const textRef = useRef<HTMLTextAreaElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({ focus: () => (kind === 'link' ? urlRef.current?.focus() : textRef.current?.focus()) }), [kind]);

  useEffect(() => {
    if (saveState !== 'success') return;
    const timer = setTimeout(() => setSaveState('idle'), 1600);
    return () => clearTimeout(timer);
  }, [saveState]);

  const revision = snapshot.data?.revision;
  const ready = revision !== undefined;
  const trimmedUrl = url.trim();
  const linkInvalid = kind === 'link' && trimmedUrl.length > 0 && !LINK_PATTERN.test(trimmedUrl);

  /** Exactly what the `source` action stores; the server trims the same way. */
  function payload(): { kind: string; text: string; title: string } | null {
    if (kind === 'idea') {
      const text = idea.trim();
      return text ? { kind: 'idea', text, title: text.slice(0, 60) } : null;
    }
    if (kind === 'text') {
      const text = pasted.trim();
      return text ? { kind: 'text', text, title: pastedTitle.trim() || 'Pasted source' } : null;
    }
    if (kind === 'link') {
      return trimmedUrl && LINK_PATTERN.test(trimmedUrl) ? { kind: 'link', text: trimmedUrl, title: linkTitle.trim() || hostOf(trimmedUrl) || 'Link' } : null;
    }
    const text = file?.text.trim();
    return file && text ? { kind: 'document', text, title: file.name } : null;
  }

  const body = payload();
  const ownApplies = kind !== 'link';

  function clear() {
    if (kind === 'idea') setIdea('');
    if (kind === 'text') {
      setPasted('');
      setPastedTitle('');
    }
    if (kind === 'link') {
      setUrl('');
      setLinkTitle('');
    }
    if (kind === 'file') {
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  /** After the API reports a duplicate this tab has not seen yet, reload and open the one it holds. */
  async function openExisting(item: { kind: string; text: string }, anyKind = false) {
    await client.refetchQueries({ queryKey: keys.snapshot(workspaceId) });
    const match = existing(client.getQueryData<Snapshot>(keys.snapshot(workspaceId)), item, anyKind);
    if (match) onSelect(match.id);
  }

  async function save() {
    const item = payload();
    const snap = snapshot.data;
    if (!item || !snap || saveState === 'loading') return;
    const duplicate = existing(snap, item);
    if (duplicate) {
      toast.info('That source is already here. It is open for review.');
      onSelect(duplicate.id);
      return;
    }
    setSaveState('loading');
    const before = new Set(ideaSources(snap.state).map((s) => s.id));
    let after: Snapshot;
    try {
      after = await act.mutateAsync({ revision: snap.revision, action: 'source', payload: item });
    } catch (err) {
      setSaveState('idle');
      onError(err, 'The source could not be saved.');
      if (err instanceof ApiError && /already here/i.test(err.message)) void openExisting(item);
      return;
    }
    const created = ideaSources(after.state).find((s) => !before.has(s.id));
    if (created) {
      try {
        if (item.kind !== 'link' && item.kind !== 'idea' && own) {
          // Your own text: quotable, every sentence approved (what a quick start does for own content).
          after = await act.mutateAsync({ revision: after.revision, action: 'source_policy', payload: { sourceId: created.id, policy: 'public_quote', egressConsent: ['local'], confirmed: true } });
          if (created.facts.length > 0) {
            after = await act.mutateAsync({ revision: after.revision, action: 'approve_source', payload: { sourceId: created.id, factIds: created.facts.map((f) => f.id) } });
          }
        } else if (item.kind === 'idea' && !own) {
          after = await act.mutateAsync({ revision: after.revision, action: 'source_policy', payload: { sourceId: created.id, policy: 'rewrite_approval', egressConsent: ['local'], confirmed: true } });
        }
      } catch (err) {
        onError(err, 'Saved, but how it may be used could not be set. Set it in the inspector.');
      }
      onSelect(created.id);
    }
    clear();
    setSaveState('success');
  }

  async function draftNow() {
    const item = payload();
    if (!item) return;
    const started =
      item.kind === 'link'
        ? await draft.quickStart({ url: item.text, title: item.title, ownContent: false })
        : await draft.quickStart({ text: item.text, title: item.kind === 'idea' ? undefined : item.title, ownContent: own });
    if (!started) void openExisting(item, true);
  }

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0];
    if (!picked) return;
    const reset = () => {
      event.target.value = '';
      setFile(null);
    };
    if (!/\.(txt|md)$/i.test(picked.name)) {
      toast.error('Only .txt and .md files can be added. Export other documents as plain text first.');
      return reset();
    }
    if (picked.size > MAX_FILE_BYTES) {
      toast.error(`${picked.name} is ${formatBytes(picked.size)}. Files can be at most 20 KB of UTF-8 text.`);
      return reset();
    }
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await picked.arrayBuffer());
      if (!text.trim()) {
        toast.error(`${picked.name} is empty.`);
        return reset();
      }
      setFile({ name: picked.name, text, bytes: picked.size });
    } catch {
      toast.error(`${picked.name} is not UTF-8 text.`);
      reset();
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void save();
    }
  }

  const batches = usage.isLoading ? '…' : usage.isError || !usage.data ? 'Unavailable' : String(usage.data.entitlement.writingBatchesRemaining);

  return (
    <Card data-tour='ideas-capture'>
      <CardHeader className='gap-3'>
        <div className='flex flex-col gap-1'>
          <CardTitle className='text-base'>Capture</CardTitle>
          <CardDescription>Saving keeps it here. Nothing is drafted, sent to a model or published until you ask.</CardDescription>
        </div>
        <div className='scrollbar-hide -mx-1 overflow-x-auto px-1'>
          <Tabs value={kind} onValueChange={(value) => setKind(value as Kind)} variant='pill'>
            <TabsList aria-label='What to capture' className='bg-muted/60 w-max'>
              {KINDS.map((item) => {
                const Icon = Icons[item.icon];
                return (
                  <TabsTrigger key={item.id} value={item.id} className='h-8 gap-1 px-2.5 py-0 text-xs sm:gap-1.5 sm:px-3 sm:text-sm'>
                    <Icon className='size-3.5' />
                    {item.label}
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        {kind === 'idea' && (
          <Textarea
            ref={textRef}
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            maxLength={IDEA_LIMIT}
            aria-label='Your idea'
            placeholder='e.g. The thing I keep noticing about first-time customers…'
            className='max-h-48'
          />
        )}
        {kind === 'text' && (
          <>
            <Textarea
              ref={textRef}
              value={pasted}
              onChange={(event) => setPasted(event.target.value)}
              onKeyDown={onKeyDown}
              rows={6}
              maxLength={TEXT_LIMIT}
              aria-label='Text to keep'
              placeholder='Paste notes, an article excerpt or a transcript. Each paragraph becomes a fact you can approve.'
              className='max-h-72'
            />
            <Input value={pastedTitle} onChange={(event) => setPastedTitle(event.target.value)} onKeyDown={onKeyDown} maxLength={200} aria-label='Title' placeholder='Title (optional) · Pasted source' />
          </>
        )}
        {kind === 'link' && (
          <>
            <div className='flex flex-col gap-1'>
              <Input
                ref={urlRef}
                type='url'
                inputMode='url'
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                onKeyDown={onKeyDown}
                maxLength={2000}
                aria-label='Link'
                aria-invalid={linkInvalid || undefined}
                placeholder='https://…'
              />
              <p className={linkInvalid ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
                {linkInvalid ? 'Use a full http or https address.' : 'Saved as an unverified reference: the page itself is not read when you save.'}
              </p>
            </div>
            <Input value={linkTitle} onChange={(event) => setLinkTitle(event.target.value)} onKeyDown={onKeyDown} maxLength={200} aria-label='Title' placeholder='Title (optional) · the site name' />
          </>
        )}
        {kind === 'file' && (
          <div className='flex flex-col gap-2'>
            <Label htmlFor='ideas-file' className='text-muted-foreground text-xs font-normal'>
              A UTF-8 .txt or .md file, up to 20 KB. Each paragraph becomes a fact you can approve.
            </Label>
            <input
              id='ideas-file'
              ref={fileRef}
              type='file'
              aria-label='File to add'
              accept='.txt,.md,text/plain,text/markdown'
              onChange={(event) => void readFile(event)}
              className='file:bg-muted file:text-foreground text-muted-foreground w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border-0 file:px-3 file:py-1.5 file:text-sm file:font-medium'
            />
            {file && (
              <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 text-xs'>
                <Icons.page className='size-3.5' />
                <span className='text-foreground font-medium'>{file.name}</span>
                <span>{formatBytes(file.bytes)}</span>
                <span>· {plural(file.text.split(/\n+/).filter((line) => line.trim()).length, 'paragraph')}</span>
              </p>
            )}
          </div>
        )}

        {ownApplies && (
          <Checkbox
            checked={own}
            onCheckedChange={setOwn}
            label={kind === 'idea' ? 'My own words (may be quoted publicly)' : 'My own writing (quotable, every paragraph approved)'}
          />
        )}

        <div className='flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between'>
          <p className='text-muted-foreground text-xs sm:max-w-sm'>
            Draft now opens a conversation · {draft.modelLabel} · for {draft.destinationLabel} · {batches === 'Unavailable' ? 'writing allowance unavailable' : `${batches} writing batches left`}
          </p>
          <div className='flex flex-wrap items-center gap-2'>
            <StatefulButton variant='outline' state={draft.busy ? 'loading' : 'idle'} loadingText='Starting…' disabled={!ready || !body || saveState === 'loading'} onClick={() => void draftNow()}>
              Draft now
            </StatefulButton>
            <StatefulButton state={saveState} loadingText='Saving…' successText='Saved' disabled={!ready || (!body && saveState === 'idle') || draft.busy} onClick={() => void save()}>
              Save to ideas
            </StatefulButton>
          </div>
        </div>
        <p className='text-muted-foreground -mt-1 hidden text-[11px] sm:block'>⌘↵ saves</p>
      </CardContent>
    </Card>
  );
});
