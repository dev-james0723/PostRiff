'use client';
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { rafiiCheckbox, rafiiDialog, rafiiInput } from '@/components/auth/form-styles';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { FilterSelect, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { keys, useTokens } from '@/lib/api/hooks';
import type { ApiTokenCreated, WorkspaceApiToken } from '@/lib/api/types';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { SettingsSection } from '../settings-section';

const EXPIRY_OPTIONS = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' }
];

export function TokensCard() {
  const { workspaceId } = useWorkspaceApi();
  // Switching workspace unmounts the one-time reveal and clears its secret.
  return <TokensForWorkspace key={workspaceId} />;
}

/**
 * Personal access tokens (DNA §21.14): the secret is revealed once in the dialog and never in a
 * toast; the list separates saved tokens from their runtime state (active, expired, revoked).
 */
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
    const hidden = () => {
      if (document.visibilityState === 'hidden') clear();
    };
    window.addEventListener('pagehide', clear);
    document.addEventListener('visibilitychange', hidden);
    return () => {
      window.removeEventListener('pagehide', clear);
      document.removeEventListener('visibilitychange', hidden);
      clear();
    };
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
  const list = tokens.data?.tokens ?? [];
  return (
    <SettingsSection
      id='api-tokens'
      title='Personal access tokens'
      description='For your own scripts and agents. Read the workspace; optionally draft and propose schedules. Approval, publishing, replies, account connections and billing stay in the app. Trial plans may use tokens.'
      action={
        <Button variant='action' size='control' data-tour='api-create-token' disabled={busy} onClick={() => setOpen(true)}>
          Create token
        </Button>
      }
      data-tour='api-tokens'
    >
      {tokens.isLoading && <StateMessage kind='loading' layout='inline' title='Loading tokens…' />}
      {tokens.isError && (
        <StateMessage
          kind='error'
          layout='inline'
          title='Tokens are unavailable. No count is shown.'
          action={
            <Button variant='glass' size='sm' className='min-h-9' onClick={() => void tokens.refetch()}>
              Try again
            </Button>
          }
        />
      )}
      {tokens.data && !tokens.isError && (
        <p className='text-muted-foreground text-sm'>
          {list.filter((t) => !t.revokedAt && t.expiresAt > now).length} active tokens
        </p>
      )}
      {tokens.data?.tokens.length === 0 && (
        <StateMessage kind='empty' layout='inline' title='No tokens yet.' description='Every token expires and can be revoked here.' />
      )}
      {list.length > 0 && (
        <ul className='flex flex-col gap-2'>
          {list.map((item) => (
            <li key={item.tokenId} className='rafii-glass flex flex-wrap items-center justify-between gap-3 rounded-[var(--rafii-radius-card)] px-4 py-3'>
              <div className='min-w-0'>
                <p className='text-foreground font-medium break-words'>
                  {item.name}{' '}
                  <span className='text-muted-foreground text-xs font-normal'>
                    {item.revokedAt ? 'Revoked' : item.expiresAt <= now ? 'Expired' : 'Active'}
                  </span>
                </p>
                <p className='text-muted-foreground text-xs'>
                  {item.prefix}… · {item.scopes.includes('draft') ? 'Read, draft and propose' : 'Read only'}
                </p>
                <p className='text-muted-foreground text-xs'>
                  Expires {formatDateTime(item.expiresAt)} · {item.lastUsedAt ? `Last used ${formatDateTime(item.lastUsedAt)}` : 'Never used'}
                </p>
                <p className='text-muted-foreground text-xs'>
                  Created by {item.createdBy} {item.lastUsedClient ? `· ${item.lastUsedClient}` : ''}
                </p>
              </div>
              {!item.revokedAt && (
                <HoldActionButton
                  key={`${item.tokenId}-${epoch}`}
                  holdDuration={900}
                  disabled={busy}
                  className='min-h-11 rounded-[var(--rafii-radius-control)]'
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
      )}
      <details className='text-sm'>
        <summary className='rafii-focus text-foreground -mx-1 inline-flex min-h-9 cursor-pointer items-center rounded-md px-1 font-medium'>Using a token</summary>
        <p className='text-muted-foreground mt-2 leading-relaxed'>
          Send it in the Authorization header as Bearer followed by the token. Keep it in your secret store. Never put it in a URL.
        </p>
        <code className='rafii-quiet mt-2 block rounded-[var(--rafii-radius-micro)] px-2.5 py-1.5 text-xs break-all'>GET /api/workspaces/{workspaceId}</code>
        <p className='text-muted-foreground mt-2 leading-relaxed'>
          Draft scope uses the same writing allowance and source-use confirmations as the app. A schedule proposal is a candidate for a person to approve.
        </p>
      </details>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent className={cn(rafiiDialog, 'gap-5')}>
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className='text-foreground text-xl font-medium tracking-tight'>{revealed ? 'Copy your token now' : 'Create a token'}</DialogTitle>
            <DialogDescription className='leading-relaxed'>
              {revealed
                ? 'This is the only reveal. Closing this dialog clears the secret; create a replacement if you lose it.'
                : 'Creation requires a recent verified sign-in. Every request is limited by both these scopes and your current workspace permissions.'}
            </DialogDescription>
          </DialogHeader>
          {revealed ? (
            <div className='flex flex-col gap-3'>
              <code className='rafii-quiet rounded-[var(--rafii-radius-control)] p-3 font-mono text-xs break-all' data-testid='token-secret'>
                {revealed.secret}
              </code>
              <Button
                variant='action'
                size='control'
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
              <Button variant='glass' size='control' onClick={() => close(false)}>
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
              <div className='flex flex-col gap-2'>
                <Label htmlFor='token-name'>Name</Label>
                <Input id='token-name' maxLength={40} value={name} onChange={(e) => setName(e.target.value)} required className={rafiiInput} />
              </div>
              <FilterSelect id='token-expiry' label='Expires after' value={String(days)} onChange={(value) => setDays(Number(value))} options={EXPIRY_OPTIONS} />
              <Label className='flex min-h-11 cursor-pointer items-center gap-3 font-normal'>
                <input type='checkbox' aria-label='Also allow drafts and schedule proposals' checked={draft} onChange={(e) => setDraft(e.target.checked)} className={rafiiCheckbox} />
                Also allow drafts and schedule proposals
              </Label>
              <p className='text-muted-foreground text-xs leading-relaxed'>
                Read is always included. Draft requests use writing allowance. No token can approve or publish.
              </p>
              <Button variant='action' size='control' disabled={busy || !name.trim()} type='submit'>
                {busy ? 'Creating…' : 'Create and reveal once'}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
