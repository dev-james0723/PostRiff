'use client';

/**
 * Carousels in the Library (PRD R-VIS-01..03): the workspace's six-slide packs and a way to make one from a draft.
 * Hidden entirely while the deployment has the feature off (404 `feature_disabled`). `#visual-packs` links here (proof
 * evidence); words and `lang` follow the person's language (D-022), dialogs included.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import Image from 'next/image';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { errorCode, errorMessage, idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { usePackFile, usePrepareVisualPack, useVisualPacks } from '@/lib/growth-v2/visual-pack-hooks';
import { copyFor, coverState, isPurged, serverText, stateLabel, type Lang } from '@/lib/growth-v2/visual-pack-logic';
import type { PackListItem } from '@/lib/growth-v2/visual-pack-types';
import { textAttributes } from '@/lib/locales';
import { usePreferences } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import { useObjectUrl, VisualPackEditor } from './visual-pack-editor';

type Copy = ReturnType<typeof copyFor>;

/** The section's anchor: proof evidence links to `/app/library#visual-packs`. */
const VISUAL_PACKS_ANCHOR = 'visual-packs';
const itemId = (id: string) => `visual-pack-item-${id}`;

function Cover({ item, copy }: { item: PackListItem; copy: Copy }) {
  const file = usePackFile(item.cover);
  const url = useObjectUrl(file.data);
  // A cover whose bytes arrived but don't decode is a failure too, not "not rendered".
  const [broken, setBroken] = useState<string | null>(null);
  const state = coverState(item, { hasUrl: Boolean(url), failed: file.isError || (url !== null && broken === url) });
  return (
    <div className='bg-foreground/[0.04] relative aspect-[4/5] w-full overflow-hidden rounded-[calc(var(--rafii-radius-card)-6px)]'>
      {state === 'image' && url ? (
        <Image src={url} alt='' width={216} height={270} unoptimized className='size-full object-cover' onError={() => setBroken(url)} />
      ) : state === 'loading' ? (
        <Skeleton className='size-full' />
      ) : (
        <div className='text-muted-foreground flex size-full flex-col items-center justify-center gap-1 p-3 text-center text-xs'>
          {state === 'failed' ? <Icons.warning aria-hidden className='size-5' /> : <Icons.galleryVerticalEnd aria-hidden className='size-5' />}
          {state === 'failed' ? copy.coverFailed : state === 'purged' ? copy.purged : copy.notRendered}
        </div>
      )}
    </div>
  );
}

export function VisualPackSection() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const copy = copyFor(usePreferences().locale);
  const lang = copy.lang as Lang;
  const packs = useVisualPacks();
  const snapshot = useSnapshot();
  const prepare = usePrepareVisualPack();
  // The open pack stays mounted while its dialog closes, so focus can return to its card.
  const [editor, setEditor] = useState<{ id: string; open: boolean } | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [variantId, setVariantId] = useState<string | null>(null);
  const prepareKey = useRef<string | null>(null);
  const newButton = useRef<HTMLButtonElement>(null);
  const scrolled = useRef(false);

  const drafts = useMemo(
    () => (snapshot.data?.state.variants ?? []).filter((v) => v.text?.trim() && !v.rejected).slice(-50).reverse(),
    [snapshot.data]
  );
  const images = useMemo(() => snapshot.data?.state.phase2?.assets ?? [], [snapshot.data]);
  const items = packs.data?.pages.flatMap((page) => page.items) ?? [];
  const ready = !packs.isPending && !isFeatureDisabled(packs.error);

  // A link to #visual-packs (proof evidence) lands here once the section exists; it renders nothing while loading.
  useEffect(() => {
    if (!ready || scrolled.current || typeof window === 'undefined' || window.location.hash !== `#${VISUAL_PACKS_ANCHOR}`) return;
    scrolled.current = true;
    document.getElementById(VISUAL_PACKS_ANCHOR)?.scrollIntoView({ block: 'start' });
  }, [ready]);

  // Nothing at all until the server says the feature is on: a deployment with it off shows no trace of it.
  if (!ready) return null;

  async function make() {
    if (!variantId) return;
    const key = (prepareKey.current ??= idempotencyKey('vp-prepare'));
    try {
      const view = await prepare.mutateAsync({ variantId, key });
      prepareKey.current = null;
      setChoosing(false);
      setEditor({ id: view.pack.id, open: true });
    } catch {
      /* the error stays on screen (role=alert) and the same key replays a retry */
    }
  }

  const returnFocus = () => (editor ? document.getElementById(itemId(editor.id)) : null) ?? newButton.current;

  return (
    <Surface
      as='section'
      id={VISUAL_PACKS_ANCHOR}
      lang={lang}
      material='quiet'
      radius='card'
      padding='md'
      aria-labelledby='visual-packs-title'
      className='flex scroll-mt-24 flex-col gap-4'
    >
      <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
        <div className='flex min-w-0 flex-col gap-1'>
          <h2 id='visual-packs-title' className='text-lg font-medium'>
            {copy.title}
          </h2>
          <p className='text-muted-foreground text-sm'>{copy.intro}</p>
        </div>
        {canEdit && (
          <Button ref={newButton} variant='glass' size='control' onClick={() => setChoosing(true)} className='shrink-0'>
            <Icons.add aria-hidden />
            {copy.newCarousel}
          </Button>
        )}
      </div>

      {packs.isError ? (
        <StateMessage
          kind='error'
          title={copy.loadError}
          description={serverText(errorCode(packs.error), errorMessage(packs.error), lang)}
          action={
            <Button variant='glass' size='control' onClick={() => void packs.refetch()}>
              <Icons.refresh aria-hidden />
              {copy.retry}
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title={copy.empty} description={copy.emptyHint} />
      ) : (
        <ul className='grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5' aria-label={copy.title}>
          {items.map((item) => (
            <li key={item.id}>
              <button
                type='button'
                id={itemId(item.id)}
                onClick={() => setEditor({ id: item.id, open: true })}
                className='rafii-glass rafii-focus hover:rafii-glass-selected flex w-full flex-col gap-2 rounded-[var(--rafii-radius-card)] p-2 text-left'
              >
                <Cover item={item} copy={copy} />
                <span className='line-clamp-2 min-h-10 px-1 text-sm' {...textAttributes(item.language)}>
                  {item.title || '—'}
                </span>
                <span className='text-muted-foreground flex items-center justify-between gap-2 px-1 pb-1 text-xs'>
                  <span>{stateLabel(item.state, isPurged(item), copy)}</span>
                  <span>{copy.version.replace('{n}', String(item.revision))}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {packs.hasNextPage && (
        <Button variant='quiet' size='control' className='self-center' disabled={packs.isFetchingNextPage} onClick={() => void packs.fetchNextPage()}>
          {copy.loadMore}
        </Button>
      )}

      <RafiiDialog open={choosing} onOpenChange={setChoosing}>
        <RafiiDialogContent size='md' lang={lang}>
          <RafiiDialogHeader title={copy.chooseDraft} intro={copy.chooseDraftHint} closeLabel={copy.close} />
          <RafiiDialogBody>
            {drafts.length === 0 ? (
              <StateMessage kind='empty' title={copy.noDrafts} />
            ) : (
              <fieldset className='flex flex-col gap-2'>
                <legend className='sr-only'>{copy.chooseDraft}</legend>
                {drafts.map((draft) => (
                  <label
                    key={draft.id}
                    className={cn('rafii-glass flex min-h-11 cursor-pointer items-start gap-3 rounded-[var(--rafii-radius-control)] p-3', variantId === draft.id && 'rafii-glass-selected')}
                  >
                    <input
                      type='radio'
                      name='visual-pack-draft'
                      aria-label={draft.text.slice(0, 120)}
                      value={draft.id}
                      checked={variantId === draft.id}
                      onChange={() => {
                        setVariantId(draft.id);
                        prepareKey.current = null; // a different draft is a different request
                      }}
                      className='mt-1 size-4 shrink-0'
                    />
                    <span className='flex min-w-0 flex-col gap-0.5'>
                      <span className='line-clamp-2 text-sm' {...textAttributes(draft.language)}>
                        {draft.text}
                      </span>
                      <span className='text-muted-foreground text-xs'>{[draft.platform, draft.language].filter(Boolean).join(' · ')}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
          </RafiiDialogBody>
          <RafiiDialogFooter>
            {prepare.isError && (
              <p role='alert' className='text-destructive text-sm'>
                {serverText(errorCode(prepare.error), errorMessage(prepare.error), lang)}
              </p>
            )}
            <Button variant='action' size='control' disabled={!variantId || prepare.isPending} onClick={() => void make()}>
              {prepare.isPending ? copy.making : copy.make}
            </Button>
          </RafiiDialogFooter>
        </RafiiDialogContent>
      </RafiiDialog>

      {editor && (
        <VisualPackEditor
          packId={editor.id}
          open={editor.open}
          onOpenChange={(open) => !open && setEditor((current) => current && { ...current, open: false })}
          copy={copy}
          canEdit={canEdit}
          images={images}
          returnFocus={returnFocus}
        />
      )}
    </Surface>
  );
}
