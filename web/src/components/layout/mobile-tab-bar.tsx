'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icons } from '@/components/icons';
import { useSidebar } from '@/components/ui/sidebar';
import { navGroups } from '@/config/nav-config';
import { useCoworkerNavGroups } from '@/features/coworker/nav';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import { cn } from '@/lib/utils';

const DESTINATIONS = ['/app', '/app/calendar', '/app/weekly', '/app/queue', '/app/inbox'];

/**
 * The fixed mobile navigation (DNA §8.3): the frequent top-level destinations plus More, on a
 * translucent panel with one selection lens that glides between the five slots.
 */
export function MobileTabBar() {
  const pathname = usePathname();
  const { toggleSidebar } = useSidebar();
  const items = useFilteredNavGroups(useCoworkerNavGroups(navGroups)).flatMap((g) => g.items).filter((i) => DESTINATIONS.includes(i.url));
  const slots = items.length + 1;
  const activeIndex = items.findIndex((item) => (item.url === '/app' ? pathname === item.url : pathname.startsWith(item.url)));
  return (
    <nav
      aria-label='Mobile navigation'
      style={{ ['--slots' as string]: slots }}
      className='rafii-panel fixed inset-x-0 bottom-0 z-30 grid h-[calc(4.25rem+env(safe-area-inset-bottom))] grid-cols-[repeat(var(--slots),minmax(0,1fr))] px-2 pt-1.5 pb-[env(safe-area-inset-bottom)] md:hidden'
    >
      <span
        aria-hidden
        className='rafii-lens rafii-spatial-motion pointer-events-none absolute top-1.5 left-2 h-[3.25rem] w-[calc((100%-1rem)/var(--slots)-0.25rem)] rounded-2xl transition-transform duration-[550ms] ease-[var(--rafii-ease-ui)]'
        style={{ transform: `translateX(calc(${Math.max(0, activeIndex)} * (100% + 0.25rem)))`, opacity: activeIndex < 0 ? 0 : 1 }}
      />
      {items.map((item) => {
        const active = item.url === '/app' ? pathname === item.url : pathname.startsWith(item.url);
        const Icon = item.icon ? Icons[item.icon] : Icons.page;
        return (
          <Link
            key={item.url}
            href={item.url}
            aria-current={active ? 'page' : undefined}
            className={cn('rafii-focus relative z-[1] flex min-h-[3.25rem] min-w-0 flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-medium transition-colors', active ? 'text-foreground' : 'text-muted-foreground')}
          >
            <Icon className='size-5' />
            {item.title}
          </Link>
        );
      })}
      <button type='button' onClick={toggleSidebar} className='rafii-focus text-muted-foreground relative z-[1] flex min-h-[3.25rem] flex-1 flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-medium' aria-label='More navigation'>
        <Icons.menu className='size-5' />
        More
      </button>
    </nav>
  );
}
