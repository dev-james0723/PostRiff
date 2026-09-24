'use client';

import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { SegmentedControl, Surface } from '@/components/rafii';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { keys, useAct, useSnapshot, useUsage } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Snapshot } from '@/lib/api/types';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
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

/* Borderless Rafii text entry (DNA §11.1): 16px on phones, the field fill, the control radius. */
const FIELD = 'rafii-field rounded-[var(--rafii-radius-control)] border-0 bg-(--rafii-surface-field) dark:bg-(--rafii-surface-field) px-4 text-base md:text-sm';
const FIELD_INPUT = cn(FIELD, 'h-12');
const FIELD_AREA = cn(FIELD, 'py-3 leading-relaxed');
/* The one dominant commitment action, and its quiet-glass secondary (DNA §10.1–10.2), on the motion buttons. */
const ACTION = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent hover:brightness-[1.06]';
const GLASS = 'rafii-glass hover:rafii-glass-selected text-foreground hover:text-foreground h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent';

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
    // The page's work surface (DNA §5.2, §21.10): one glass panel, its WHAT control, the entry field and one commitment.
    <Surface as='section' material='glass' radius='card' padding='lg' data-tour='ideas-capture' aria-labelledby='ideas-capture-title' className='flex flex-col gap-4'>
      <div className='flex flex-col gap-3'>
        <div className='flex flex-col gap-1'>
          <h2 id='ideas-capture-title' className='text-foreground text-base font-medium'>
            Capture
          </h2>
          <p className='text-muted-foreground text-sm leading-relaxed'>Saving keeps it here. Nothing is drafted, sent to a model or published until you ask.</p>
        </div>
        <div className='relative scrollbar-hide -mx-1 overflow-x-auto px-1 py-0.5'>
          <SegmentedControl
            label='What to capture'
            value={kind}
            onChange={setKind}
            widths='content'
            options={KINDS.map((item) => {
              const Icon = Icons[item.icon];
              return {
                value: item.id,
                label: (
                  <>
                    <Icon aria-hidden className='size-4' />
                    {item.label}
                  </>
                )
              };
            })}
          />
        </div>
      </div>
      <div className='flex flex-col gap-3'>
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
            className={cn(FIELD_AREA, 'max-h-48')}
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
              className={cn(FIELD_AREA, 'max-h-72')}
            />
            <Input value={pastedTitle} onChange={(event) => setPastedTitle(event.target.value)} onKeyDown={onKeyDown} maxLength={200} aria-label='Title' placeholder='Title (optional) · Pasted source' className={FIELD_INPUT} />
          </>
        )}
        {kind === 'link' && (
          <>
            <div className='flex flex-col gap-1.5'>
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
                className={FIELD_INPUT}
              />
              <p className={linkInvalid ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
                {linkInvalid ? 'Use a full http or https address.' : 'Saved as an unverified reference: the page itself is not read when you save.'}
              </p>
            </div>
            <Input value={linkTitle} onChange={(event) => setLinkTitle(event.target.value)} onKeyDown={onKeyDown} maxLength={200} aria-label='Title' placeholder='Title (optional) · the site name' className={FIELD_INPUT} />
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
              className={cn(
                FIELD,
                'rafii-focus text-muted-foreground flex min-h-12 w-full min-w-0 items-center py-2 text-sm file:mr-3 file:rounded-[var(--rafii-radius-micro)] file:border-0 file:bg-foreground/10 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-foreground'
              )}
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

        {/* An explicit permission checkbox with its own label (DNA §10.6): quoting is never pre-enabled for text that is not yours. */}
        {ownApplies && (
          <Checkbox
            checked={own}
            onCheckedChange={setOwn}
            className='min-h-11'
            label={kind === 'idea' ? 'My own words (may be quoted publicly)' : 'My own writing (quotable, every paragraph approved)'}
          />
        )}

        <div className='flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between'>
          <p className='text-muted-foreground min-w-0 text-xs leading-relaxed sm:max-w-sm'>
            Draft now opens a conversation · {draft.modelLabel} · for {draft.destinationLabel} · {batches === 'Unavailable' ? 'writing allowance unavailable' : `${batches} writing batches left`}
          </p>
          <div className='flex flex-wrap items-center gap-2 sm:shrink-0'>
            <StatefulButton variant='ghost' className={GLASS} state={draft.busy ? 'loading' : 'idle'} loadingText='Starting…' disabled={!ready || !body || saveState === 'loading'} onClick={() => void draftNow()}>
              Draft now
            </StatefulButton>
            <StatefulButton className={ACTION} state={saveState} loadingText='Saving…' successText='Saved' disabled={!ready || (!body && saveState === 'idle') || draft.busy} onClick={() => void save()}>
              Save to ideas
            </StatefulButton>
          </div>
        </div>
        <p className='text-muted-foreground -mt-1 hidden text-xs sm:block'>⌘↵ saves</p>
      </div>
    </Surface>
  );
});
