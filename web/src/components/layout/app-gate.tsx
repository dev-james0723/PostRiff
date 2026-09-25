'use client';

import { useEffect } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Icons } from '@/components/icons';
import { StateMessage, type StateKind } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { verifyHref } from '@/lib/auth/navigation';
import { devSignIn, useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { siteConfig } from '@/config/site';

/** Stable geometry while the session and workspace load (DNA §20.1): the rail, a heading and quiet blocks. */
function ShellSkeleton() {
  return (
    <div role='status' aria-label='Loading workspace' className='flex min-h-svh'>
      <div className='rafii-panel hidden w-64 shrink-0 p-4 md:block'>
        <Skeleton className='mb-6 h-12 w-full rounded-[var(--rafii-radius-control)]' />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className='mb-2 h-9 w-full rounded-[var(--rafii-radius-control)]' />
        ))}
      </div>
      {/* min-w-0: the fixed-width placeholders must not widen the column past a 320px screen. */}
      <div className='flex min-w-0 flex-1 flex-col gap-4 p-4 md:p-8'>
        <Skeleton className='h-8 w-48' />
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-4'>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className='rafii-quiet h-28 w-full rounded-[var(--rafii-radius-card)]' />
          ))}
        </div>
        <div className='rafii-quiet h-64 w-full rounded-[var(--rafii-radius-card)]' />
      </div>
    </div>
  );
}

/**
 * One gate state on the ambient canvas, in the shared state grammar (§20.4: errors keep the design language).
 * The headline says what happened and the action what to do; the raw error, when there is one, stays
 * available under Details instead of becoming the message.
 */
function Problem({
  kind,
  title,
  description,
  detail,
  action,
  media
}: {
  kind: StateKind;
  title: string;
  description?: string;
  detail?: string | null;
  action?: React.ReactNode;
  media?: React.ReactNode;
}) {
  // In the action row (a <div>), not the description (a <p>, which cannot hold <details>); basis-full puts it on its own line.
  const details = detail ? (
    <details className='text-muted-foreground basis-full text-xs'>
      <summary className='rafii-focus cursor-pointer rounded-sm'>Details</summary>
      <p className='mt-1 break-words'>{detail}</p>
    </details>
  ) : null;
  return (
    <div className='relative isolate flex min-h-svh items-center justify-center p-6'>
      <div aria-hidden className='rafii-ambient' />
      <StateMessage
        kind={kind}
        title={title}
        description={description}
        action={action || details ? <>{action}{details}</> : undefined}
        media={media}
        className='rafii-glass w-full max-w-md'
      />
    </div>
  );
}

/**
 * Renders children only with a signed-in user and a ready workspace.
 * Supabase deployments are also gated server-side by `src/proxy.ts`; this
 * component covers the dev harness and client-side session loss.
 */
export function AppGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();

  const signInHref = `${siteConfig.links.signIn}?next=${encodeURIComponent(
    `${pathname}${search.size ? `?${search.toString()}` : ''}`
  )}`;

  useEffect(() => {
    if (auth.status === 'signed-out' && auth.mode === 'supabase') {
      router.replace(signInHref);
    } else if (auth.status === 'mfa-required') {
      router.replace(verifyHref(`${pathname}${search.size ? `?${search.toString()}` : ''}`));
    }
  }, [auth.status, auth.mode, router, signInHref, pathname, search]);

  if (auth.status === 'loading') return <ShellSkeleton />;

  // A second factor is enrolled and this session has not shown it: the API would refuse every call.
  if (auth.status === 'mfa-required') return <ShellSkeleton />;

  if (auth.status === 'unavailable') {
    return (
      <Problem
        kind='offline'
        title={`Couldn’t reach ${siteConfig.name}`}
        description='Check your connection and try again.'
        detail={auth.error}
        action={
          <Button variant='glass' size='control' onClick={() => window.location.reload()}>
            Try again
          </Button>
        }
      />
    );
  }

  if (auth.status === 'signed-out') {
    if (auth.mode === 'dev') {
      return (
        <Problem
          kind='empty'
          media={
            <span aria-hidden className='rafii-glass text-foreground flex size-11 items-center justify-center rounded-full'>
              <Icons.terminal className='size-5' />
            </span>
          }
          title='Local dev workspace'
          description='Identity is simulated on this machine. Everything behind it — tenancy, policies, OAuth custody, the ledger — is the real hosted code on a throwaway database.' // copy-audit: allow (local dev mode only)
          action={
            <Button
              variant='action'
              size='control'
              onClick={() => {
                devSignIn();
                window.location.reload();
              }}
            >
              Enter dev workspace
            </Button>
          }
        />
      );
    }
    return <ShellSkeleton />;
  }

  if (workspace.status === 'error') {
    return (
      <Problem
        kind='error'
        title='Couldn’t load your workspace'
        detail={workspace.error}
        action={
          <>
            <Button variant='action' size='control' onClick={() => void workspace.refresh()}>
              Try again
            </Button>
            <Button variant='glass' size='control' onClick={() => void auth.signOut()}>
              Sign out
            </Button>
          </>
        }
      />
    );
  }

  if (workspace.status !== 'ready' || !workspace.workspaceId) return <ShellSkeleton />;

  return <>{children}</>;
}
