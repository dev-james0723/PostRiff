'use client';
import type { Action } from 'kbar';
import { navGroups } from '@/config/nav-config';
import { KBarAnimator, KBarPortal, KBarPositioner, KBarProvider, KBarSearch, useRegisterActions } from 'kbar';
import { tourStore } from '@/features/onboarding/store';
import { pageTourFor } from '@/features/onboarding/tours';
import { Icons } from '@/components/icons';
import { Kbd } from '@/components/ui/kbd';
import { usePathname, useRouter } from 'next/navigation';
import { useMemo } from 'react';
import RenderResults from './render-result';
import useThemeSwitching from './use-theme-switching';
import { useFilteredNavGroups } from '@/hooks/use-nav';

export default function KBar({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const filteredGroups = useFilteredNavGroups(navGroups);

  // These action are for the navigation
  const actions = useMemo(() => {
    // Define navigateTo inside the useMemo callback to avoid dependency array issues
    const navigateTo = (url: string) => {
      router.push(url);
    };

    const allItems = filteredGroups.flatMap((group) => group.items);

    const navActions = allItems.flatMap((navItem) => {
      // Only include base action if the navItem has a real URL and is not just a container
      const baseAction =
        navItem.url !== '#'
          ? {
              id: `${navItem.title.toLowerCase()}Action`,
              name: navItem.title,
              shortcut: navItem.shortcut,
              keywords: navItem.title.toLowerCase(),
              section: 'Navigation',
              perform: () => navigateTo(navItem.url)
            }
          : null;

      // Map child items into actions
      const childActions =
        navItem.items?.map((childItem) => ({
          id: `${childItem.title.toLowerCase()}Action`,
          name: childItem.title,
          shortcut: childItem.shortcut,
          keywords: childItem.title.toLowerCase(),
          section: navItem.title,
          perform: () => navigateTo(childItem.url)
        })) ?? [];

      // Return only valid actions (ignoring null base actions for containers)
      return baseAction ? [baseAction, ...childActions] : childActions;
    });

    return navActions;
  }, [router, filteredGroups]);

  return (
    <KBarProvider>
      <NavigationActions actions={actions} />
      <KBarComponent>{children}</KBarComponent>
    </KBarProvider>
  );
}
/**
 * Onboarding entries (the same as the header's help menu), registered from inside the provider so
 * "Tips for …" follows the current route; the provider only reads its `actions` prop once.
 */
function useHelpActions() {
  const pathname = usePathname();
  const pageTour = pageTourFor(pathname);
  const actions = useMemo(
    () => [
      {
        id: 'tourWelcomeAction',
        name: 'Take the tour',
        keywords: 'help tour onboarding tutorial guide walkthrough',
        section: 'Help',
        subtitle: 'Two minutes',
        perform: () => tourStore.start('welcome')
      },
      {
        id: 'tourResetAction',
        name: 'Reset tips',
        keywords: 'help tips tour reset onboarding show again',
        section: 'Help',
        subtitle: 'Show tips again',
        perform: () => tourStore.reset()
      },
      ...(pageTour
        ? [
            {
              id: 'tourPageAction',
              name: `Tips for ${pageTour.title}`,
              keywords: 'help tips how this page works',
              section: 'Help',
              subtitle: 'How this page works',
              perform: () => tourStore.start(pageTour.id)
            }
          ]
        : [])
    ],
    [pageTour]
  );
  useRegisterActions(actions, [actions]);
}

const KBarComponent = ({ children }: { children: React.ReactNode }) => {
  useThemeSwitching();
  useHelpActions();

  return (
    <>
      <KBarPortal>
        <KBarPositioner className='rafii-scrim fixed inset-0 z-99999 flex items-start! justify-center p-4! pt-[14vh]!'>
          <KBarAnimator className='rafii-elevated text-foreground relative mx-auto w-full max-w-[600px] overflow-hidden rounded-[var(--rafii-radius-dialog)]'>
            <div className='sticky top-0 z-10 flex items-center gap-3 px-5 pt-4 pb-3'>
              <Icons.search aria-hidden className='text-muted-foreground size-4 shrink-0' />
              <KBarSearch className='placeholder:text-muted-foreground min-w-0 flex-1 border-none bg-transparent py-1.5 text-base outline-hidden focus:ring-0 focus:outline-hidden md:text-sm' />
            </div>
            <div className='h-[400px] pb-1'>
              <RenderResults />
            </div>
            <div className='text-muted-foreground flex items-center gap-3 px-5 pt-2 pb-3 text-xs'>
              <span className='flex items-center gap-1'>
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> navigate
              </span>
              <span className='flex items-center gap-1'>
                <Kbd>↵</Kbd> open
              </span>
              <span className='flex items-center gap-1'>
                <Kbd>esc</Kbd> close
              </span>
            </div>
          </KBarAnimator>
        </KBarPositioner>
      </KBarPortal>
      {children}
    </>
  );
};

function NavigationActions({ actions }: { actions: Action[] }) {
  useRegisterActions(actions, [actions]);
  return null;
}
