'use client';
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { keys, useTokens } from '@/lib/api/hooks';
import type { ApiTokenCreated, WorkspaceApiToken } from '@/lib/api/types';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { formatDateTime } from '@/lib/time';

export function TokensCard() {
  const { workspaceId } = useWorkspaceApi();
  // Switching workspace unmounts the one-time reveal and clears its secret.
  return <TokensForWorkspace key={workspaceId} />;
}
function TokensForWorkspace() {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const tokens = useTokens();
  const reportError = useChangeError();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [days, setDays] = useState(30);
  const [draft, setDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState<ApiTokenCreated | null>(null);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const clear = () => setRevealed(null);
    const hidden = () => { if (document.visibilityState === 'hidden') clear(); };
    window.addEventListener('pagehide', clear);
    document.addEventListener('visibilitychange', hidden);
    return () => { window.removeEventListener('pagehide', clear); document.removeEventListener('visibilitychange', hidden); clear(); };
  }, []);

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: keys.tokens(workspaceId) }),
      client.invalidateQueries({ queryKey: keys.audit(workspaceId) })
    ]);
  }
  async function create() {
    setBusy(true);
    try {
      // Deliberately bypass mutation/query caches: the secret lives only in this reveal state.
      const result = await api.createToken(workspaceId, {
        name,
        scopes: draft ? ['read', 'draft'] : ['read'],
        expiresDays: days
      });
      setRevealed(result);
      await refresh();
    } catch (error) {
      reportError(error, 'The token could not be created.');
    } finally {
      setBusy(false);
    }
  }
  async function revoke(item: WorkspaceApiToken) {
    setBusy(true);
    try {
      await api.revokeToken(workspaceId, item.tokenId);
      await refresh();
      toast.success('Token revoked.');
    } catch (error) {
      reportError(error, 'The token could not be revoked.');
    } finally {
      setBusy(false);
      setEpoch((n) => n + 1);
    }
  }
  function close(next: boolean) {
    if (busy) return;
    setOpen(next);
    if (!next) {
      setRevealed(null);
      setName('');
    }
  }
  const now = Date.now() / 1000;
  return (
    <Card data-tour='api-tokens'>
      <CardHeader>
        <CardTitle>Personal access tokens</CardTitle>
        <CardDescription>
          For your own scripts and agents. Read the workspace; optionally draft and propose
          schedules. Approval, publishing, replies, account connections and billing stay in the app.
          Trial plans may use tokens.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <Button
          className='self-start'
          data-tour='api-create-token'
          disabled={busy}
          onClick={() => setOpen(true)}
        >
          Create token
        </Button>
        {tokens.isLoading && <p role='status'>Loading tokens…</p>}
        {tokens.isError && (
          <div role='alert'>
            <p>Tokens are unavailable. No count is shown.</p>
            <Button variant='outline' onClick={() => void tokens.refetch()}>
              Try again
            </Button>
          </div>
        )}
        {tokens.data && !tokens.isError && (
          <p className='text-muted-foreground text-sm'>
            {tokens.data.tokens.filter((t) => !t.revokedAt && t.expiresAt > now).length} active
            tokens
          </p>
        )}
        {tokens.data?.tokens.length === 0 && (
          <p className='text-muted-foreground text-sm'>
            No tokens yet. Every token expires and can be revoked here.
          </p>
        )}
        <ul className='divide-y'>
          {tokens.data?.tokens.map((item) => (
            <li
              key={item.tokenId}
              className='flex flex-wrap items-center justify-between gap-3 py-3'
            >
              <div className='min-w-0'>
                <p className='font-medium break-words'>
                  {item.name}{' '}
                  <span className='text-muted-foreground text-xs'>
                    {item.revokedAt ? 'Revoked' : item.expiresAt <= now ? 'Expired' : 'Active'}
                  </span>
                </p>
                <p className='text-muted-foreground text-xs'>
                  {item.prefix}… ·{' '}
                  {item.scopes.includes('draft') ? 'Read, draft and propose' : 'Read only'}
                </p>
                <p className='text-muted-foreground text-xs'>
                  Expires {formatDateTime(item.expiresAt)} ·{' '}
                  {item.lastUsedAt ? `Last used ${formatDateTime(item.lastUsedAt)}` : 'Never used'}
                </p>
                <p className='text-muted-foreground text-xs'>
                  Created by {item.createdBy}{' '}
                  {item.lastUsedClient ? `· ${item.lastUsedClient}` : ''}
                </p>
              </div>
              {!item.revokedAt && (
                <HoldActionButton
                  key={`${item.tokenId}-${epoch}`}
                  holdDuration={900}
                  disabled={busy}
                  className='min-h-11'
                  onHoldComplete={() => void revoke(item)}
                  holdingLabel='Keep holding…'
                  completeLabel='Revoking…'
                  aria-label={`Hold to revoke ${item.name}`}
                >
                  Hold to revoke
                </HoldActionButton>
              )}
            </li>
          ))}
        </ul>
        <details className='text-sm'>
          <summary className='cursor-pointer'>Using a token</summary>
          <p className='text-muted-foreground mt-2'>
            Send it in the Authorization header as Bearer followed by the token. Keep it in your
            secret store. Never put it in a URL.
          </p>
          <code className='mt-2 block break-all text-xs'>GET /api/workspaces/{workspaceId}</code>
          <p className='text-muted-foreground mt-2'>
            Draft scope uses the same writing allowance and source-use confirmations as the app. A
            schedule proposal is a candidate for a person to approve.
          </p>
        </details>
      </CardContent>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{revealed ? 'Copy your token now' : 'Create a token'}</DialogTitle>
            <DialogDescription>
              {revealed
                ? 'This is the only reveal. Closing this dialog clears the secret; create a replacement if you lose it.'
                : 'Creation requires a recent verified sign-in. Every request is limited by both these scopes and your current workspace permissions.'}
            </DialogDescription>
          </DialogHeader>
          {revealed ? (
            <div className='flex flex-col gap-3'>
              <code
                className='bg-muted rounded-md p-3 text-xs break-all'
                data-testid='token-secret'
              >
                {revealed.secret}
              </code>
              <Button
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(revealed.secret);
                    toast.success('Token copied.');
                  } catch {
                    toast.error('Copy failed. Select and copy the token manually.');
                  }
                }}
              >
                Copy token
              </Button>
              <Button variant='outline' onClick={() => close(false)}>
                I have saved it
              </Button>
            </div>
          ) : (
            <form
              className='flex flex-col gap-4'
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <div>
                <Label htmlFor='token-name'>Name</Label>
                <Input
                  id='token-name'
                  maxLength={40}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>
              <div>
                <Label htmlFor='token-expiry'>Expires after</Label>
                <select
                  id='token-expiry'
                  className='border-input mt-1 block h-10 w-full rounded-md border px-3'
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                >
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={365}>1 year</option>
                </select>
              </div>
              <Label className='flex gap-2'>
                <input
                  type='checkbox'
                    aria-label='Also allow drafts and schedule proposals'
                  checked={draft}
                  onChange={(e) => setDraft(e.target.checked)}
                />
                Also allow drafts and schedule proposals
              </Label>
              <p className='text-muted-foreground text-xs'>
                Read is always included. Draft requests use writing allowance. No token can approve
                or publish.
              </p>
              <Button disabled={busy || !name.trim()} type='submit'>
                {busy ? 'Creating…' : 'Create and reveal once'}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
