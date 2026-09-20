'use client';

import { useLayoutEffect, useState, type ReactNode } from 'react';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { RunVariant } from '@/lib/api/types';

/** Local conservative text limits (`postriff_phase2.contracts.LIMITS`; Threads is the platform's own). */
const LIMITS: Record<string, number> = { LinkedIn: 3000, Instagram: 2200, Threads: 500 };

export const destinationLabel = (v: { platform: string; language: string }) => `${v.platform} · ${v.language === '繁體中文' ? '繁中' : 'EN'}`;

interface VariantCardProps {
  variants: RunVariant[];
  selected: number;
  onSelect: (index: number) => void;
  /**
   * The draft drawn in its app. Opens from the card below `xl`, where the page's inspector is hidden, and side by
   * side with the other drafts from Compare.
   */
  preview?: (variant: RunVariant, options?: { scale?: number }) => ReactNode;
}

export function VariantCard({ variants, selected, onSelect, preview }: VariantCardProps) {
  const active = Math.min(selected, variants.length - 1);
  // A panel mounts fresh each time its tab opens, so its count starts on the length the reader just saw on the
  // previous tab and rolls to its own before paint. Both numbers are real text lengths.
  const [countFrom, setCountFrom] = useState(active);
  useLayoutEffect(() => {
    setCountFrom(active);
  }, [active]);
  if (variants.length === 0) return null;
  return (
    <div className='bg-card ring-foreground/10 flex flex-col overflow-hidden rounded-xl ring-1'>
      <Tabs value={String(active)} onValueChange={(value) => onSelect(Number(value))} variant='segment' className='flex flex-col gap-2'>
        <div className='flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2'>
          <TabsList className='bg-muted max-w-full flex-wrap'>
            {variants.map((variant, index) => (
              <TabsTrigger key={index} value={String(index)} className='px-3 py-1'>
                {destinationLabel(variant)}
              </TabsTrigger>
            ))}
          </TabsList>
          {preview && variants.length > 1 && <CompareDrafts variants={variants} preview={preview} />}
        </div>
        {variants.map((variant, index) => {
          const limit = LIMITS[variant.platform];
          const over = limit ? variant.text.length > limit : false;
          const shownLength = index === active ? (variants[countFrom] ?? variant).text.length : variant.text.length;
          return (
            <TabsContent key={index} value={String(index)} className='mt-0 flex flex-col'>
              <article className='px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap'>{variant.text}</article>
              <div className='bg-background/60 flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2'>
                <div className='flex flex-wrap items-center gap-1.5'>
                  {variant.warnings?.map((warning, i) => (
                    <Badge key={i} variant='outline' className='h-auto max-w-full justify-start rounded-lg text-left whitespace-normal'>
                      {warning}
                    </Badge>
                  ))}
                  {variant.unknowns.length > 0 && (
                    <Badge variant='outline' className='border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'>
                      {variant.unknowns.length} unknown{variant.unknowns.length === 1 ? '' : 's'} kept out
                    </Badge>
                  )}
                  {variant.candidateOnly && (
                    <Badge variant='outline' className='border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'>
                      Rewritten source · approve public use first
                    </Badge>
                  )}
                </div>
                <span className='flex items-center gap-2'>
                  {preview && (
                    <Popover>
                      <PopoverTrigger render={<Button variant='ghost' size='sm' className='xl:hidden' />}>
                        <Icons.eye />
                        Preview
                      </PopoverTrigger>
                      <PopoverContent align='end' className='w-auto max-w-[calc(100vw-1rem)]'>
                        <div className='max-h-[calc(var(--available-height,100vh)-1.5rem)] overflow-y-auto'>{preview(variant)}</div>
                      </PopoverContent>
                    </Popover>
                  )}
                  <span className={over ? 'inline-flex items-center font-mono text-xs text-red-600' : 'text-muted-foreground inline-flex items-center font-mono text-xs'}>
                    <DigitSwap value={shownLength} />
                    {limit ? <span className='whitespace-pre'>{` / ${limit.toLocaleString()}`}</span> : null}
                  </span>
                </span>
              </div>
              {variant.unknowns.length > 0 && (
                <ul className='text-muted-foreground list-disc border-t px-4 py-2 pl-8 text-xs'>
                  {variant.unknowns.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              )}
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}

/** Every draft in its own app, side by side, so the versions can be read against each other. */
function CompareDrafts({ variants, preview }: { variants: RunVariant[]; preview: NonNullable<VariantCardProps['preview']> }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant='ghost' size='sm' />}>
        <Icons.columns />
        Compare
      </DialogTrigger>
      {/* w-max: a centred fixed box sized by its content would otherwise only get half the viewport. */}
      <DialogContent className='max-h-[calc(100dvh-2rem)] w-max grid-rows-[auto_minmax(0,1fr)] sm:max-w-[calc(100%-2rem)]'>
        <DialogHeader>
          <DialogTitle>Compare drafts</DialogTitle>
          <DialogDescription>Each draft in its app. Scroll sideways when they do not all fit.</DialogDescription>
        </DialogHeader>
        <div className='-mx-4 flex min-w-0 snap-x gap-6 overflow-auto px-4 pb-1'>
          {variants.map((variant, index) => (
            <section key={index} aria-label={destinationLabel(variant)} className='flex shrink-0 snap-center flex-col items-center gap-2'>
              <h3 className='flex items-center gap-1.5 text-xs font-medium'>
                <ChannelIcon platform={variant.platform} name={variant.platform} size='sm' />
                {destinationLabel(variant)}
              </h3>
              {preview(variant, { scale: 0.5 })}
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
