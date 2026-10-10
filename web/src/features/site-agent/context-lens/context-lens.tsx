'use client';

/**
 * Context Lens chips (Agent Experience P1.1) above the Rafii panel's composer: exactly what the next typed message will use,
 * as the server resolved it (`POST /agent/context-lens`). Each chip opens its details (where it comes from, why it is there,
 * when it was checked) and, when the person may, removes it from the next message; the removal travels with the message as
 * `contextLens.exclude` and is honoured on the server. Shown only when the server reports the lens on for this workspace.
 *
 * Keyboard: every chip and its remove control are buttons; Escape closes the open details and returns focus to its chip.
 * Screen readers: the list is labelled, each chip says when it won't be used, and removals are announced politely.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import type { AgentApi } from '@/lib/agent-runtime/client';
import { cn } from '@/lib/utils';
import { currentPageContext } from '../use-page-context';
import type { PanelState } from '../store';
import { checkedLine, chipLabel, chips, noSelection, previewBody, statusLine, t, used, whyLine, type LensItem, type LensLanguage, type LensPreview } from './model';

type IconName = keyof typeof Icons;

const ICON: Record<string, IconName> = {
  workspace: 'workspace',
  page: 'page',
  selection: 'check',
  screen: 'eye',
  visible_state: 'adjustments',
  reference: 'link',
  attachment: 'media',
  view_selection: 'listCheck',
  conversation: 'chat',
  work: 'listDetails',
  style: 'sparkles'
};

/** Chips shown before "N more". */
const VISIBLE = 4;

function useDebounced<T>(value: T, ms: number): T {
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setCurrent(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return current;
}

/**
 * The preview for the panel as it is now: refetched when the page, its selection, the conversation or the attached images
 * change, and again when it expires. Never sent the message being typed.
 */
export function useContextLensPreview({ enabled, api, workspaceId, conversationId, pathname, page, images, ttlSeconds }: {
  enabled: boolean;
  api: AgentApi;
  workspaceId: string | null | undefined;
  conversationId: string | null;
  pathname: string;
  page: PanelState['page'];
  images: readonly { assetId: string }[];
  ttlSeconds: number;
}) {
  const key = useDebounced(JSON.stringify([pathname, page ?? null, conversationId, images.map((image) => image.assetId)]), 250);
  const ttl = Math.max(30, ttlSeconds) * 1000;
  return useQuery({
    queryKey: ['agent-runtime', 'context-lens', workspaceId ?? null, key],
    queryFn: ({ signal }) => api.contextLens(workspaceId as string, previewBody({ conversationId, pageContext: currentPageContext(pathname), attachments: images }), signal),
    enabled: enabled && Boolean(workspaceId),
    staleTime: ttl,
    refetchInterval: enabled ? ttl : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
    retry: 1
  });
}

export function ContextLens({ preview, loading, failed, onRetry, removed, onToggle, text, lang, timeZone, onNewConversation }: {
  preview: LensPreview | null;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  removed: ReadonlySet<string>;
  onToggle: (item: LensItem) => void;
  /** What is being typed (stays in the browser): only to say "No item selected" when it points at "this". */
  text: string;
  lang: LensLanguage;
  timeZone?: string;
  onNewConversation?: () => void;
}) {
  const base = useId();
  const [open, setOpen] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const chipButtons = useRef(new Map<string, HTMLButtonElement>());
  const details = useRef<HTMLDivElement>(null);
  const list = useMemo(() => chips(preview, removed), [preview, removed]);
  const shown = expanded ? list : list.slice(0, VISIBLE);
  const hidden = list.length - shown.length;
  const openItem = list.find((item) => item.id === open) ?? null;
  const detailsId = `${base}-details`;
  const missing = noSelection(preview, text, removed);

  // An item that left the preview (another page, another conversation) closes its details.
  useEffect(() => {
    if (open && !list.some((item) => item.id === open)) setOpen(null);
  }, [list, open]);

  const close = useCallback(() => {
    const id = open;
    setOpen(null);
    if (id) requestAnimationFrame(() => chipButtons.current.get(id)?.focus());
  }, [open]);

  // Escape closes the open details from its chip or anywhere inside them, and nothing else (not the sheet holding the panel).
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const target = event.target as Node | null;
      const inside = (target && details.current?.contains(target)) || target === chipButtons.current.get(open);
      if (!inside) return;
      event.stopPropagation();
      close();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [close, open]);

  const toggle = (item: LensItem) => {
    const label = chipLabel(item, lang);
    setAnnouncement(t(removed.has(item.id) ? 'restoredNow' : 'removedNow', lang, { label }));
    onToggle(item);
  };

  if (!preview && !loading && !failed) return null;
  return (
    <section aria-label={t('region', lang)} data-rafii-context-lens className='mb-2 px-1'>
      <ul className='flex flex-wrap items-center gap-1.5'>
        {!preview && loading && (
          <li className='text-muted-foreground text-xs'>
            <span role='status'>{t('checking', lang)}</span>
          </li>
        )}
        {!preview && failed && (
          <li className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
            <span role='status'>{t('failed', lang)}</span>
            <Button type='button' variant='quiet' size='xs' onClick={onRetry}>{t('retry', lang)}</Button>
          </li>
        )}
        {shown.map((item, index) => {
          const label = chipLabel(item, lang);
          const active = used(item, removed);
          const removedHere = removed.has(item.id);
          const Icon = Icons[ICON[item.kind] ?? 'circle'];
          return (
            <li key={item.id} data-lens-kind={item.kind} data-lens-status={removedHere ? 'removed' : item.status}
              className={cn('inline-flex max-w-full min-w-0 items-center rounded-full border text-xs', active ? 'border-border bg-background/60' : 'border-dashed border-border/70 text-muted-foreground')}>
              <button type='button' ref={(node) => { if (node) chipButtons.current.set(item.id, node); else chipButtons.current.delete(item.id); }}
                className='rafii-focus inline-flex min-h-8 min-w-0 items-center gap-1.5 rounded-full py-1 pr-2 pl-2.5 text-left'
                aria-expanded={open === item.id} aria-controls={open === item.id ? detailsId : undefined} data-lens-chip={index}
                onClick={() => setOpen((current) => (current === item.id ? null : item.id))}>
                <Icon aria-hidden className='size-3.5 shrink-0' />
                <span className={cn('max-w-[13rem] truncate', removedHere && 'line-through')}>{label}</span>
                {!active && <span className='sr-only'>, {removedHere ? t('removedShort', lang) : t('notUsedShort', lang)}</span>}
                {!item.removable && <Icons.lock aria-hidden className='text-muted-foreground size-3 shrink-0' />}
              </button>
              {item.removable && item.status === 'included' && (
                <button type='button' className='rafii-focus text-muted-foreground hover:text-foreground -ml-1 inline-flex size-8 shrink-0 items-center justify-center rounded-full'
                  aria-label={t(removedHere ? 'restore' : 'remove', lang, { label })} onClick={() => toggle(item)}>
                  {removedHere ? <Icons.refresh aria-hidden className='size-3.5' /> : <Icons.close aria-hidden className='size-3.5' />}
                </button>
              )}
            </li>
          );
        })}
        {missing && (
          <li className='text-muted-foreground inline-flex min-h-8 items-center gap-1.5 rounded-full border border-dashed px-2.5 text-xs' data-lens-kind='no_selection'>
            <Icons.info aria-hidden className='size-3.5 shrink-0' />
            <span>{t('noSelection', lang)}</span>
            <span className='sr-only'>: {t('noSelectionWhy', lang)}</span>
          </li>
        )}
        {hidden > 0 && (
          <li>
            <Button type='button' variant='quiet' size='xs' onClick={() => setExpanded(true)}>{t('more', lang, { count: hidden })}</Button>
          </li>
        )}
        {expanded && list.length > VISIBLE && (
          <li>
            <Button type='button' variant='quiet' size='xs' onClick={() => setExpanded(false)}>{t('fewer', lang)}</Button>
          </li>
        )}
      </ul>
      {missing && <p className='text-muted-foreground mt-1 px-1 text-xs' aria-hidden>{t('noSelectionWhy', lang)}</p>}
      {openItem && (
        <div ref={details} id={detailsId} role='region' aria-label={t('inspect', lang, { label: chipLabel(openItem, lang) })}
          className='rafii-glass mt-2 flex flex-col gap-1.5 rounded-2xl p-3 text-xs leading-relaxed'>
          <div className='flex items-start justify-between gap-2'>
            <p className='font-medium break-words'>{chipLabel(openItem, lang)}</p>
            <Button type='button' variant='quiet' size='xs' onClick={close}>{t('close', lang)}</Button>
          </div>
          <p className='text-muted-foreground'>{whyLine(openItem, lang)}</p>
          {statusLine(openItem, lang, removed.has(openItem.id)) && <p>{statusLine(openItem, lang, removed.has(openItem.id))}</p>}
          {checkedLine(openItem, lang, timeZone) && <p className='text-muted-foreground'>{checkedLine(openItem, lang, timeZone)}</p>}
          <div className='flex flex-wrap gap-2 pt-1'>
            {openItem.removable && openItem.status === 'included' && (
              <Button type='button' variant='glass' size='xs' onClick={() => toggle(openItem)}>
                {t(removed.has(openItem.id) ? 'restore' : 'remove', lang, { label: chipLabel(openItem, lang) })}
              </Button>
            )}
            {openItem.kind === 'conversation' && onNewConversation && (
              <Button type='button' variant='glass' size='xs' onClick={() => { setOpen(null); onNewConversation(); }}>{t('newConversation', lang)}</Button>
            )}
          </div>
          <p className='text-muted-foreground'>{t('nextOnly', lang)} {t('dataOnly', lang)}</p>
        </div>
      )}
      <p className='sr-only' role='status' aria-live='polite'>{announcement}</p>
    </section>
  );
}
