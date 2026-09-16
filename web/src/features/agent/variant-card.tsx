'use client';

import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { RunVariant } from '@/lib/api/types';

/** Local conservative text limits (`postriff_phase2.contracts.LIMITS`; Threads is the platform's own). */
const LIMITS: Record<string, number> = { LinkedIn: 3000, Instagram: 2200, Threads: 500 };

export const destinationLabel = (v: { platform: string; language: string }) => `${v.platform} · ${v.language === '繁體中文' ? '繁中' : 'EN'}`;

export function VariantCard({ variants, selected, onSelect }: { variants: RunVariant[]; selected: number; onSelect: (index: number) => void }) {
  if (variants.length === 0) return null;
  return (
    <div className='bg-card ring-foreground/10 flex flex-col overflow-hidden rounded-xl ring-1'>
      <Tabs value={String(Math.min(selected, variants.length - 1))} onValueChange={(value) => onSelect(Number(value))}>
        <div className='flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2'>
          <TabsList>
            {variants.map((variant, index) => (
              <TabsTrigger key={index} value={String(index)}>
                {destinationLabel(variant)}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {variants.map((variant, index) => {
          const limit = LIMITS[variant.platform];
          const over = limit ? variant.text.length > limit : false;
          return (
            <TabsContent key={index} value={String(index)} className='flex flex-col'>
              <article className='px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap'>{variant.text}</article>
              <div className='bg-background/60 flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2'>
                <div className='flex flex-wrap items-center gap-1.5'>
                  {variant.warnings?.map((warning, i) => (
                    <Badge key={i} variant='outline' className='max-w-full whitespace-normal'>
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
                <span className={over ? 'font-mono text-xs text-red-600' : 'text-muted-foreground font-mono text-xs'}>
                  {variant.text.length}
                  {limit ? ` / ${limit.toLocaleString()}` : ''}
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
