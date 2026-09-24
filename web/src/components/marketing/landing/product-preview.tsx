import { ChannelIcon } from '@/components/channel-icon';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Section } from '@/components/marketing/section';
import { TiltCard } from '@/components/motion/tilt-card';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

const NAV = ['Overview', 'Ideas', 'Automations', 'Calendar', 'Channels', 'Queue', 'Analytics', 'Inbox'];
const DAYS = Array.from({ length: 28 }, (_, i) => i + 1);
/** Event marks are monochrome like the app's calendar chrome (DNA §2.2); the count is how many items sit on that day. */
const DOTS: Record<number, number> = { 3: 1, 5: 2, 9: 1, 12: 1, 16: 2, 19: 1, 24: 1 };
const STATS = [
  ['Scheduled', '7'],
  ['Published · 30d', '23'],
  ['Writing batches', '61'],
  ['Channels', '5']
];
const CHANNEL_ROWS: [string, 'assisted' | 'local', string][] = [
  ['LinkedIn', 'assisted', 'linkedin'],
  ['Threads', 'assisted', 'threads'],
  ['Instagram', 'assisted', 'instagram'],
  ['小紅書', 'local', 'xiaohongshu'],
  ['Bilibili', 'local', 'bilibili']
];

/**
 * Illustrative product frame built from the app's own materials (glass frame, quiet panels, one
 * selected lens in the rail) — not a screenshot. Replace with a real capture at #product-preview
 * once the app is public.
 */
export function ProductPreview() {
  return (
    <Section id='product-preview' eyebrow='Product preview' title='A calm workspace' accent='for a loud job.' description='Everything scheduled, everything that needs you, and what each channel can really do — on one screen.'>
      {/* TiltCard clips to its own radius; the glass fill and shadow sit on it directly. No glare: it is painted in
          --foreground, which reads as a dark smudge over the UI in light themes. Figures stay static. */}
      <TiltCard max={3} glare={false} className='rafii-glass rounded-[var(--rafii-radius-composer)]'>
        <div className='flex items-center gap-2 px-4 py-2.5'>
          <span className='bg-foreground/15 size-2.5 rounded-full' />
          <span className='bg-foreground/15 size-2.5 rounded-full' />
          <span className='bg-foreground/15 size-2.5 rounded-full' />
          <span className='text-muted-foreground ml-3 text-xs'>{siteConfig.name} — Overview</span>
        </div>
        <div className='grid md:grid-cols-[10rem_1fr]'>
          <aside className='rafii-quiet hidden flex-col gap-1 p-3 md:flex' aria-hidden>
            <div className='rafii-quiet mb-2 rounded-[var(--rafii-radius-control)] px-2.5 py-2 text-xs font-medium'>My workspace</div>
            {NAV.map((item, index) => (
              <div key={item} className={cn('rounded-[var(--rafii-radius-control)] px-2.5 py-1.5 text-xs', index === 0 ? 'rafii-lens text-foreground font-medium' : 'text-muted-foreground')}>
                {item}
              </div>
            ))}
          </aside>
          <div className='grid gap-4 p-4 lg:grid-cols-[1fr_16rem]'>
            <div className='flex flex-col gap-3'>
              <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
                {STATS.map(([label, value]) => (
                  <div key={label} className='rafii-quiet rounded-[var(--rafii-radius-card)] p-3'>
                    <p className='text-muted-foreground text-xs'>{label}</p>
                    <p className='text-foreground text-xl font-medium tabular-nums'>{value}</p>
                  </div>
                ))}
              </div>
              <div className='rafii-quiet rounded-[var(--rafii-radius-card)] p-3'>
                <p className='text-foreground mb-2 text-xs font-medium'>September</p>
                <div className='grid grid-cols-7 gap-1'>
                  {DAYS.map((day) => (
                    <div key={day} className='rafii-quiet text-foreground flex h-8 flex-col items-start rounded-[var(--rafii-radius-micro)] p-1 text-[11px] tabular-nums'>
                      {day}
                      <span className='flex gap-0.5'>
                        {Array.from({ length: DOTS[day] ?? 0 }, (_, i) => (
                          <span key={i} className='bg-foreground/60 size-1.5 rounded-full' />
                        ))}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className='rafii-quiet flex flex-col gap-1.5 rounded-[var(--rafii-radius-card)] p-3'>
              <p className='text-foreground mb-1 text-xs font-medium'>Channels</p>
              {CHANNEL_ROWS.map(([name, level, slug]) => (
                <div key={name} className='flex items-center justify-between gap-2 rounded-[var(--rafii-radius-control)] px-2 py-1.5 text-xs'>
                  <span className='text-foreground flex items-center gap-1.5'>
                    <ChannelIcon slug={slug} name={name} size='xs' />
                    {name}
                  </span>
                  <CapabilityBadge level={level} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </TiltCard>
      <p className='text-muted-foreground mt-3 text-xs'>Illustrative layout built from the real interface components; figures are examples.</p>
    </Section>
  );
}
