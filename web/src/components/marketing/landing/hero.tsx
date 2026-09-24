import Link from 'next/link';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Container } from '@/components/marketing/section';
import { ChromaticTextReveal } from '@/components/motion/chromatic-text-reveal';
import { Magnetic } from '@/components/motion/magnetic';
import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/** Platforms cycled in the connector line; each one is a channel in `@/config/channels` (B站 is Bilibili). */
const REWRITE_TARGETS = ['LinkedIn', 'Instagram', '小紅書', 'Threads', 'B站', 'YouTube'];

/** The sweep takes its colours from the active theme's chart tokens, so it follows light/dark and every theme. */
const SWEEP_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'];

/**
 * transitions.dev texts reveal (`.t-stagger-line`, src/styles/transitions.css): each line rises out of a
 * soft blur one stagger step after the previous. It is plain CSS, so the server-rendered hero is readable
 * from first paint instead of waiting for hydration (the headline is this page's largest paint).
 */
const line = (index: number) => ({ '--stagger-i': index }) as React.CSSProperties;

const CANDIDATES = [
  {
    platform: 'LinkedIn',
    slug: 'linkedin',
    language: 'EN',
    level: 'assisted' as const,
    text: 'Three years of piano competitions taught me one thing about practice: the hour you skip is the hour the jury hears.'
  },
  {
    platform: 'Instagram',
    slug: 'instagram',
    language: '繁中',
    level: 'assisted' as const,
    text: '比賽教我的事：你跳過的那一小時，評審聽得出來。今晚練琴。🎹'
  },
  {
    platform: '小紅書',
    slug: 'xiaohongshu',
    language: '繁中',
    level: 'local' as const,
    text: '鋼琴比賽三年，最大的體會｜練習沒有捷徑，但有方法。三個我每天在用的練琴習慣👇'
  }
];

export function Hero() {
  return (
    <section className='border-b' aria-labelledby='hero-title'>
      <Container className='grid gap-12 py-16 sm:py-24 lg:grid-cols-[1.05fr_1fr] lg:items-center'>
        <div className='flex flex-col gap-6'>
          <p style={line(0)} className='t-stagger-line text-primary flex items-center gap-2 text-xs font-semibold tracking-[0.18em] uppercase'>
            <Icons.sparkles className='size-3.5' aria-hidden />
            Your ideas, on every platform
          </p>
          <h1 id='hero-title' style={line(1)} className='t-stagger-line text-4xl font-semibold tracking-tight text-balance sm:text-5xl md:text-6xl'>
            Your AI teammate for social media.
          </h1>
          <p style={line(2)} className='t-stagger-line text-muted-foreground max-w-xl text-lg text-pretty'>
            Prepare drafts from the sources you allow, review and edit each version, then use an available connector or export for manual posting. Automatic publishing depends on the connected account and its verified permissions.
          </p>
          <div style={line(3)} className='t-stagger-line flex flex-wrap items-center gap-3'>
            <Magnetic strength={0.2} className='flex'>
              <Link href={siteConfig.links.signUp} className={buttonVariants({ size: 'lg' })}>
                Start free trial
              </Link>
            </Magnetic>
            <Link href='#how-it-works' className={buttonVariants({ size: 'lg', variant: 'outline' })}>
              See how it works
            </Link>
          </div>
          <p style={line(4)} className='t-stagger-line text-muted-foreground text-sm'>No credit card · 14-day trial · Export everything, any time</p>
        </div>

        <div aria-label='One source becoming three platform-native drafts' className='relative'>
          <div style={line(2)} className='t-stagger-line bg-card rounded-xl border p-4 shadow-xs'>
            <p className='text-muted-foreground mb-2 text-xs font-semibold tracking-[0.14em] uppercase'>01 · Your source</p>
            <p className='text-sm'>
              “Three years of competitions. The lesson wasn’t about talent — it was about the practice hour I kept wanting to skip.”
            </p>
          </div>
          <div style={line(3)} className='t-stagger-line text-muted-foreground my-3 flex items-center gap-2 pl-4 text-xs'>
            <Icons.arrowRight className='size-3.5 rotate-90' aria-hidden />
            <ChromaticTextReveal prefix='Rewritten in your voice for' words={REWRITE_TARGETS} colors={SWEEP_COLORS} foregroundColor='var(--muted-foreground)' duration={1.1} delay={0.3} pauseDuration={1.8} />
          </div>
          <div className='grid gap-3'>
            {CANDIDATES.map((candidate, index) => (
              <div key={candidate.platform} style={line(4 + index)} className='t-stagger-line bg-card flex flex-col gap-2 rounded-xl border p-4 shadow-xs'>
                <div className='flex items-center justify-between gap-2'>
                  <span className='flex items-center gap-2 text-sm font-medium'>
                    <ChannelIcon slug={candidate.slug} name={candidate.platform} size='xs' />
                    {candidate.platform} <span className='text-muted-foreground'>· {candidate.language}</span>
                  </span>
                  <CapabilityBadge level={candidate.level} />
                </div>
                <p className={cn('text-sm', candidate.language === '繁中' && 'font-normal')}>{candidate.text}</p>
              </div>
            ))}
          </div>
          <div style={line(7)} className='t-stagger-line bg-primary text-primary-foreground absolute -right-2 -bottom-3 rounded-full px-3 py-1 text-xs font-medium shadow'>
            You approve → then it publishes
          </div>
        </div>
      </Container>
    </section>
  );
}
