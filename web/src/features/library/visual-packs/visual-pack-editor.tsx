'use client';

/**
 * The six-slide editor (PRD R-VIS-01..03): per-slide text, alt text and Library image, keyboard-accessible dnd-kit
 * reordering, palette and weight, the server's checks, a preview of the server-rendered PNGs (never a browser
 * approximation), and the honest handoff: render → accept → export → download → "I posted these myself". Direct
 * publishing is not offered for a six-image carousel. Saving always makes a new version; earlier ones stay. A newer
 * version arriving while someone types never discards their edits (they choose), files removed with a deleted image are
 * said as such, and an export that no longer reproduces can be exported again. Words follow the person's language.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import Image from 'next/image';
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type Announcements, type DragEndEvent } from '@dnd-kit/core';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type { Asset } from '@/lib/api/types';
import { errorCode, errorMessage, idempotencyKey } from '@/lib/growth-v2/request';
import { useDownloadPack, useEditVisualPack, usePackAction, usePackFile, useVisualPack } from '@/lib/growth-v2/visual-pack-hooks';
import {
  copyFor,
  editInput,
  fill,
  findingMessage,
  hasEdits,
  localPack,
  moveKey,
  moveTo,
  nextStep,
  paletteLabel,
  rebase,
  receiptText,
  reconcile,
  revisionPurged,
  serverText,
  stateLabel,
  type Lang,
  type LocalPack,
  type LocalSlide
} from '@/lib/growth-v2/visual-pack-logic';
import type { PackEditInput, PackView, PackWeight, RenderedSlide, SlideCheck } from '@/lib/growth-v2/visual-pack-types';
import { textAttributes } from '@/lib/locales';
import { isPostableImage } from '@/lib/media/asset-kinds';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { useAssetImage } from '../asset-card';

type Copy = ReturnType<typeof copyFor>;

/** An object URL for a Blob, revoked when the Blob changes or the view unmounts. */
export function useObjectUrl(blob: Blob | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

function RenderedPreview({ slide, lang }: { slide: RenderedSlide; lang: Lang }) {
  const file = usePackFile(slide.href);
  const url = useObjectUrl(file.data);
  return (
    <figure className='flex flex-col gap-1'>
      <div className='bg-foreground/[0.04] aspect-[4/5] w-full overflow-hidden rounded-[var(--rafii-radius-control)]'>
        {url ? (
          <Image src={url} alt={slide.altText} width={slide.width} height={slide.height} unoptimized className='size-full object-contain' />
        ) : file.isError ? (
          <p role='alert' className='text-destructive p-3 text-xs'>
            {serverText(errorCode(file.error), errorMessage(file.error), lang)}
          </p>
        ) : (
          <Skeleton className='size-full' />
        )}
      </div>
      <figcaption className='text-muted-foreground text-xs tabular-nums'>
        {slide.position}/6 · {slide.width}×{slide.height}
      </figcaption>
    </figure>
  );
}

function ImageThumb({ assetId }: { assetId: string }) {
  const image = useAssetImage(assetId);
  return (
    <span className='bg-foreground/[0.06] block size-11 shrink-0 overflow-hidden rounded-[var(--rafii-radius-control)]'>
      {image.data ? <Image src={image.data} alt='' width={44} height={44} unoptimized className='size-full object-cover' /> : null}
    </span>
  );
}

function Findings({ check, copy }: { check: SlideCheck | undefined; copy: Copy }) {
  const visible = check?.findings ?? [];
  if (!visible.length) return null;
  return (
    <ul className='flex flex-col gap-1 text-sm'>
      {visible.map((finding, index) => (
        <li key={`${finding.code}-${index}`} className={cn('flex items-start gap-2', finding.severity === 'blocking' ? 'text-destructive' : 'text-muted-foreground')}>
          {finding.severity === 'blocking' ? <Icons.warning aria-hidden className='mt-0.5 size-4 shrink-0' /> : <Icons.info aria-hidden className='mt-0.5 size-4 shrink-0' />}
          <span>{findingMessage(finding, copy)}</span>
        </li>
      ))}
    </ul>
  );
}

interface SlideRowProps {
  slide: LocalSlide;
  position: number;
  role: 'hook' | 'point' | 'close';
  check: SlideCheck | undefined;
  copy: Copy;
  language: string;
  images: Asset[];
  limits: PackView['options']['limits'];
  canEdit: boolean;
  reduced: boolean;
  isFirst: boolean;
  isLast: boolean;
  onChange: (patch: Partial<LocalSlide>) => void;
  onMove: (delta: number) => void;
}

function SlideRow({ slide, position, role, check, copy, language, images, limits, canEdit, reduced, isFirst, isLast, onChange, onMove }: SlideRowProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: slide.key, disabled: !canEdit });
  const style = { transform: CSS.Translate.toString(transform), transition: reduced ? undefined : transition };
  const ids = { text: `vp-text-${slide.key}`, alt: `vp-alt-${slide.key}`, image: `vp-image-${slide.key}` };
  const blocked = check ? !check.ok : false;
  return (
    <li ref={setNodeRef} style={style} className={cn('rafii-glass flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-3 md:p-4', isDragging && 'relative z-10 shadow-lg')}>
      <div className='flex items-center gap-2'>
        {canEdit && (
          <button
            type='button'
            ref={setActivatorNodeRef}
            {...attributes}
            {...listeners}
            aria-label={fill(copy.dragHandle, { n: position })}
            className='rafii-focus text-muted-foreground hover:text-foreground flex size-11 shrink-0 cursor-grab touch-none items-center justify-center rounded-full active:cursor-grabbing'
          >
            <Icons.gripVertical aria-hidden className='size-5' />
          </button>
        )}
        <h4 className='flex min-w-0 flex-1 items-center gap-2 text-sm font-medium'>
          <span className='tabular-nums'>{fill(copy.slide, { n: position })}</span>
          <span className='text-muted-foreground font-normal'>· {copy.roles[role]}</span>
          {check && (blocked ? <Icons.warning aria-hidden className='text-destructive size-4' /> : <Icons.circleCheck aria-hidden className='text-muted-foreground size-4' />)}
        </h4>
        {canEdit && (
          <div className='flex shrink-0 gap-1'>
            <Button variant='quiet' size='icon-control' aria-label={fill(copy.moveUp, { n: position })} disabled={isFirst} onClick={() => onMove(-1)}>
              <Icons.chevronUp aria-hidden />
            </Button>
            <Button variant='quiet' size='icon-control' aria-label={fill(copy.moveDown, { n: position })} disabled={isLast} onClick={() => onMove(1)}>
              <Icons.chevronDown aria-hidden />
            </Button>
          </div>
        )}
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={ids.text}>{copy.text}</Label>
        <Textarea
          id={ids.text}
          value={slide.text}
          maxLength={limits.text}
          readOnly={!canEdit}
          aria-invalid={blocked || undefined}
          onChange={(event) => onChange({ text: event.target.value })}
          className='min-h-20'
          {...textAttributes(language)}
        />
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={ids.image}>{copy.image}</Label>
        <div className='flex items-center gap-2'>
          {slide.imageAssetId && <ImageThumb assetId={slide.imageAssetId} />}
          <NativeSelect
            id={ids.image}
            value={slide.imageAssetId ?? ''}
            disabled={!canEdit}
            onChange={(event) => onChange({ imageAssetId: event.target.value || null })}
            className='w-full min-w-0 [&_select]:h-11'
          >
            <NativeSelectOption value=''>{copy.noImage}</NativeSelectOption>
            {slide.imageAssetId && !images.some((a) => a.id === slide.imageAssetId) && <NativeSelectOption value={slide.imageAssetId}>{slide.imageAssetId.slice(0, 8)}</NativeSelectOption>}
            {images.map((asset) => (
              <NativeSelectOption key={asset.id} value={asset.id}>
                {asset.width && asset.height ? `${asset.width}×${asset.height}` : copy.image} · {asset.hash.slice(0, 8)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={ids.alt}>{copy.altText}</Label>
        <Textarea
          id={ids.alt}
          value={slide.altText}
          maxLength={limits.altText}
          readOnly={!canEdit}
          aria-describedby={`${ids.alt}-hint`}
          onChange={(event) => onChange({ altText: event.target.value, altCustom: true })}
          className='min-h-16 text-sm'
          {...textAttributes(language)}
        />
        <p id={`${ids.alt}-hint`} className='text-muted-foreground text-xs'>
          {copy.altHint}
        </p>
      </div>
      <Findings check={check} copy={copy} />
    </li>
  );
}

type Recovery = 'idle' | 'running' | 'tried';

/**
 * The editor for one pack. Local edits are kept relative to `base`, the version on screen; a newer version from the
 * server (a save here, an action, or someone else) never remounts the editor, so nothing typed is lost. Without unsaved
 * edits the newer version is shown (with a note when it came from elsewhere); with edits the person chooses: keep them
 * on top of the newer version, or load it and discard them.
 */
function EditorBody({ view, copy, canEdit, images, onConflict }: { view: PackView; copy: Copy; canEdit: boolean; images: Asset[]; onConflict: () => void }) {
  const lang = copy.lang as Lang;
  const { reduced } = useMotionPreference();
  const [base, setBase] = useState<PackView>(view);
  const [local, setLocal] = useState<LocalPack>(() => localPack(view.revision));
  const [seen, setSeen] = useState<PackView>(view);
  const [conflict, setConflict] = useState<PackView | null>(null);
  const [notice, setNotice] = useState<number | null>(null);
  // The version this editor's own save will create: adopting it needs no "changed elsewhere" note.
  const [ownRevision, setOwnRevision] = useState<number | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [posted, setPosted] = useState(false);
  const [recovery, setRecovery] = useState<Recovery>('idle');
  // One idempotency key per distinct request: a retry of the same save replays; a different save is a new request.
  const pending = useRef<{ body: string; key: string } | null>(null);
  // A control the person just used can disappear with the new state (a conflict choice, the export-again button):
  // focus then goes to what comes next instead of the dialog itself.
  const [focusNext, setFocusNext] = useState<'save' | 'slides' | 'download' | null>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  const downloadRef = useRef<HTMLButtonElement>(null);
  const slidesHeading = useRef<HTMLHeadingElement>(null);
  const packId = base.pack.id;
  const edit = useEditVisualPack(packId);
  const action = usePackAction(packId);
  const download = useDownloadPack(packId);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  // The server's view changed: decide once per view, while rendering (no remount, no lost typing).
  if (view !== seen) {
    setSeen(view);
    const outcome = reconcile(base.revision, view.revision, local, ownRevision);
    if (outcome.kind === 'refresh') {
      setBase(view);
    } else if (outcome.kind === 'adopt') {
      setBase(view);
      setLocal(localPack(view.revision));
      setConflict(null);
      setNotice(outcome.notice ? view.revision.revision : null);
    } else if (outcome.kind === 'conflict') {
      setConflict(view);
    }
  }

  useEffect(() => {
    if (!focusNext) return;
    const target = focusNext === 'save' ? saveButton.current : focusNext === 'download' ? downloadRef.current : null;
    (target ?? slidesHeading.current)?.focus();
    setFocusNext(null);
  }, [focusNext]);

  const revision = base.revision;
  const slides = local.slides;
  const input: PackEditInput = useMemo(() => editInput(revision, local), [revision, local]);
  const dirty = hasEdits(input);
  const step = nextStep(revision, dirty);
  const purged = revisionPurged(revision);
  const checks = new Map(revision.checks.slides.map((c) => [c.key, c]));
  const positionOf = (key: string) => slides.findIndex((s) => s.key === key) + 1;
  const busy = edit.isPending || action.isPending || download.isPending || recovery === 'running';
  const blocked = busy || conflict !== null;
  const integrity = errorCode(download.error) === 'integrity_failed';
  const failure = edit.error ?? action.error ?? download.error;
  // A version conflict is explained by the conflict choice or the "changed elsewhere" note, not repeated as an error;
  // an export that no longer matches has its own message and recovery below.
  const showFailure = failure && !(errorCode(failure) === 'revision_conflict' && (conflict !== null || notice !== null)) && !(integrity && failure === download.error);
  const merged = conflict ? rebase(revision, conflict.revision, local) : null;
  const say = (error: unknown) => serverText(errorCode(error), errorMessage(error), lang);

  const announcements: Announcements = {
    onDragStart: ({ active }) => fill(copy.dnd.picked, { n: positionOf(String(active.id)) }),
    onDragOver: ({ active, over }) => (over ? fill(copy.dnd.over, { n: positionOf(String(active.id)), to: positionOf(String(over.id)) }) : undefined),
    onDragEnd: ({ active, over }) => (over ? fill(copy.dnd.dropped, { n: positionOf(String(active.id)), to: positionOf(String(over.id)) }) : undefined),
    onDragCancel: () => copy.dnd.cancelled
  };

  function setSlides(next: (current: LocalSlide[]) => LocalSlide[]) {
    setLocal((current) => ({ ...current, slides: next(current.slides) }));
  }

  function reorder(order: string[]) {
    setSlides((current) => {
      const byKey = new Map(current.map((s) => [s.key, s]));
      return order.map((key) => byKey.get(key) as LocalSlide);
    });
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    if (over) reorder(moveTo(slides.map((s) => s.key), String(active.id), String(over.id)));
  }

  function patchSlide(key: string, patch: Partial<LocalSlide>) {
    setSlides((current) => current.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  }

  function discard() {
    setLocal(localPack(revision));
    pending.current = null;
  }

  /** Load the newer version and discard the unsaved edits (only when the person picks it). */
  function loadLatest() {
    if (!conflict) return;
    setBase(conflict);
    setLocal(localPack(conflict.revision));
    setConflict(null);
    setNotice(null);
    pending.current = null;
    edit.reset();
    setFocusNext('slides');
  }

  /** Keep the edits, carried onto the newer version; saving then makes the next version from it. */
  function keepMine() {
    if (!conflict || !merged) return;
    setBase(conflict);
    setLocal(merged);
    setConflict(null);
    setNotice(null);
    pending.current = null;
    edit.reset();
    setFocusNext('save');
  }

  async function save(extra: PackEditInput = input) {
    // The version is part of the request: the same edit on a newer version is a new request with a new key.
    const body = JSON.stringify({ on: revision.revision, ...extra });
    const request = pending.current?.body === body ? pending.current : { body, key: idempotencyKey('vp-edit') };
    pending.current = request;
    setOwnRevision(revision.revision + 1);
    setNotice(null);
    try {
      await edit.mutateAsync({ expectedRevision: revision.revision, input: extra, key: request.key });
      pending.current = null;
    } catch (error) {
      setOwnRevision(null);
      // Shown below with role=alert; a retry replays the same key. A newer version elsewhere: load it, keep the edits.
      if (errorCode(error) === 'revision_conflict') onConflict();
    }
  }

  async function act(name: 'render' | 'accept' | 'export' | 'confirm-used', confirmed?: boolean) {
    setNotice(null);
    try {
      await action.mutateAsync({ action: name, expectedRevision: revision.revision, confirmed });
    } catch (error) {
      if (errorCode(error) === 'revision_conflict') onConflict();
    }
  }

  /** The recorded export can't be reproduced: export again (the server rebuilds it from the checked slides), then download. */
  async function exportAgain() {
    setRecovery('running');
    setNotice(null);
    try {
      const fresh = await action.mutateAsync({ action: 'export', expectedRevision: revision.revision });
      const file = fresh.revision.export;
      if (file) await download.mutateAsync({ href: file.href, filename: file.filename });
    } catch (error) {
      if (errorCode(error) === 'revision_conflict') onConflict();
    } finally {
      setRecovery('tried');
      setFocusNext('download');
    }
  }

  let primary: ReactNode = null;
  if (canEdit) {
    if (step === 'save') {
      primary = (
        <div className='flex flex-col gap-2 sm:flex-row-reverse'>
          <Button ref={saveButton} variant='action' size='control' disabled={blocked} onClick={() => void save()}>
            {edit.isPending ? copy.saving : copy.save}
          </Button>
          {!conflict && (
            <Button variant='glass' size='control' disabled={busy} onClick={discard}>
              {copy.discard}
            </Button>
          )}
        </div>
      );
    } else if (step === 'reconcile') {
      primary = (
        <div className='flex flex-col gap-2 sm:flex-row-reverse'>
          <Button variant='action' size='control' disabled={blocked} onClick={() => void save({ source: 'resplit' })}>
            {copy.resplit}
          </Button>
          <Button variant='glass' size='control' disabled={blocked} onClick={() => void save({ source: 'keep' })}>
            {copy.keep}
          </Button>
        </div>
      );
    } else if (step === 'render' || (step === 'fix' && !purged)) {
      primary = (
        <Button variant='action' size='control' disabled={blocked || step === 'fix'} onClick={() => void act('render')}>
          {action.isPending ? copy.rendering : copy.render}
        </Button>
      );
    } else if (step === 'accept') {
      primary = (
        <>
          <label className='flex min-h-11 items-start gap-3 text-sm'>
            <input type='checkbox' aria-label={copy.acceptConfirm} checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} className='mt-0.5 size-4 shrink-0' />
            {copy.acceptConfirm}
          </label>
          <Button variant='action' size='control' disabled={blocked || !reviewed} onClick={() => void act('accept', true)}>
            {copy.accept}
          </Button>
        </>
      );
    } else if (step === 'export') {
      primary = (
        <Button variant='action' size='control' disabled={blocked} onClick={() => void act('export')}>
          <Icons.fileZip aria-hidden />
          {action.isPending ? copy.exporting : copy.export}
        </Button>
      );
    }
  }
  const exported = revision.export;
  const downloadButton = exported && canEdit && (step === 'download' || step === 'confirm' || step === 'done') && (
    <Button
      ref={downloadRef}
      variant={step === 'download' ? 'action' : 'glass'}
      size='control'
      disabled={blocked}
      onClick={() => download.mutate({ href: exported.href, filename: exported.filename })}
    >
      <Icons.download aria-hidden />
      {download.isPending ? copy.downloading : copy.download}
    </Button>
  );
  if (canEdit && step === 'confirm') {
    primary = (
      <>
        <label className='flex min-h-11 items-start gap-3 text-sm'>
          <input type='checkbox' aria-label={copy.confirmUsed} checked={posted} onChange={(e) => setPosted(e.target.checked)} className='mt-0.5 size-4 shrink-0' />
          <span className='flex flex-col gap-0.5'>
            {copy.confirmUsed}
            <span className='text-muted-foreground text-xs'>{copy.confirmUsedHint}</span>
          </span>
        </label>
        <Button variant='action' size='control' disabled={blocked || !posted} onClick={() => void act('confirm-used', true)}>
          {copy.confirmUsed}
        </Button>
      </>
    );
  }

  return (
    <>
      <RafiiDialogHeader eyebrow={copy.title} title={`${stateLabel(revision.state, purged, copy)} · ${fill(copy.version, { n: revision.revision })}`} closeLabel={copy.close} />
      <RafiiDialogBody className='flex flex-col gap-5'>
        {notice !== null && (
          <p role='status' className='text-sm font-medium'>
            {fill(copy.updatedElsewhere, { n: notice })}
          </p>
        )}
        {purged ? (
          <StateMessage kind='stale' layout='inline' title={copy.purged} description={copy.purgedNote} />
        ) : (
          <p role='status' className='text-sm'>
            {receiptText(revision.state, base.receipt, lang)}
            {revision.facts.downloadCount > 0 && <span className='text-muted-foreground'> · {fill(copy.downloads, { n: revision.facts.downloadCount })}</span>}
          </p>
        )}
        {revision.sourceStatus !== 'current' && (
          <StateMessage kind='stale' layout='inline' title={revision.sourceStatus === 'changed' ? copy.sourceChanged : copy.sourceGone} />
        )}
        <p className='text-muted-foreground text-sm' role='status'>
          {revision.checks.ok ? copy.checksOk : fill(copy.checksBlocked, { n: revision.checks.blocking })}
        </p>

        <section aria-labelledby='vp-slides' className='flex flex-col gap-3'>
          <h3 id='vp-slides' ref={slidesHeading} tabIndex={-1} className='text-base font-medium outline-none'>
            {copy.slides}
          </h3>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragEnd={onDragEnd}
            accessibility={{ announcements, screenReaderInstructions: { draggable: copy.dnd.instructions } }}
          >
            <SortableContext items={slides.map((s) => s.key)} strategy={verticalListSortingStrategy}>
              <ol className='flex flex-col gap-3'>
                {slides.map((slide, index) => (
                  <SlideRow
                    key={slide.key}
                    slide={slide}
                    position={index + 1}
                    role={index === 0 ? 'hook' : index === slides.length - 1 ? 'close' : 'point'}
                    check={checks.get(slide.key)}
                    copy={copy}
                    language={base.pack.language}
                    images={images}
                    limits={base.options.limits}
                    canEdit={canEdit}
                    reduced={reduced}
                    isFirst={index === 0}
                    isLast={index === slides.length - 1}
                    onChange={(patch) => patchSlide(slide.key, patch)}
                    onMove={(delta) => reorder(moveKey(slides.map((s) => s.key), slide.key, delta))}
                  />
                ))}
              </ol>
            </SortableContext>
          </DndContext>
        </section>

        <fieldset className='flex flex-col gap-2' disabled={!canEdit}>
          <legend className='mb-1 text-sm font-medium'>{copy.palette}</legend>
          <div className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
            {base.options.palettes.map((option) => {
              const label = paletteLabel(option.id, option.label, lang);
              return (
                <label key={option.id} className={cn('rafii-glass flex min-h-11 cursor-pointer items-center gap-2 rounded-[var(--rafii-radius-control)] p-2 text-sm', local.palette === option.id && 'rafii-glass-selected')}>
                  <input
                    type='radio'
                    name={`vp-palette-${packId}`}
                    aria-label={label}
                    value={option.id}
                    checked={local.palette === option.id}
                    onChange={() => setLocal((current) => ({ ...current, palette: option.id }))}
                    className='size-4 shrink-0'
                  />
                  <span aria-hidden className='flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold' style={{ background: option.background, color: option.text, borderColor: option.accent }}>
                    Aa
                  </span>
                  {label}
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className='flex flex-col gap-2'>
          <span className='text-sm font-medium'>
            {copy.weight}
          </span>
          <SegmentedControl
            label={copy.weight}
            value={local.weight}
            onChange={(value) => canEdit && setLocal((current) => ({ ...current, weight: value }))}
            widths='content'
            className='w-fit'
            options={(base.options.weights as PackWeight[]).map((value) => ({ value, label: copy.weights[value], disabled: !canEdit }))}
          />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor={`vp-caption-${packId}`}>{copy.caption}</Label>
          <Textarea
            id={`vp-caption-${packId}`}
            value={local.caption}
            maxLength={base.options.limits.caption}
            readOnly={!canEdit}
            onChange={(e) => setLocal((current) => ({ ...current, caption: e.target.value }))}
            className='min-h-24'
            {...textAttributes(base.pack.language)}
          />
        </div>

        <section aria-labelledby='vp-preview' className='flex flex-col gap-2'>
          <h3 id='vp-preview' className='text-base font-medium'>
            {copy.preview}
          </h3>
          <p className='text-muted-foreground text-xs'>{copy.previewHint}</p>
          {revision.render?.available ? (
            <div className='grid grid-cols-2 gap-3 sm:grid-cols-3'>
              {revision.render.slides.map((slide) => (
                <RenderedPreview key={slide.sha256 + slide.position} slide={slide} lang={lang} />
              ))}
            </div>
          ) : (
            <p className='text-muted-foreground text-sm'>{purged ? copy.purged : copy.notRendered}</p>
          )}
        </section>
        <p className='text-muted-foreground text-sm'>{copy.queueNote}</p>
      </RafiiDialogBody>
      <RafiiDialogFooter>
        {conflict && (
          <div role='alert' className='flex flex-col gap-2 text-sm'>
            <p className='font-medium'>{fill(copy.conflictTitle, { n: conflict.revision.revision })}</p>
            <p className='text-muted-foreground'>{fill(merged ? copy.conflictBody : copy.conflictNoMerge, { n: conflict.revision.revision })}</p>
            <div className='flex flex-col gap-2 sm:flex-row-reverse'>
              {merged && canEdit && (
                <Button variant='action' size='control' disabled={busy} onClick={keepMine}>
                  {copy.keepMine}
                </Button>
              )}
              <Button variant='glass' size='control' disabled={busy} onClick={loadLatest}>
                {fill(copy.loadLatest, { n: conflict.revision.revision })}
              </Button>
            </div>
          </div>
        )}
        {dirty && !conflict && <p className='text-muted-foreground text-xs'>{copy.unsaved}</p>}
        {integrity && (
          <div role='alert' className='flex flex-col gap-2 text-sm'>
            <p className='text-destructive'>{recovery === 'idle' ? copy.integrityTitle : say(download.error)}</p>
            {recovery === 'idle' && canEdit && (
              <>
                <p className='text-muted-foreground'>{copy.integrityHint}</p>
                <Button variant='action' size='control' disabled={busy} onClick={() => void exportAgain()}>
                  <Icons.fileZip aria-hidden />
                  {copy.exportAgain}
                </Button>
              </>
            )}
          </div>
        )}
        {recovery === 'running' && (
          <p role='status' className='text-muted-foreground text-sm'>
            {action.isPending ? copy.exporting : copy.downloading}
          </p>
        )}
        {showFailure && (
          <p role='alert' className='text-destructive text-sm'>
            {say(failure)}
          </p>
        )}
        {step === 'done' && <p className='text-sm'>{copy.done}</p>}
        {step === 'unavailable' && <p className='text-sm'>{copy.sourceGone}</p>}
        {primary}
        {downloadButton}
      </RafiiDialogFooter>
    </>
  );
}

export function VisualPackEditor({
  packId,
  open,
  onOpenChange,
  copy,
  canEdit,
  images,
  returnFocus
}: {
  packId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  copy: Copy;
  canEdit: boolean;
  images: Asset[];
  /** Where focus goes when the dialog closes (the pack's card, say); the dialog's default when it returns null. */
  returnFocus?: () => HTMLElement | null;
}) {
  // Kept while the dialog closes (no refetch once closed), so its content doesn't flicker on the way out.
  const pack = useVisualPack(packId, open);
  const libraryImages = useMemo(() => images.filter((asset) => isPostableImage(asset)), [images]);
  const view = pack.data;
  const lang = copy.lang as Lang;
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='xl' lang={copy.lang} finalFocus={returnFocus ? () => returnFocus() ?? true : undefined}>
        {view ? (
          <EditorBody key={view.pack.id} view={view} copy={copy} canEdit={canEdit} images={libraryImages} onConflict={() => void pack.refetch()} />
        ) : (
          <>
            <RafiiDialogHeader title={copy.title} closeLabel={copy.close} />
            <RafiiDialogBody>
              {pack.isError ? (
                <StateMessage
                  kind='error'
                  title={copy.loadError}
                  description={serverText(errorCode(pack.error), errorMessage(pack.error), lang)}
                  action={<Button variant='glass' size='control' onClick={() => void pack.refetch()}>{copy.retry}</Button>}
                />
              ) : (
                <StateMessage kind='loading' title={copy.title} />
              )}
            </RafiiDialogBody>
          </>
        )}
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
