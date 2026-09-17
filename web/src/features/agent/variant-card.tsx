'use client';

import { useLayoutEffect, useState } from 'react';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import type { RunVariant } from '@/lib/api/types';
import { languageLabel, textAttributes, textLength } from '@/lib/locales';

/** Local conservative text limits (`postriff_phase2.contracts.LIMITS`; Threads is the platform's own). */
const LIMITS: Record<string, number> = { LinkedIn: 3000, Instagram: 2200, Threads: 500, Xiaohongshu: 1000 };

export const destinationLabel = (v: { platform: string; language: string }) => `${v.platform} · ${languageLabel(v.language)}`;

/** A channel mark, its name and the draft's language: a channel can carry the same platform in several languages. */
export function Destination({ platform, language }: { platform: string; language: string }) {
  return (
    <span className='inline-flex min-w-0 items-center gap-1.5'>
      <ChannelIcon platform={platform} size='xs' />
      <span>{platform}</span>
      <LanguageName language={language} className='text-muted-foreground font-normal' />
    </span>
  );
}

export function VariantCard({ variants, selected, onSelect }: { variants: RunVariant[]; selected: number; onSelect: (index: number) => void }) {
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
                <Destination platform={variant.platform} language={variant.language} />
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {variants.map((variant, index) => {
          const limit = LIMITS[variant.platform];
          const over = limit ? textLength(variant.text) > limit : false;
          const shownLength = index === active ? textLength((variants[countFrom] ?? variant).text) : textLength(variant.text);
          return (
            <TabsContent key={index} value={String(index)} className='mt-0 flex flex-col'>
              <article {...textAttributes(variant.language)} className='px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap'>
                {variant.text}
              </article>
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
                <span className={over ? 'inline-flex items-center font-mono text-xs text-red-600' : 'text-muted-foreground inline-flex items-center font-mono text-xs'}>
                  <DigitSwap value={shownLength} />
                  {limit ? <span className='whitespace-pre'>{` / ${limit.toLocaleString()}`}</span> : null}
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
