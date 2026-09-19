'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icons } from '@/components/icons';
import { useSidebar } from '@/components/ui/sidebar';
import { navGroups } from '@/config/nav-config';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import { cn } from '@/lib/utils';

const DESTINATIONS = ['/app', '/app/calendar', '/app/queue', '/app/inbox'];
export function MobileTabBar() {
  const pathname = usePathname();
  const { toggleSidebar } = useSidebar();
  const items = useFilteredNavGroups(navGroups).flatMap((g) => g.items).filter((i) => DESTINATIONS.includes(i.url));
  return <nav aria-label='Mobile navigation' className='bg-background fixed inset-x-0 bottom-0 z-30 flex border-t pb-[env(safe-area-inset-bottom)] md:hidden'>
    {items.map((item) => {
      const active = item.url === '/app' ? pathname === item.url : pathname.startsWith(item.url);
      const Icon = item.icon ? Icons[item.icon] : Icons.page;
      return <Link key={item.url} href={item.url} aria-current={active ? 'page' : undefined} className={cn('flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-1 text-[11px]', active ? 'text-primary bg-primary/5' : 'text-muted-foreground')}><Icon className='size-5' />{item.title}</Link>;
    })}
    <button type='button' onClick={toggleSidebar} className='text-muted-foreground flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px]' aria-label='More navigation'><Icons.menu className='size-5' />More</button>
  </nav>;
}
