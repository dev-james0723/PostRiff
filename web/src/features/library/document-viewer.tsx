'use client';

import Image from 'next/image';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { IconArrowsMaximize, IconMinus, IconPlus, IconRotateClockwise, IconTextSize } from '@tabler/icons-react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { ApiError } from '@/lib/api/client';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from './use-library';
import { toast } from 'sonner';

const FORMATS = new Set(['pdf', 'docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'odt', 'ods', 'odp', 'rtf', 'txt', 'md', 'markdown', 'html', 'htm', 'csv', 'json']);
const extensionOf = (asset: LibraryAsset) => (asset.extension || asset.originalFilename?.split('.').pop() || '').toLowerCase();
export const canViewDocument = (asset: LibraryAsset) => FORMATS.has(extensionOf(asset));
type Fit = 'width' | 'page' | 'custom';
const retryPage = (count: number, error: unknown) => count < (error instanceof ApiError && [409, 429].includes(error.status) ? 32 : 1);

function useDocumentPage(asset: LibraryAsset, page: number, enabled = true) {
  const { api, workspaceId } = useWorkspaceApi();
  return useQuery({
    queryKey: ['library-document-page', workspaceId, asset.id, asset.hash, page],
    queryFn: () => api.libraryViewerPage(workspaceId, asset.id, page),
    enabled: enabled && Boolean(workspaceId),
    staleTime: 3 * 60_000,
    gcTime: 5 * 60_000,
    refetchInterval: enabled ? 4 * 60_000 : false,
    retry: retryPage,
    retryDelay: 3000
  });
}

/** A real source page; offscreen sidebar pages never trigger rendering. */
function PageThumbnail({ asset, page, active, onSelect }: { asset: LibraryAsset; page: number; active: boolean; onSelect: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin: '40px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const query = useDocumentPage(asset, page, visible);
  return <button ref={ref} type='button' aria-label={`Go to page ${page}`} aria-current={active ? 'page' : undefined} onClick={onSelect}
    className={cn('rafii-focus flex h-[148px] min-h-11 w-full flex-col items-center gap-2 rounded-lg p-2 text-xs', active ? 'bg-foreground/10 font-semibold ring-2 ring-foreground/40' : 'hover:bg-foreground/5')}>
    <span className='relative flex aspect-[3/4] w-20 items-center justify-center overflow-hidden rounded-sm bg-white shadow-sm'>
      {query.data ? <Image src={query.data.url} alt='' width={query.data.width} height={query.data.height} unoptimized className='max-h-full max-w-full object-contain' /> : <Icons.page aria-hidden className='size-5 text-neutral-400' />}
    </span>
    <span>Page {page}</span>
  </button>;
}

/** Keep long documents bounded: only visible thumbnail rows mount observers/queries. */
function PageSidebar({ asset, page, pageCount, onSelect }: { asset: LibraryAsset; page: number; pageCount: number; onSelect: (page: number) => void }) {
  const ref = useRef<HTMLElement>(null);
  const [view, setView] = useState({ top: 0, height: 600 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setView((current) => ({ ...current, height: entry.contentRect.height })));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const top = (page - 1) * 148 + 36;
    if (top < element.scrollTop || top + 148 > element.scrollTop + element.clientHeight) element.scrollTo({ top: Math.max(0, top - element.clientHeight / 2 + 74) });
  }, [page]);
  const start = Math.max(0, Math.floor((view.top - 36) / 148) - 2);
  const end = Math.min(pageCount, Math.ceil((view.top + view.height - 36) / 148) + 2);
  return <aside ref={ref} id='document-page-sidebar' aria-label='Document pages' onScroll={(event) => { const top = event.currentTarget.scrollTop; setView((current) => ({ ...current, top })); }} className='absolute inset-y-0 left-0 z-10 w-32 shrink-0 overflow-y-auto overscroll-contain border-r border-foreground/10 bg-popover px-2 shadow-xl sm:relative sm:shadow-none'>
    <p className='text-muted-foreground flex h-9 items-center px-2 text-[10px] font-semibold uppercase tracking-wider'>Pages</p>
    <div aria-hidden style={{ height: start * 148 }} />
    {Array.from({ length: Math.max(0, end - start) }, (_, index) => <PageThumbnail key={start + index + 1} asset={asset} page={start + index + 1} active={page === start + index + 1} onSelect={() => onSelect(start + index + 1)} />)}
    <div aria-hidden style={{ height: (pageCount - end) * 148 }} />
  </aside>;
}

function DocumentReader({ asset }: { asset: LibraryAsset }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [pageCount, setPageCount] = useState(0);
  const [sidebar, setSidebar] = useState(false);
  const [reading, setReading] = useState(false);
  const [find, setFind] = useState(false);
  const [search, setSearch] = useState('');
  const [matchIndex, setMatchIndex] = useState(0);
  const [fit, setFit] = useState<Fit>('page');
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [imageFailed, setImageFailed] = useState(false);
  const [viewport, setViewport] = useState({ width: 640, height: 600 });
  const stage = useRef<HTMLDivElement>(null);
  const reader = useRef<HTMLDivElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const currentMatch = useRef<HTMLElement>(null);
  const query = useDocumentPage(asset, page);
  const title = asset.displayTitle || asset.originalFilename || 'Document';
  const extension = extensionOf(asset).toUpperCase();
  const width = query.data?.width || 1000;
  const height = query.data?.height || 1400;
  const rotated = rotation % 180 !== 0;
  const pageWidth = rotated ? height : width;
  const pageHeight = rotated ? width : height;
  const fitWidth = Math.max(80, viewport.width - 48) / pageWidth;
  const fitPage = Math.min(fitWidth, Math.max(80, viewport.height - 48) / pageHeight);
  const scale = fit === 'custom' ? zoom / 100 : fit === 'width' ? fitWidth : fitPage;
  const shownZoom = Math.round(scale * 100);
  const text = query.data?.text || '';
  const matches = useMemo(() => {
    if (!search.trim()) return [];
    const lower = text.toLocaleLowerCase();
    const needle = search.toLocaleLowerCase();
    const result: number[] = [];
    let cursor = 0;
    while (cursor < lower.length && result.length < 1000) {
      const at = lower.indexOf(needle, cursor);
      if (at < 0) break;
      result.push(at);
      cursor = at + needle.length;
    }
    return result;
  }, [search, text]);

  useEffect(() => {
    if (query.data) setPageCount(query.data.pageCount);
    setImageFailed(false);
  }, [query.data]);
  useEffect(() => { setPageInput(String(page)); setMatchIndex(0); stage.current?.scrollTo({ top: 0, left: 0 }); }, [page]);
  useEffect(() => { setMatchIndex(0); }, [search]);
  useEffect(() => { if (find) searchInput.current?.focus(); }, [find]);
  useEffect(() => { currentMatch.current?.scrollIntoView({ block: 'center' }); }, [matchIndex, matches]);
  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setViewport({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const go = (target: number) => { if (pageCount) setPage(Math.min(pageCount, Math.max(1, target))); };
  const changeZoom = (amount: number) => { setZoom(Math.min(300, Math.max(25, shownZoom + amount))); setFit('custom'); };
  useEffect(() => {
    const element = reader.current;
    if (!element) return;
    const handleKeys = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'f') { event.preventDefault(); setFind(true); setReading(true); return; }
      if ((event.target as HTMLElement).closest('input,select,textarea,button,a')) return;
      if (['ArrowRight', 'PageDown', 'ArrowLeft', 'PageUp', 'Home', 'End'].includes(event.key) && pageCount) {
        event.preventDefault();
        setPage((current) => event.key === 'Home' ? 1 : event.key === 'End' ? pageCount : Math.min(pageCount, Math.max(1, current + (['ArrowRight', 'PageDown'].includes(event.key) ? 1 : -1))));
      }
      if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); setZoom(Math.min(300, Math.max(25, shownZoom + (event.key === '-' ? -25 : 25)))); setFit('custom'); }
    };
    element.addEventListener('keydown', handleKeys);
    return () => element.removeEventListener('keydown', handleKeys);
  }, [pageCount, shownZoom]);
  const original = (download: boolean) => {
    const target = window.open('about:blank', '_blank');
    if (target) target.opener = null;
    void api.libraryFileUrl(workspaceId, asset.id, download).then(({ url }) => {
      if (target) target.location.href = url;
      else toast.error('Allow a new tab to open the original.');
    }).catch(() => { target?.close(); toast.error('Original file unavailable'); });
  };
  const highlightedText = () => {
    if (!matches.length) return text;
    const pieces = [];
    let cursor = 0;
    matches.forEach((at, index) => {
      pieces.push(text.slice(cursor, at));
      pieces.push(<mark key={at} ref={index === matchIndex ? currentMatch : undefined} className={cn('rounded-sm px-0.5 text-neutral-950', index === matchIndex ? 'bg-amber-400' : 'bg-amber-200')}>{text.slice(at, at + search.length)}</mark>);
      cursor = at + search.length;
    });
    pieces.push(text.slice(cursor));
    return pieces;
  };

  return <div ref={reader} data-document-viewer='' role='region' aria-label='Document reading workspace' className='flex h-full min-h-0 flex-col'>
    <header className='flex min-h-16 shrink-0 items-center gap-3 border-b border-foreground/10 px-3 sm:px-5'>
      <span className='rafii-quiet hidden rounded-lg p-2 sm:block'><Icons.page aria-hidden className='size-5' /></span>
      <div className='min-w-0 flex-1'>
        <DialogTitle className='truncate text-sm sm:text-base'>{title}</DialogTitle>
        <DialogDescription className='mt-1 truncate text-xs'>{extension} · Private document · Original page layout</DialogDescription>
      </div>
      <Button variant='quiet' size='icon-control' aria-label='Download original document' title='Download original' onClick={() => original(true)}><Icons.download aria-hidden /></Button>
      <DialogClose render={<Button variant='glass' size='icon-control' aria-label='Close document viewer' />}><Icons.close aria-hidden /></DialogClose>
    </header>

    <div role='group' aria-label='Document controls' className='flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-foreground/10 px-2 py-1.5 sm:px-4'>
      <div className='flex items-center gap-0.5'>
        <Button variant='quiet' size='icon-control' aria-label={sidebar ? 'Hide page sidebar' : 'Show page sidebar'} aria-expanded={sidebar} aria-controls={sidebar ? 'document-page-sidebar' : undefined} title='Page sidebar' onClick={() => setSidebar(!sidebar)}><Icons.panelLeft aria-hidden /></Button>
        <Button variant='quiet' size='icon-control' aria-label='Previous page' disabled={page <= 1 || !pageCount} onClick={() => go(page - 1)}><Icons.chevronLeft aria-hidden /></Button>
        <form className='flex items-center gap-1.5 text-xs' onSubmit={(event) => { event.preventDefault(); const parsed = Number(pageInput); if (Number.isInteger(parsed)) go(parsed); setPageInput(String(Number.isInteger(parsed) ? Math.min(pageCount || 1, Math.max(1, parsed)) : page)); }}>
          <label className='sr-only' htmlFor='document-page-number'>Page number</label>
          <input aria-label='Page number' id='document-page-number' inputMode='numeric' pattern='[0-9]*' value={pageInput} onChange={(event) => setPageInput(event.target.value)} className='rafii-focus h-9 w-12 rounded-md border border-foreground/15 bg-transparent text-center tabular-nums' aria-describedby='document-page-total' />
          <span id='document-page-total' className='text-muted-foreground tabular-nums'>/ {pageCount || '…'}</span>
        </form>
        <Button variant='quiet' size='icon-control' aria-label='Next page' disabled={!pageCount || page >= pageCount} onClick={() => go(page + 1)}><Icons.chevronRight aria-hidden /></Button>
      </div>
      <div className='flex items-center gap-0.5'>
        <Button variant='quiet' size='icon-control' aria-label='Zoom out' disabled={reading || shownZoom <= 25} onClick={() => changeZoom(-25)}><IconMinus aria-hidden /></Button>
        <label className='sr-only' htmlFor='document-zoom'>Document zoom</label>
        <select id='document-zoom' value={fit === 'custom' ? 'custom' : fit} disabled={reading} onChange={(event) => { const value = event.target.value; if (value === 'width' || value === 'page') setFit(value); else { setZoom(Number(value)); setFit('custom'); } }} className='rafii-focus h-9 max-w-28 rounded-md border border-foreground/15 bg-popover px-2 text-xs'>
          <option value='page'>Fit page</option><option value='width'>Fit width</option>{fit === 'custom' ? <option value='custom'>{shownZoom}%</option> : null}<option value='50'>50%</option><option value='100'>100%</option><option value='150'>150%</option><option value='200'>200%</option>
        </select>
        <Button variant='quiet' size='icon-control' aria-label='Zoom in' disabled={reading || shownZoom >= 300} onClick={() => changeZoom(25)}><IconPlus aria-hidden /></Button>
        <Button variant='quiet' size='icon-control' aria-label='Rotate page clockwise' title='Rotate page' disabled={reading} onClick={() => setRotation((rotation + 90) % 360)}><IconRotateClockwise aria-hidden /></Button>
      </div>
      <div className='flex items-center gap-0.5'>
        <Button variant='quiet' size='icon-control' aria-label='Find text on current page' aria-expanded={find} title='Find on this page (⌘/Ctrl F)' onClick={() => { setFind(!find); setReading(true); }}><Icons.search aria-hidden /></Button>
        <Button variant='quiet' size='icon-control' aria-label={reading ? 'Show original page layout' : 'Read page text'} aria-pressed={reading} title='Accessible reading view' onClick={() => setReading(!reading)}><IconTextSize aria-hidden /></Button>
      </div>
    </div>

    {find ? <form role='search' aria-label='Find on current page' className='flex shrink-0 items-center gap-2 border-b border-foreground/10 px-4 py-2' onSubmit={(event) => { event.preventDefault(); if (matches.length) setMatchIndex((matchIndex + 1) % matches.length); }}>
      <label htmlFor='document-page-search' className='sr-only'>Find on this page</label>
      <input aria-label='Find on this page' ref={searchInput} id='document-page-search' placeholder='Find on this page' value={search} onChange={(event) => setSearch(event.target.value)} className='rafii-focus h-10 min-w-0 flex-1 rounded-md border border-foreground/15 bg-transparent px-3 text-sm' />
      <span role='status' className='text-muted-foreground shrink-0 text-xs tabular-nums'>{matches.length ? `${matchIndex + 1} / ${matches.length}${matches.length === 1000 ? '+' : ''}` : search ? 'No matches' : ''}</span>
      <Button type='submit' variant='quiet' size='icon-control' disabled={!matches.length} aria-label='Next text match'><Icons.chevronDown aria-hidden /></Button>
      <Button variant='quiet' size='icon-control' aria-label='Close page search' onClick={() => { setFind(false); setSearch(''); }}><Icons.close aria-hidden /></Button>
    </form> : null}

    <div className='relative flex min-h-0 flex-1'>
      {sidebar ? <PageSidebar asset={asset} page={page} pageCount={pageCount} onSelect={(target) => { go(target); if (window.matchMedia('(max-width: 639px)').matches) setSidebar(false); }} /> : null}
      <div ref={stage} aria-label={`Document page ${page}${pageCount ? ` of ${pageCount}` : ''}. Use arrow keys to navigate.`} className='rafii-focus relative min-w-0 flex-1 overflow-auto overscroll-contain bg-foreground/[0.055]'>
        {query.isPending || query.isFetching && !query.data ? <div role='status' className='flex h-full min-h-64 flex-col items-center justify-center gap-3 px-6 text-center text-sm'><Icons.spinner aria-hidden className='size-6 animate-spin' /><span>Rendering page {page} from your original document…</span><span className='text-muted-foreground text-xs'>The first render can take a little longer.</span></div> : query.isError || imageFailed ? <div role='alert' className='flex h-full min-h-64 flex-col items-center justify-center gap-3 px-6 text-center text-sm'><Icons.alertCircle aria-hidden className='size-6' /><p>This page could not be displayed.</p><div className='flex flex-wrap justify-center gap-2'><Button variant='glass' size='control' onClick={() => { setImageFailed(false); void query.refetch(); }}>Retry page</Button><Button variant='quiet' size='control' onClick={() => original(false)}>Open original</Button></div></div> : reading ? <article aria-label={`Extracted text of page ${page}`} className='mx-auto my-6 max-w-3xl rounded-sm bg-background p-6 shadow-sm sm:p-10'><h2 className='mb-6 text-xs font-semibold text-muted-foreground'>PAGE {page} · READING VIEW</h2>{text ? <div className='whitespace-pre-wrap break-words text-base leading-8'>{highlightedText()}</div> : <p className='text-muted-foreground text-sm'>This page has no extractable text. Use the original layout to read scanned pages and artwork.</p>}</article> : query.data ? <div className='flex min-h-full min-w-full items-start justify-center p-6' style={{ width: Math.max(viewport.width, pageWidth * scale + 48), minHeight: Math.max(viewport.height, pageHeight * scale + 48) }}><div className='relative shrink-0 bg-white shadow-lg' style={{ width: pageWidth * scale, height: pageHeight * scale }}><Image data-document-page={page} src={query.data.url} alt={`Original rendered page ${page} of ${title}`} width={width} height={height} unoptimized onError={() => setImageFailed(true)} style={{ position: 'absolute', left: '50%', top: '50%', width: width * scale, height: height * scale, maxWidth: 'none', transform: `translate(-50%, -50%) rotate(${rotation}deg)` }} /></div></div> : null}
      </div>
    </div>
    <footer className='text-muted-foreground flex min-h-9 shrink-0 items-center justify-between gap-3 border-t border-foreground/10 px-4 text-[11px]'>
      <span role='status' aria-live='polite'>Page {page}{pageCount ? ` of ${pageCount}` : ''}{query.data ? ` · ${width > height ? 'Landscape' : 'Portrait'}` : ''}</span>
      <input type='range' aria-label='Page navigation' aria-valuetext={`Page ${page} of ${pageCount || 1}`} min={1} max={Math.max(1, pageCount)} value={page} disabled={!pageCount} onChange={(event) => go(Number(event.target.value))} onKeyDown={(event) => { if (event.key === 'PageDown' || event.key === 'PageUp') { event.preventDefault(); go(page + (event.key === 'PageDown' ? 1 : -1)); } }} title='Use arrow keys, Home and End to navigate pages' className='rafii-focus h-8 w-20 min-w-0 cursor-pointer accent-current sm:w-40' />
      <span>{reading ? 'Extracted page text' : `${shownZoom}% · Original layout`}</span>
    </footer>
  </div>;
}

export function DocumentViewerLauncher({ asset }: { asset: LibraryAsset }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  if (!canViewDocument(asset)) return null;
  return <>
    <Button ref={trigger} variant='glass' size='control' className='w-full' disabled={!['ready', 'unsupported'].includes(asset.processing || '')} onClick={() => setOpen(true)}><IconArrowsMaximize aria-hidden />Open document viewer</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent showCloseButton={false} finalFocus={() => trigger.current} className='rafii-elevated h-dvh max-h-dvh w-screen max-w-none gap-0 overflow-hidden rounded-none p-0 sm:h-[92dvh] sm:w-[min(1400px,96vw)] sm:max-w-none sm:rounded-[var(--rafii-radius-dialog)]'>
        {open ? <DocumentReader key={asset.id} asset={asset} /> : null}
      </DialogContent>
    </Dialog>
  </>;
}
