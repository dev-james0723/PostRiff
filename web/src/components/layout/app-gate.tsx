'use client';

import { useEffect } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Icons } from '@/components/icons';
import { verifyHref } from '@/lib/auth/navigation';
import { devSignIn, useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { siteConfig } from '@/config/site';

function ShellSkeleton() {
  return (
    <div role='status' aria-label='Loading workspace' className='flex min-h-svh'>
      <div className='hidden w-64 shrink-0 border-r p-4 md:block'>
        <Skeleton className='mb-6 h-10 w-full' />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className='mb-2 h-8 w-full' />
        ))}
      </div>
      <div className='flex flex-1 flex-col gap-4 p-6'>
        <Skeleton className='h-8 w-48' />
        <Skeleton className='h-4 w-80' />
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-4'>
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className='h-28 w-full' />
          ))}
        </div>
        <Skeleton className='h-64 w-full' />
      </div>
    </div>
  );
}

function Problem({
  title,
  description,
  action
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className='flex min-h-svh items-center justify-center p-6'>
      <Empty className='max-w-md'>
        <EmptyHeader>
          <EmptyMedia variant='icon'>
            <Icons.alertCircle />
          </EmptyMedia>
          <EmptyTitle>{title}</EmptyTitle>
          <EmptyDescription>{description}</EmptyDescription>
        </EmptyHeader>
        {action}
      </Empty>
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
        title='PostRiff is temporarily unavailable'
        description={auth.error ?? 'The API did not respond. Please try again in a moment.'}
        action={
          <Button variant='outline' onClick={() => window.location.reload()}>
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
          title='Local dev workspace'
          description='Identity is simulated on this machine. Everything behind it — tenancy, policies, OAuth custody, the ledger — is the real hosted code on a throwaway database.'
          action={
            <Button
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
        title='Your workspace could not be loaded'
        description={workspace.error ?? 'Please try again.'}
        action={
          <div className='flex gap-2'>
            <Button onClick={() => void workspace.refresh()}>Retry</Button>
            <Button variant='outline' onClick={() => void auth.signOut()}>
              Sign out
            </Button>
          </div>
        }
      />
    );
  }

  if (workspace.status !== 'ready' || !workspace.workspaceId) return <ShellSkeleton />;

  return <>{children}</>;
}
