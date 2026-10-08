'use client';

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import type { CollectionDefinition, CollectionPreview, CollectionWriteResult, SmartRule } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import {
  RULE_CAPABILITIES,
  RULE_CAPABILITY_STATES,
  RULE_FIELDS,
  RULE_KINDS,
  RULE_ORIENTATIONS,
  RULE_SOURCE_KINDS,
  buildRule,
  defaultRow,
  draftFromRule,
  opsFor,
  originLabel,
  parseList,
  previewSummary,
  saveEnvelope,
  undoEnvelope,
  validateRow,
  valueTypeOf,
  type RuleDraft,
  type RuleRow
} from '@/lib/library/smart-rules';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function localZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

const KIND_WORDS: Record<string, string> = { image: 'Photos', video: 'Videos', audio: 'Audio', document: 'Documents', file: 'Other files' };
const SOURCE_WORDS: Record<string, string> = { upload: 'Uploads', link: 'Saved links', note: 'Notes', artifact: 'Rafii outputs' };
const STATE_WORDS: Record<string, string> = {
  not_requested: 'Not requested',
  queued: 'Queued',
  processing: 'In progress',
  ready: 'Ready',
  partial: 'Partly ready',
  unsupported: 'Not available for the file',
  failed: 'Failed',
  cancelled: 'Cancelled',
  blocked_permission: 'Needs permission',
  blocked_budget: 'Paused by the usage limit'
};
const CAPABILITY_WORDS: Record<string, string> = {
  preview: 'Preview',
  extract: 'Text',
  transcribe: 'Transcript',
  visual: 'Visual description',
  embed_text: 'Meaning search',
  embed_visual: 'Visual search',
  understand: 'Summary'
};

/** The collection's definition, history and whether undo is possible. Polls while membership is being re-evaluated. */
export function useCollectionDetail(collectionId: string | null, enabled: boolean) {
  const { api, workspaceId } = useWorkspaceApi();
  return useQuery({
    queryKey: ['library-collection', workspaceId, collectionId],
    queryFn: () => api.libraryCollection(workspaceId, collectionId ?? ''),
    enabled: Boolean(workspaceId && collectionId && enabled),
    retry: false,
    refetchInterval: (query) => (query.state.data && !query.state.data.collection.evaluationCurrent ? 4000 : false)
  });
}

type SendResult = { ok: true; result: CollectionWriteResult; warnings: string[] } | { ok: false; status: string; message: string };

function useCollectionAction() {
  const { api, workspaceId } = useWorkspaceApi();
  return async (envelope: ReturnType<typeof saveEnvelope>, key: string): Promise<SendResult> => {
    try {
      const response = await api.libraryAction<CollectionWriteResult>(workspaceId, { ...envelope, idempotencyKey: key });
      if (response.status === 'applied' && response.result) return { ok: true, result: response.result, warnings: response.warnings ?? [] };
      const message =
        response.status === 'conflict'
          ? response.warnings?.[0] || 'This collection changed since you opened it. Reload it and try again.'
          : response.status === 'denied'
            ? response.warnings?.[0] || 'Not allowed for your role.'
            : response.warnings?.[0] || 'This needs confirmation first.';
      return { ok: false, status: response.status, message };
    } catch (error) {
      const status = error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed';
      return { ok: false, status, message: error instanceof Error ? error.message : 'The collection wasn’t saved.' };
    }
  };
}

function CheckGroup({ legend, options, words, value, onChange }: { legend: string; options: readonly string[]; words: Record<string, string>; value: unknown; onChange: (next: string[]) => void }) {
  const chosen = Array.isArray(value) ? (value as string[]) : [];
  return (
    <fieldset className='flex flex-wrap gap-x-3 gap-y-1'>
      <legend className='sr-only'>{legend}</legend>
      {options.map((option) => (
        <label key={option} className='flex min-h-11 items-center gap-2 text-sm'>
          <input
            type='checkbox'
            aria-label={words[option] ?? option}
            checked={chosen.includes(option)}
            onChange={(event) => onChange(event.target.checked ? [...chosen, option] : chosen.filter((item) => item !== option))}
            className='accent-foreground size-4'
          />
          {words[option] ?? option}
        </label>
      ))}
    </fieldset>
  );
}

/** One criterion: an allowlisted field, an allowlisted operator and a value editor for that type. No free-form query. */
function RuleRowEditor({ row, index, onChange, onRemove }: { row: RuleRow; index: number; onChange: (row: RuleRow) => void; onRemove: () => void }) {
  const id = useId();
  const type = valueTypeOf(row.field, row.op);
  const problem = validateRow(row);
  const field = RULE_FIELDS[row.field];
  const label = `Criterion ${index + 1}`;
  const select = 'rafii-field rafii-focus h-11 rounded-[var(--rafii-radius-control)] px-3 text-sm';
  let editor: ReactNode = null;
  if (type === 'kinds') editor = <CheckGroup legend={`${label} types`} options={RULE_KINDS} words={KIND_WORDS} value={row.value} onChange={(value) => onChange({ ...row, value })} />;
  else if (type === 'source_kinds') editor = <CheckGroup legend={`${label} sources`} options={RULE_SOURCE_KINDS} words={SOURCE_WORDS} value={row.value} onChange={(value) => onChange({ ...row, value })} />;
  else if (type === 'states')
    editor = (
      <div className='flex flex-col gap-1'>
        <label htmlFor={`${id}-cap`} className='text-xs'>
          Step
          <select id={`${id}-cap`} aria-label={`${label} step`} value={row.capability ?? 'transcribe'} onChange={(event) => onChange({ ...row, capability: event.target.value as RuleRow['capability'] })} className={cn(select, 'ml-2')}>
            {RULE_CAPABILITIES.map((capability) => (
              <option key={capability} value={capability}>
                {CAPABILITY_WORDS[capability]}
              </option>
            ))}
          </select>
        </label>
        <CheckGroup legend={`${label} states`} options={RULE_CAPABILITY_STATES} words={STATE_WORDS} value={row.value} onChange={(value) => onChange({ ...row, value })} />
      </div>
    );
  else if (type === 'tags' || type === 'languages')
    editor = (
      <Input
        aria-label={`${label} ${type === 'tags' ? 'tags' : 'language codes'}, separated by commas`}
        defaultValue={Array.isArray(row.value) ? (row.value as string[]).join(', ') : ''}
        onChange={(event) => onChange({ ...row, value: parseList(event.target.value) })}
        placeholder={type === 'tags' ? 'recital, rehearsal' : 'yue, zh-Hant, en'}
        className='h-11'
      />
    );
  else if (type === 'date')
    editor = (
      <span className='flex flex-wrap items-center gap-2 text-xs'>
        <Input type='date' aria-label={`${label} date`} value={typeof row.value === 'string' ? row.value : ''} onChange={(event) => onChange({ ...row, value: event.target.value })} className='h-11 w-auto' />
        <span className='text-muted-foreground'>in {row.timeZone ?? 'UTC'} time</span>
      </span>
    );
  else if (type === 'ms')
    editor = (
      <span className='flex items-center gap-2 text-xs'>
        <Input
          type='number'
          min={0}
          max={86400}
          aria-label={`${label} length in seconds`}
          value={typeof row.value === 'number' ? Math.round(row.value / 1000) : 0}
          onChange={(event) => onChange({ ...row, value: Math.max(0, Math.round(Number(event.target.value) || 0)) * 1000 })}
          className='h-11 w-28'
        />
        seconds
      </span>
    );
  else if (type === 'orientation' || type === 'usage')
    editor = (
      <select aria-label={`${label} value`} value={String(row.value)} onChange={(event) => onChange({ ...row, value: event.target.value })} className={select}>
        {(type === 'orientation' ? RULE_ORIENTATIONS : ['unused', 'used']).map((option) => (
          <option key={option} value={option}>
            {option[0].toUpperCase() + option.slice(1)}
          </option>
        ))}
      </select>
    );
  else if (type)
    editor = (
      <Input
        aria-label={`${label} ${type === 'mime' ? 'content type' : 'words'}`}
        value={typeof row.value === 'string' ? row.value : ''}
        maxLength={type === 'text200' ? 200 : type === 'tag' ? 40 : 120}
        onChange={(event) => onChange({ ...row, value: event.target.value })}
        placeholder={type === 'mime' ? 'audio/' : ''}
        className='h-11'
      />
    );
  return (
    <li className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <select
          aria-label={`${label} field`}
          value={row.field}
          onChange={(event) => onChange(defaultRow(event.target.value, row.timeZone ?? localZone()))}
          className={select}
        >
          {Object.entries(RULE_FIELDS).map(([name, entry]) => (
            <option key={name} value={name}>
              {name === 'created_after' ? 'Added on or after' : name === 'created_before' ? 'Added before' : entry.label}
            </option>
          ))}
        </select>
        {opsFor(row.field).length > 1 ? (
          <select aria-label={`${label} match`} value={row.op} onChange={(event) => onChange({ ...row, op: event.target.value, value: defaultRow(row.field).value })} className={select}>
            {opsFor(row.field).map((op) => (
              <option key={op} value={op}>
                {field?.ops[op]?.label ?? op}
              </option>
            ))}
          </select>
        ) : (
          <span className='text-muted-foreground text-sm'>{field?.ops[row.op]?.label}</span>
        )}
        {row.field === 'tag' ? (
          <select aria-label={`${label} whose tags`} value={row.origin ?? 'user'} onChange={(event) => onChange({ ...row, origin: event.target.value as RuleRow['origin'] })} className={select}>
            <option value='user'>Your tags</option>
            <option value='ai_suggested'>AI-suggested tags</option>
            <option value='any'>Either</option>
          </select>
        ) : null}
        <Button variant='quiet' size='icon-control' className='ml-auto' aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>
          <Icons.close aria-hidden />
        </Button>
      </div>
      {editor}
      {problem ? <p className='text-muted-foreground text-xs'>{problem}</p> : null}
    </li>
  );
}

/**
 * Create or edit a smart collection: allowlisted criteria, the server's plain-language explanation, a before/after
 * membership preview, and a save that names the revision it was edited from.
 */
export function SmartCollectionDialog({
  open,
  onOpenChange,
  existing,
  onSaved,
  onAnnounce
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: CollectionDefinition | null;
  onSaved: (collectionId: string) => void;
  onAnnounce: (message: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const send = useCollectionAction();
  const id = useId();
  const zone = useMemo(localZone, []);
  const initial = useMemo<RuleDraft>(() => (existing?.rule ? draftFromRule(existing.rule) : null) ?? { join: 'all', rows: [defaultRow('kind', zone)] }, [existing, zone]);
  const nested = Boolean(existing?.rule) && !draftFromRule(existing?.rule);
  const [name, setName] = useState(existing?.name ?? '');
  const [draft, setDraft] = useState<RuleDraft>(initial);
  const [preview, setPreview] = useState<{ digest: string; result: CollectionPreview } | null>(null);
  const [busy, setBusy] = useState<'preview' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const saveKey = useRef<{ digest: string; key: string } | null>(null);

  // A fresh form each time the dialog opens; background refreshes of the collection never reset an edit in progress.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setName(existing?.name ?? '');
      setDraft(initial);
      setPreview(null);
      setError(null);
      setConflict(false);
    }
    wasOpen.current = open;
  }, [open, existing, initial]);

  const built = buildRule(draft);
  const digest = built.ok ? JSON.stringify(built.rule) : '';
  const previewCurrent = Boolean(preview && preview.digest === digest);

  async function runPreview() {
    if (!built.ok) {
      setError(built.errors[0]);
      return;
    }
    setBusy('preview');
    setError(null);
    try {
      const result = await api.libraryCollectionPreview(workspaceId, { rule: built.rule as SmartRule, ...(existing ? { collectionId: existing.id } : {}), limit: 12 });
      setPreview({ digest, result });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The preview didn’t load.');
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!built.ok || !previewCurrent) return;
    if (!existing && !name.trim()) {
      setError('Name the collection first.');
      return;
    }
    const request = saveEnvelope(built.rule, { name: existing ? undefined : name.trim(), collectionId: existing?.id ?? null, revision: existing?.revision ?? null, actionId: `save-${Date.now()}` });
    const requestDigest = JSON.stringify([request.payload, request.expectedRevision]);
    if (!saveKey.current || saveKey.current.digest !== requestDigest) saveKey.current = { digest: requestDigest, key: newIdempotencyKey('lib-smart', randomKey) };
    setBusy('save');
    setError(null);
    const outcome = await send(request, saveKey.current.key);
    setBusy(null);
    if (!outcome.ok) {
      setConflict(outcome.status === 'conflict');
      setError(outcome.message);
      return;
    }
    saveKey.current = null;
    await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] });
    await client.invalidateQueries({ queryKey: ['library-collection', workspaceId, outcome.result.collection.id] });
    await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
    const changes = outcome.result.changes;
    onAnnounce(`${outcome.result.collection.name} saved${changes ? `: ${changes.added} joined, ${changes.removed} left` : ''}.`);
    onSaved(outcome.result.collection.id);
    onOpenChange(false);
  }

  const summary = preview ? previewSummary(preview.result) : null;
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='lg'>
        <RafiiDialogHeader
          title={existing ? `Edit “${existing.name}”` : 'New smart collection'}
          intro='Pick criteria from the list. Rafii explains them in words and shows who joins and leaves before anything is saved. Items are referenced, never copied.'
        />
        <RafiiDialogBody className='flex flex-col gap-4'>
          {!existing ? (
            <label htmlFor={`${id}-name`} className='flex flex-col gap-1.5 text-sm font-medium'>
              Name
              <Input id={`${id}-name`} value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className='h-11 font-normal' />
            </label>
          ) : null}
          {nested ? <StateMessage kind='partial' layout='inline' title='These criteria use nested groups' description='They stay as saved unless you replace them here with a simple list.' /> : null}
          <label htmlFor={`${id}-join`} className='flex flex-wrap items-center gap-2 text-sm'>
            Include items that match
            <select id={`${id}-join`} value={draft.join} onChange={(event) => setDraft({ ...draft, join: event.target.value === 'any' ? 'any' : 'all' })} className='rafii-field rafii-focus h-11 rounded-[var(--rafii-radius-control)] px-3 text-sm'>
              <option value='all'>all of these</option>
              <option value='any'>any of these</option>
            </select>
          </label>
          <ul className='flex flex-col gap-2' aria-label='Criteria'>
            {draft.rows.map((row, index) => (
              <RuleRowEditor
                key={index}
                row={row}
                index={index}
                onChange={(next) => setDraft({ ...draft, rows: draft.rows.map((item, position) => (position === index ? next : item)) })}
                onRemove={() => setDraft({ ...draft, rows: draft.rows.filter((_, position) => position !== index) })}
              />
            ))}
          </ul>
          <Button variant='glass' size='control' className='self-start' disabled={draft.rows.length >= 40} onClick={() => setDraft({ ...draft, rows: [...draft.rows, defaultRow('tag', zone)] })}>
            <Icons.add aria-hidden />
            Add criterion
          </Button>
          {preview ? (
            <section aria-label='Preview' className='flex flex-col gap-2'>
              <p className='text-sm'>
                <span className='text-muted-foreground'>Rafii reads this as: </span>
                {preview.result.explanation}
              </p>
              {summary ? <p className='text-sm font-medium'>{summary.line}</p> : null}
              {!previewCurrent ? <p className='text-muted-foreground text-xs'>The criteria changed since this preview. Preview again before saving.</p> : null}
              {preview.result.members.length ? (
                <ul className='flex flex-col gap-1 text-sm'>
                  {preview.result.members.map((member) => (
                    <li key={`${member.assetRef.assetId}:${member.assetRef.versionId}`} className='flex flex-wrap items-baseline justify-between gap-x-3'>
                      <span className='min-w-0 truncate'>{member.title}</span>
                      <span className='text-muted-foreground text-xs'>{originLabel(member.origin)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className='text-muted-foreground text-sm'>No item matches these criteria right now.</p>
              )}
              {preview.result.warnings.map((warning) => (
                <p key={warning} className='text-muted-foreground text-xs'>
                  {warning}
                </p>
              ))}
            </section>
          ) : null}
          {error ? (
            <p role='alert' className='text-destructive text-sm'>
              {error}
            </p>
          ) : null}
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row flex-wrap justify-end'>
          {conflict && existing ? (
            <Button
              variant='glass'
              size='control'
              onClick={() => {
                void client.invalidateQueries({ queryKey: ['library-collection', workspaceId, existing.id] });
                onOpenChange(false);
              }}
            >
              Reload collection
            </Button>
          ) : null}
          <Button variant='glass' size='control' disabled={busy !== null} onClick={() => void runPreview()}>
            {busy === 'preview' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            Preview
          </Button>
          <Button variant='action' size='control' disabled={busy !== null || !previewCurrent} onClick={() => void save()}>
            {busy === 'save' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            {existing ? 'Save criteria' : 'Create collection'}
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/** The active smart collection: what it holds in words, whether membership is still updating, edit and undo. */
export function SmartCollectionPanel({ collectionId, canEdit, enabled, onAnnounce }: { collectionId: string; canEdit: boolean; enabled: boolean; onAnnounce: (message: string) => void }) {
  const { workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const detail = useCollectionDetail(collectionId, enabled);
  const send = useCollectionAction();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const undoKey = useRef<{ revision: number; key: string } | null>(null);
  if (!enabled) return null;
  if (detail.isPending) return <p className='text-muted-foreground text-xs'>Loading the collection’s criteria…</p>;
  if (detail.isError || !detail.data) return <p className='text-muted-foreground text-xs'>This collection’s criteria couldn’t load. Its items are shown as last saved.</p>;
  const { collection, history, canUndo } = detail.data;
  if (collection.kind !== 'smart') return null;
  const last = history[0];

  async function undo() {
    if (!undoKey.current || undoKey.current.revision !== collection.revision) undoKey.current = { revision: collection.revision, key: newIdempotencyKey('lib-undo', randomKey) };
    setBusy(true);
    setMessage(null);
    const outcome = await send(undoEnvelope(collection.id, collection.revision, `undo-${Date.now()}`), undoKey.current.key);
    setBusy(false);
    if (!outcome.ok) {
      setMessage(outcome.message);
      if (outcome.status === 'conflict') void detail.refetch();
      return;
    }
    undoKey.current = null;
    await client.invalidateQueries({ queryKey: ['library-collection', workspaceId, collection.id] });
    await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] });
    await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
    const text = ['Restored the previous criteria.', ...outcome.warnings].join(' ');
    setMessage(text);
    onAnnounce(text);
  }

  return (
    <section aria-label={`About ${collection.name}`} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3'>
      <div className='flex flex-wrap items-start gap-2'>
        <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
          <p className='flex items-center gap-1.5 text-sm font-medium'>
            <Icons.sparkles className='size-4' aria-hidden />
            Smart collection
          </p>
          <p className='text-sm'>{collection.explanation}</p>
          <p className='text-muted-foreground text-xs'>
            {collection.memberCount.toLocaleString('en-US')} {collection.memberCount === 1 ? 'item' : 'items'}
            {collection.overrides.include ? ` · ${collection.overrides.include} included by you` : ''}
            {collection.overrides.exclude ? ` · ${collection.overrides.exclude} excluded by you` : ''}
            {last?.createdAt ? ` · changed ${relativeTime(last.createdAt)}${last.byYou ? ' by you' : ''}` : ''}
          </p>
          {!collection.evaluationCurrent ? (
            <p role='status' className='flex items-center gap-1.5 text-xs font-medium'>
              <Icons.spinner className='size-3.5 animate-spin motion-reduce:animate-none' aria-hidden />
              Re-evaluating membership…
            </p>
          ) : null}
        </div>
        {canEdit ? (
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' size='control' className='h-11' onClick={() => setEditing(true)}>
              Edit criteria
            </Button>
            {canUndo ? (
              <Button variant='quiet' size='control' className='h-11' disabled={busy} onClick={() => void undo()}>
                {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
                Undo last change
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      {message ? <p className='text-muted-foreground text-xs'>{message}</p> : null}
      <SmartCollectionDialog open={editing} onOpenChange={setEditing} existing={collection} onSaved={() => undefined} onAnnounce={onAnnounce} />
    </section>
  );
}
