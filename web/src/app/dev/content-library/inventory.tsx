'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii';
import { SemanticIllustration } from '@/components/rafii/semantic-illustration';
import { Button } from '@/components/ui/button';
import { ARTWORK, BACKEND_CONTENT_TYPE_BY_ID, BACKEND_FORMAT_LABELS, CATEGORIES, EXECUTION, LEGACY_FALLBACK, PAIRINGS, TAXONOMY, TAXONOMY_SOURCE, categoryInfo, executionFor, platformInfo, type Dimension } from '@/lib/content-library';
import { cn } from '@/lib/utils';

type Filter = 'all' | Dimension;

/**
 * Development-only visual audit of the Content Library artwork: every large illustration and compact
 * glyph with its metadata and execution mapping, drawn from the same modules the dialog uses. Counts
 * come from the data. Nothing here reads a workspace.
 */
export function ContentLibraryInventory() {
  const [filter, setFilter] = useState<Filter>('all');
  const [paused, setPaused] = useState(false);
  const items = TAXONOMY.filter((item) => filter === 'all' || item.dimension === filter);
  const editorial = TAXONOMY.filter((item) => item.dimension === 'editorial').length;
  const native = TAXONOMY.length - editorial;
  const planning = TAXONOMY.filter((item) => executionFor(item.id)?.execution === 'planning-only').length;

  return (
    <main className='bg-background text-foreground min-h-dvh px-4 py-8 md:px-8'>
      <div className='mx-auto flex max-w-6xl flex-col gap-6'>
        <header className='flex flex-col gap-3'>
          <span className='rafii-eyebrow'>Content Library · artwork inventory</span>
          <h1 className='text-3xl font-medium tracking-tight'>
            {TAXONOMY.length} items, <em className='rafii-serif'>two scales each.</em>
          </h1>
          <p className='text-muted-foreground max-w-3xl text-sm leading-relaxed'>
            {editorial} editorial types and {native} native formats, {Object.keys(ARTWORK).length * 2} assets plus the legacy fallback, {PAIRINGS.length} pairings. Source archive {TAXONOMY_SOURCE.archive} (sha256 {TAXONOMY_SOURCE.archiveSha256.slice(0, 12)}…), taxonomy {TAXONOMY_SOURCE.taxonomyVersion}, library {TAXONOMY_SOURCE.libraryVersion}, research reviewed {TAXONOMY_SOURCE.reviewedAt}. {planning} native
            formats are planning-only. Motion pauses off screen, in a background tab, under reduced motion, and with the toggle here.
          </p>
          <div className='flex flex-wrap items-center gap-3'>
            <SegmentedControl<Filter>
              label='Dimension'
              size='sm'
              widths='content'
              value={filter}
              onChange={setFilter}
              options={[
                { value: 'all', label: `All · ${TAXONOMY.length}` },
                { value: 'editorial', label: `Editorial · ${editorial}` },
                { value: 'native', label: `Native · ${native}` }
              ]}
            />
            <Button variant='glass' size='control' aria-pressed={paused} onClick={() => setPaused((value) => !value)} className='gap-2 text-xs'>
              {paused ? <Icons.play className='size-3.5' /> : <Icons.pause className='size-3.5' />}
              {paused ? 'Play artwork' : 'Pause artwork'}
            </Button>
            <span className='text-muted-foreground text-xs'>The paper field stays light in both themes; switch the app theme to check the chrome around it.</span>
          </div>
        </header>

        <section aria-label='Artwork' className='grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3'>
          {items.map((item, index) => {
            const art = ARTWORK[item.id];
            const mapping = EXECUTION[item.id];
            const target = mapping?.contentTypeId ? BACKEND_CONTENT_TYPE_BY_ID[mapping.contentTypeId]?.label : mapping?.formatId ? BACKEND_FORMAT_LABELS[mapping.formatId] : null;
            return (
              <article key={item.id} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-3'>
                <SemanticIllustration id={item.id} size='large' motion={!paused} delayIndex={index} className='rounded-[0.8125rem]' />
                <div className='flex items-start gap-3'>
                  <SemanticIllustration id={item.id} size='compact' motion={!paused} delayIndex={index} className='size-12 shrink-0 rounded-[0.8125rem]' />
                  <div className='flex min-w-0 flex-col gap-1'>
                    <span className={cn('leading-snug', item.dimension === 'editorial' ? 'text-lg [font-family:var(--rafii-font-editorial)]' : 'text-base font-medium')}>{item.title}</span>
                    <span className='text-muted-foreground text-xs'>
                      {item.dimension} · {categoryInfo(item.dimension, item.category)?.label} · {item.family}
                    </span>
                    <span className='text-muted-foreground text-xs'>Fit: {item.platforms.length ? item.platforms.map((id) => platformInfo(id)?.label ?? id).join(', ') : 'specialist surface'}</span>
                  </div>
                </div>
                <dl className='text-muted-foreground grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] leading-relaxed'>
                  <dt>id</dt>
                  <dd className='text-foreground font-mono'>{item.id}</dd>
                  <dt>large</dt>
                  <dd className='truncate font-mono' title={art?.large.content_hash}>
                    {art?.large.thumbnail_id} · {art?.large.content_hash.slice(7, 19)}…
                  </dd>
                  <dt>compact</dt>
                  <dd className='truncate font-mono' title={art?.compact.content_hash}>
                    {art?.compact.thumbnail_id} · {art?.compact.content_hash.slice(7, 19)}…
                  </dd>
                  <dt>runs as</dt>
                  <dd className={cn(mapping?.execution === 'planning-only' && 'text-foreground')}>{mapping?.execution === 'planning-only' ? 'Planning only' : `${target} (${mapping?.contentTypeId ?? mapping?.formatId})`}</dd>
                </dl>
                <p className='text-muted-foreground text-[11px] leading-relaxed'>{mapping?.note}</p>
              </article>
            );
          })}
        </section>

        <section aria-label='Legacy fallback' className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-3 sm:max-w-sm'>
          <SemanticIllustration id='legacy-item' size='large' motion={!paused} className='rounded-[0.8125rem]' />
          <div className='flex items-center gap-3'>
            <SemanticIllustration id='legacy-item' size='compact' className='size-12 shrink-0 rounded-[0.8125rem]' />
            <div className='flex flex-col gap-1'>
              <span className='text-base font-medium'>Legacy fallback</span>
              <span className='text-muted-foreground text-xs'>Only for ids the taxonomy no longer carries. {LEGACY_FALLBACK.content_hash.slice(7, 19)}…</span>
            </div>
          </div>
        </section>

        <section aria-label='Categories' className='grid gap-4 sm:grid-cols-2'>
          {(['editorial', 'native'] as const).map((dimension) => (
            <div key={dimension} className='rafii-quiet rounded-[var(--rafii-radius-card)] p-4'>
              <span className='rafii-eyebrow'>{dimension} categories</span>
              <ul className='mt-2 flex flex-col gap-1 text-sm'>
                {CATEGORIES[dimension].map((category) => (
                  <li key={category.id} className='flex items-baseline justify-between gap-3'>
                    <span>
                      {category.label} <span className='text-muted-foreground text-xs'>{category.description}</span>
                    </span>
                    <span className='text-muted-foreground text-xs tabular-nums'>{TAXONOMY.filter((item) => item.dimension === dimension && item.category === category.id).length}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
