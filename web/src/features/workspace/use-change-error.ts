'use client';

import { usePathname, useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { siteConfig } from '@/config/site';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { needsFreshSignIn } from './access-model';

/**
 * Error toast for a refused member change, shared by the Roles and Members pages.
 *
 * A stale sign-in (`assert_fresh`) gets a way out that works: the sign-in page sends a
 * signed-in visitor straight back to `next` (components/auth/auth-form.tsx), so a fresh
 * sign-in has to start by signing out, as the account deletion card does
 * (features/account/privacy/delete-card.tsx).
 */
export function useChangeError() {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  async function signInAgain() {
    try {
      await auth.signOut();
    } catch {
      toast.error('Signing out did not finish. Use Sign out in the account menu, then sign in again.');
      return;
    }
    router.replace(`${siteConfig.links.signIn}?next=${encodeURIComponent(pathname)}`);
  }

  return (err: unknown, fallback: string) => {
    if (needsFreshSignIn(err)) {
      toast.error((err as ApiError).message, {
        description: 'Nothing changed. After you sign in again you come back to this page.',
        action: { label: 'Sign out and sign in again', onClick: () => void signInAgain() }
      });
      return;
    }
    toast.error(err instanceof ApiError ? err.message : fallback);
  };
}
