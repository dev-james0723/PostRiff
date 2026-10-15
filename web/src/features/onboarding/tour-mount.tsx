'use client';

import { useEffect } from 'react';
import { permissionsUiEnabled } from '@/lib/agent-permissions/model';
import { usePathname } from 'next/navigation';
import { toast } from 'sonner';
import { guideStore, useGuideStore } from '@/features/rafii-guide/store';
import { useAuth } from '@/lib/auth/session';
import { tourStore, useTourStore } from './store';
import dynamic from 'next/dynamic';
const TourOverlay = dynamic(() => import('./tour-overlay').then((m) => m.TourOverlay), { ssr: false });
import { pageTourFor, WELCOME_TOUR } from './tours';
import { useTourContext } from './use-tour-context';
const PermissionReminder = dynamic(() => import('@/features/account/agent/permission-reminder').then((m) => m.PermissionReminder), { ssr: false });
const WelcomeDialog = dynamic(() => import('./welcome-dialog').then((m) => m.WelcomeDialog), { ssr: false });

/**
 * Everything onboarding mounts from the app template: the first-run welcome, the one-time
 * nudge a page gets when it has tips, and the tour overlay itself. Nothing here blocks work:
 * the welcome is a dialog with "Not now", and a nudge is a toast.
 *
 * Someone whose workspace is already set up (voice, a channel, a scheduled post) is not
 * interrupted by the welcome dialog; they get one quiet offer of the tour instead.
 *
 * A tour and one of Rafii's guided walkthroughs (`features/rafii-guide`) never run together:
 * starting a tour stops the guide, and nothing here offers a tour while Rafii is showing the way.
 */
export function TourMount() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { ctx, ready } = useTourContext();
  const active = useTourStore((s) => s.active);
  const progress = useTourStore((s) => s.progress);
  const progressReady = useTourStore((s) => s.progressReady);
  const guiding = useGuideStore((s) => s.run !== null);

  const userId = user?.id ?? null;
  useEffect(() => {
    tourStore.bindUser(userId);
  }, [userId]);

  useEffect(() => {
    if (active) guideStore.stop();
  }, [active]);

  const inApp = pathname.startsWith('/app') && !pathname.startsWith('/app/agent/');
  const welcomeDecided = Boolean(progress.completed.welcome || progress.dismissed.welcome);
  const alreadySetUp = ctx.hasVoice === true && (ctx.channelCount ?? 0) > 0 && (ctx.jobCount ?? 0) > 0;
  const showWelcome = progressReady && ready && inApp && !active && !guiding && !welcomeDecided && !alreadySetUp;

  useEffect(() => {
    if (!progressReady || !ready || !inApp || active || guiding || welcomeDecided || !alreadySetUp) return;
    tourStore.dismissWithoutStarting('welcome');
    toast('Want a quick tour?', {
      action: { label: 'Take the tour', onClick: () => tourStore.start('welcome') },
      duration: 8000
    });
  }, [progressReady, ready, inApp, active, guiding, welcomeDecided, alreadySetUp]);

  const pageTour = pageTourFor(pathname);
  const pageTourId = pageTour?.id ?? null;
  const pageTitle = pageTour?.title ?? '';
  useEffect(() => {
    if (!progressReady || !ready || !pageTourId || active || !welcomeDecided) return;
    if (progress.nudged[pageTourId] || progress.completed[pageTourId]) return;
    // A finished welcome tour already walked through this page; its tips stay in the help menu.
    if (progress.completed.welcome && WELCOME_TOUR.steps.some((s) => s.route === pathname)) return;
    tourStore.markNudged(pageTourId);
    // Rafii is already showing this page: no second offer on top of it.
    if (guiding) return;
    toast(`New to ${pageTitle}?`, {
      action: { label: 'Show me', onClick: () => tourStore.start(pageTourId) },
      duration: 8000
    });
  }, [progressReady, ready, pageTourId, pageTitle, active, guiding, welcomeDecided, progress, pathname]);

  return (
    <>
      {showWelcome && <WelcomeDialog
        open={showWelcome}
        onStart={() => tourStore.start('welcome')}
        onDismiss={() => tourStore.dismissWithoutStarting('welcome')}
      />}
      {active && <TourOverlay />}
      {permissionsUiEnabled() && progressReady && ready && inApp && welcomeDecided && !showWelcome && !active && !guiding && pathname !== '/app/account/agent' && <PermissionReminder />}
    </>
  );
}
