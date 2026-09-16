import Link from 'next/link';
import { Icons } from '@/components/icons';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Container } from '@/components/marketing/section';
import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

const CANDIDATES = [
  {
    platform: 'LinkedIn',
    language: 'EN',
    level: 'assisted' as const,
    text: 'Three years of piano competitions taught me one thing about practice: the hour you skip is the hour the jury hears.'
  },
  {
    platform: 'Instagram',
    language: '繁中',
    level: 'assisted' as const,
    text: '比賽教我的事：你跳過的那一小時，評審聽得出來。今晚練琴。🎹'
  },
  {
    platform: '小紅書',
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
          <p className='text-primary flex items-center gap-2 text-xs font-semibold tracking-[0.18em] uppercase'>
            <Icons.sparkles className='size-3.5' aria-hidden />
            Your ideas, on every platform
          </p>
          <h1 id='hero-title' className='text-4xl font-semibold tracking-tight text-balance sm:text-5xl md:text-6xl'>
            One idea. 30+ platforms, including 小紅書 and B站. Still your voice.
          </h1>
          <p className='text-muted-foreground max-w-xl text-lg text-pretty'>
            PostRiff rewrites a source for each platform and language the way you would, shows you every version, and publishes only what you approve — with a receipt.
          </p>
          <div className='flex flex-wrap items-center gap-3'>
            <Link href={siteConfig.links.signUp} className={buttonVariants({ size: 'lg' })}>
              Start free trial
            </Link>
            <Link href='#how-it-works' className={buttonVariants({ size: 'lg', variant: 'outline' })}>
              See how it works
            </Link>
          </div>
          <p className='text-muted-foreground text-sm'>No credit card · 14-day trial · Export everything, any time</p>
        </div>

        <div aria-label='One source becoming three platform-native drafts' className='relative'>
          <div className='bg-card rounded-xl border p-4 shadow-xs'>
            <p className='text-muted-foreground mb-2 text-xs font-semibold tracking-[0.14em] uppercase'>01 · Your source</p>
            <p className='text-sm'>
              “Three years of competitions. The lesson wasn’t about talent — it was about the practice hour I kept wanting to skip.”
            </p>
          </div>
          <div className='text-muted-foreground my-3 flex items-center gap-2 pl-4 text-xs'>
            <Icons.arrowRight className='size-3.5 rotate-90' aria-hidden />
            rewritten per platform, in your voice
          </div>
          <div className='grid gap-3'>
            {CANDIDATES.map((candidate) => (
              <div key={candidate.platform} className='bg-card flex flex-col gap-2 rounded-xl border p-4 shadow-xs'>
                <div className='flex items-center justify-between gap-2'>
                  <span className='text-sm font-medium'>
                    {candidate.platform} <span className='text-muted-foreground'>· {candidate.language}</span>
                  </span>
                  <CapabilityBadge level={candidate.level} />
                </div>
                <p className={cn('text-sm', candidate.language === '繁中' && 'font-normal')}>{candidate.text}</p>
              </div>
            ))}
          </div>
          <div className='bg-primary text-primary-foreground absolute -right-2 -bottom-3 rounded-full px-3 py-1 text-xs font-medium shadow'>
            You approve → then it publishes
          </div>
        </div>
      </Container>
    </section>
  );
}
