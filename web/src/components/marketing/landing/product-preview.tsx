import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Section } from '@/components/marketing/section';
import { cn } from '@/lib/utils';

const NAV = ['Overview', 'Ideas', 'Calendar', 'Pipeline', 'Channels', 'Queue', 'Analytics', 'Inbox'];
const DAYS = Array.from({ length: 28 }, (_, i) => i + 1);
const DOTS: Record<number, string[]> = { 3: ['bg-sky-500'], 5: ['bg-amber-500', 'bg-sky-500'], 9: ['bg-emerald-500'], 12: ['bg-sky-500'], 16: ['bg-emerald-500', 'bg-emerald-500'], 19: ['bg-amber-500'], 24: ['bg-sky-500'] };

/**
 * Illustrative product frame built from real UI primitives (not a screenshot).
 * Replace with a real capture at #product-preview once the app is public.
 */
export function ProductPreview() {
  return (
    <Section id='product-preview' eyebrow='Product preview' title='A calm workspace for a loud job.' description='Everything scheduled, everything that needs you, and what each channel can really do — on one screen.'>
      <div className='bg-card overflow-hidden rounded-2xl border shadow-sm'>
        <div className='flex items-center gap-2 border-b px-4 py-2'>
          <span className='bg-muted size-2.5 rounded-full' />
          <span className='bg-muted size-2.5 rounded-full' />
          <span className='bg-muted size-2.5 rounded-full' />
          <span className='text-muted-foreground ml-3 text-xs'>app.postriff — Overview</span>
        </div>
        <div className='grid md:grid-cols-[10rem_1fr]'>
          <aside className='hidden flex-col gap-1 border-r p-3 md:flex' aria-hidden>
            <div className='mb-2 rounded-md border px-2 py-1.5 text-xs font-medium'>My workspace</div>
            {NAV.map((item, index) => (
              <div key={item} className={cn('rounded-md px-2 py-1.5 text-xs', index === 0 ? 'bg-accent font-medium' : 'text-muted-foreground')}>
                {item}
              </div>
            ))}
          </aside>
          <div className='grid gap-4 p-4 lg:grid-cols-[1fr_16rem]'>
            <div className='flex flex-col gap-3'>
              <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
                {[
                  ['Scheduled', '7'],
                  ['Published · 30d', '23'],
                  ['Writing batches', '61'],
                  ['Channels', '5']
                ].map(([label, value]) => (
                  <div key={label} className='rounded-lg border p-3'>
                    <p className='text-muted-foreground text-xs'>{label}</p>
                    <p className='text-xl font-semibold tabular-nums'>{value}</p>
                  </div>
                ))}
              </div>
              <div className='rounded-lg border p-3'>
                <p className='mb-2 text-xs font-medium'>September</p>
                <div className='grid grid-cols-7 gap-1'>
                  {DAYS.map((day) => (
                    <div key={day} className='bg-background flex h-8 flex-col items-start rounded border p-1 text-[10px]'>
                      {day}
                      <span className='flex gap-0.5'>
                        {(DOTS[day] ?? []).map((dot, i) => (
                          <span key={i} className={cn('size-1.5 rounded-full', dot)} />
                        ))}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className='flex flex-col gap-2 rounded-lg border p-3'>
              <p className='text-xs font-medium'>Channels</p>
              {[
                ['LinkedIn', 'assisted'],
                ['Threads', 'assisted'],
                ['Instagram', 'assisted'],
                ['小紅書', 'local'],
                ['Bilibili', 'local']
              ].map(([name, level]) => (
                <div key={name} className='flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs'>
                  <span>{name}</span>
                  <CapabilityBadge level={level as 'assisted' | 'local'} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <p className='text-muted-foreground mt-3 text-xs'>Illustrative layout built from the real interface components; figures are examples.</p>
    </Section>
  );
}
