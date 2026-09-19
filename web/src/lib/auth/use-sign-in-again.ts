'use client';

import { usePathname, useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { siteConfig } from '@/config/site';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { needsFreshSignIn } from './step-up';

/** A signed-in visit to /sign-in redirects back, so step-up starts by ending that session. */
export function useSignInAgain() {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  return async () => {
    try {
      await auth.signOut();
    } catch {
      toast.error('Signing out did not finish. Use Sign out in the account menu, then sign in again.');
      return false;
    }
    router.replace(`${siteConfig.links.signIn}?next=${encodeURIComponent(pathname)}`);
    return true;
  };
}

export function useChangeError() {
  const signInAgain = useSignInAgain();
  return (error: unknown, fallback: string) => {
    if (needsFreshSignIn(error)) {
      toast.error((error as ApiError).message, {
        description: 'After you sign in again, you come back to this page to retry.',
        action: { label: 'Sign out and sign in again', onClick: () => void signInAgain() }
      });
    } else {
      toast.error(error instanceof ApiError ? error.message : fallback);
    }
  };
}
