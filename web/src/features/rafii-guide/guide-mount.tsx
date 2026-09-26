'use client';

import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { tourStore } from '@/features/onboarding/store';
import { panelStore } from '@/features/site-agent/store';
import { registerPanelActions } from '@/lib/agent-runtime/panel-actions';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import guideManifestJson from '@/lib/site-agent/guide-manifest.json';
import routeManifestJson from '@/lib/site-agent/route-manifest.json';
import { safeHref, type RouteManifest } from '@/lib/site-agent/routes';
import type { PermissionCheck } from '@/types';
import { guideFor } from './guides';
import { guideStore, useGuideStore } from './store';

const GuideOverlay = dynamic(() => import('./guide-overlay').then((m) => m.GuideOverlay), { ssr: false });

const ROUTES = routeManifestJson as RouteManifest;
const GUIDE_MANIFEST = guideManifestJson as { guides: { id: string; routeId: string; title: string }[] };
/** Matches the docked panel's breakpoint (`features/site-agent/panel.tsx`). */
const DOCK_QUERY = '(min-width: 1024px)';

/** On a tablet or phone Rafii is a sheet over the page: close it so the person sees what Rafii opens or shows. */
function uncoverPage() {
  if (window.matchMedia(DOCK_QUERY).matches) return;
  if (panelStore.get().open) panelStore.setOpen(false);
}

/**
 * Registers what Rafii may do on the page (Contract 4: `navigate`, `startGuide`, `stopGuide`) and mounts the guide
 * overlay once, the first time a guide runs. Mounted once in the app shell, so it outlives page changes.
 */
export function GuideMount() {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const accessRef = useRef(access);
  const running = useGuideStore((s) => s.run !== null);
  const [used, setUsed] = useState(false);

  useEffect(() => {
    accessRef.current = access;
  }, [access]);

  useEffect(() => {
    if (running) setUsed(true);
  }, [running]);

  useEffect(
    () =>
      registerPanelActions({
        navigate: (href) => {
          const allowed = safeHref(ROUTES, href);
          if (!allowed) return;
          guideStore.stop();
          uncoverPage();
          router.push(allowed);
        },
        startGuide: (guideId) => {
          const entry = GUIDE_MANIFEST.guides.find((item) => item.id === guideId);
          const guide = entry ? guideFor(entry.id) : null;
          if (!entry || !guide) return false;
          // A page this person can't open would only lead to "couldn't find": say no up front instead.
          const route = ROUTES.routes.find((item) => item.id === entry.routeId);
          if (route && !checkAccess(accessRef.current, route.access as PermissionCheck)) return false;
          if (tourStore.get().active) tourStore.end('dismissed');
          uncoverPage();
          guideStore.start(guide.id);
          return true;
        },
        stopGuide: () => guideStore.stop()
      }),
    [router]
  );

  return used ? <GuideOverlay /> : null;
}
