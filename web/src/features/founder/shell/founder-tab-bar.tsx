'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icons } from '@/components/icons';
import { useSidebar } from '@/components/ui/sidebar';
import { FOUNDER_SECTIONS, FOUNDER_TAB_BAR, founderHref, isActiveFounderPath } from '@/config/founder-nav';
import { LAUNCHER_ID, PANEL_ID } from '@/features/founder/agent/panel';
import { founderPanelStore, useFounderPanel } from '@/features/founder/agent/store';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { cn } from '@/lib/utils';
import { useFounderSession } from './founder-session';

/**
 * The phone tab bar (PRD §5.2): Overview, Customers, AI cost, Operations, Rafii, More. The same translucent panel and
 * gliding selection lens as the app's bar; the Rafii slot opens the conversation sheet instead of a page.
 */
export function FounderTabBar() {
  const pathname = usePathname() ?? '/founder';
  const { mode } = useFounderSession();
  const { toggleSidebar } = useSidebar();
  const panelOpen = useFounderPanel((s) => s.open || s.above);
  const items = FOUNDER_TAB_BAR.map((id) => FOUNDER_SECTIONS[id]);
  const slots = items.length + 2;
  const pageIndex = items.findIndex((item) => isActiveFounderPath(pathname, item.url));
  const activeIndex = panelOpen ? items.length : pageIndex;
  const itemClass = 'rafii-focus relative z-[1] flex min-h-[3.25rem] min-w-11 flex-col items-center justify-center gap-1 rounded-2xl text-[10px] font-medium transition-colors min-[360px]:text-[11px]';
  return (
    <nav
      aria-label='Founder navigation'
      style={{ ['--slots' as string]: slots }}
      className='rafii-panel fixed inset-x-0 bottom-0 z-30 grid h-[calc(4.25rem+env(safe-area-inset-bottom))] grid-cols-[repeat(var(--slots),minmax(0,1fr))] px-1 pt-1.5 pb-[env(safe-area-inset-bottom)] md:hidden'
    >
      <span
        aria-hidden
        className='rafii-lens rafii-spatial-motion pointer-events-none absolute top-1.5 left-1 h-[3.25rem] rounded-2xl transition-transform duration-[550ms] ease-[var(--rafii-ease-ui)]'
        style={{
          width: 'calc((100% - 0.5rem) / var(--slots) - 0.25rem)',
          transform: `translateX(calc(${Math.max(0, activeIndex)} * (100% + 0.25rem)))`,
          opacity: activeIndex < 0 ? 0 : 1
        }}
      />
      {items.map((item, index) => {
        const active = !panelOpen && index === pageIndex;
        const Icon = Icons[item.icon];
        return (
          <Link key={item.id} href={founderHref(item.id, mode)} aria-current={active ? 'page' : undefined} className={cn(itemClass, active ? 'text-foreground' : 'text-muted-foreground')}>
            <Icon className='size-5' />
            {item.shortTitle}
          </Link>
        );
      })}
      <button
        type='button'
        id={`${LAUNCHER_ID}-tab`}
        onClick={() => (founderPanelStore.get().above ? founderPanelStore.setAbove(false) : founderPanelStore.toggle())}
        aria-expanded={panelOpen}
        aria-controls={PANEL_ID}
        className={cn(itemClass, panelOpen ? 'text-foreground' : 'text-muted-foreground')}
      >
        <RafiiAvatar size={22} />
        Rafii
      </button>
      <button type='button' onClick={toggleSidebar} className={cn(itemClass, 'text-muted-foreground')} aria-label='More navigation'>
        <Icons.menu className='size-5' />
        More
      </button>
    </nav>
  );
}
