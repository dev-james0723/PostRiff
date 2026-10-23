'use client';

import { useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ApiError } from '@/lib/api/client';
import { needsFreshSignIn } from '@/lib/auth/step-up';
import { reportStepUp } from '@/lib/auth/security-step-up';
import { useSignInAgain } from '@/lib/auth/use-sign-in-again';
import type { ChannelView, DiscordSenderProfile } from '@/lib/api/types';
import { keys } from '@/lib/api/hooks';
import { discordCopy } from '@/lib/channels/discord-copy';
import { usePreferences } from '@/lib/preferences';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_44, DIALOG_ELEVATED, DIALOG_FOOTER_PLAIN } from './rafii-materials';

export function DiscordSenderNameControl({ channel }: { channel: ChannelView }) {
  const { workspaceId } = useWorkspaceApi();
  return <SenderNameEditor key={`${workspaceId}:${channel.id}`} channel={channel} />;
}

function SenderNameEditor({ channel }: { channel: ChannelView }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const copy = discordCopy(usePreferences().locale);
  const signInAgain = useSignInAgain();
  const id = useId();
  const request = useRef(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<DiscordSenderProfile | null>(null);
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const isBot = profile?.senderKind === 'bot';
  const validName = Boolean(
    profile &&
    name.trim() === name &&
    name.length > 0 &&
    Array.from(name).length <= profile.maxLength
  );

  async function run(action: () => Promise<DiscordSenderProfile>) {
    const current = ++request.current;
    setBusy(true);
    setError(null);
    setSaved(false);
    setNeedsSignIn(false);
    try {
      const next = await action();
      if (current !== request.current) return;
      setProfile(next);
      setName(next.name);
      setShared(false);
      return next;
    } catch (cause) {
      if (current !== request.current) return;
      setProfile(null);
      if (reportStepUp(cause)) {
        setError(copy.senderSessionError);
      } else if (needsFreshSignIn(cause)) {
        setNeedsSignIn(true);
        setError(copy.senderSessionError);
      } else {
        setError(
          cause instanceof ApiError && cause.code === 'discord_sender_edit_pending'
            ? copy.senderChangePending
            : cause instanceof ApiError && cause.status === 403
              ? copy.senderPermissionError
              : copy.senderSaveFailed
        );
      }
    } finally {
      if (current === request.current) setBusy(false);
    }
  }

  function show() {
    setProfile(null);
    setName('');
    setShared(false);
    setOpen(true);
    void run(() => api.discordSenderProfile(workspaceId, channel.id));
  }

  async function save() {
    if (!profile || !validName || (isBot && !shared)) return;
    const updated = await run(() =>
      api.setDiscordSenderName(workspaceId, channel.id, {
        name,
        fingerprint: profile.fingerprint,
        confirmed: true,
        ...(isBot ? { sharedServerConfirmed: shared } : {})
      })
    );
    if (!updated) return;
    setSaved(true);
    void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
    void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
  }

  return (
    <>
      <Button
        variant='glass'
        className={CONTROL_44}
        aria-label={`${copy.senderEdit} · ${channel.account}`}
        onClick={show}
        disabled={busy}
      >
        {copy.senderEdit}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (busy) return;
          setOpen(value);
          if (!value) {
            request.current++;
            setProfile(null);
            setError(null);
            setSaved(false);
          }
        }}
      >
        <DialogContent
          showCloseButton={false}
          className={cn(DIALOG_ELEVATED, 'max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg')}
        >
          <DialogHeader>
            <DialogTitle>{copy.senderEdit}</DialogTitle>
            <DialogDescription>
              {channel.account}. {copy.senderEditDescription}
            </DialogDescription>
          </DialogHeader>
          <div className='flex flex-col gap-4 py-2'>
            {busy && (
              <p role='status' className='text-muted-foreground text-sm'>
                {copy.senderChecking}
              </p>
            )}
            {error && (
              <div className='flex flex-col gap-2'>
                <p role='alert' className='text-destructive text-sm'>
                  {error}
                </p>
                {needsSignIn ? (
                  <Button variant='glass' className={CONTROL_44} onClick={() => void signInAgain()}>
                    {copy.senderSignInAgain}
                  </Button>
                ) : (
                  <Button
                    variant='glass'
                    className={CONTROL_44}
                    disabled={busy}
                    onClick={() =>
                      void run(() => api.discordSenderProfile(workspaceId, channel.id))
                    }
                  >
                    {copy.senderReload}
                  </Button>
                )}
              </div>
            )}
            {profile && (
              <>
                <p className='text-muted-foreground text-sm' id={`${id}-scope`}>
                  {isBot ? copy.senderBotScope : copy.senderWebhookScope}
                  <br />
                  {copy.serverLabel}: {profile.guildId}
                </p>
                <div className='flex flex-col gap-2'>
                  <Label htmlFor={`${id}-name`}>{copy.senderNameLabel}</Label>
                  <Input
                    id={`${id}-name`}
                    value={name}
                    disabled={busy}
                    aria-describedby={`${id}-scope ${id}-limit`}
                    autoComplete='off'
                    className={CONTROL_44}
                    onChange={(event) => {
                      setName(event.target.value);
                      setSaved(false);
                    }}
                  />
                  <p id={`${id}-limit`} className='text-muted-foreground text-xs'>
                    {copy.senderNameLimit.replace('{limit}', String(profile.maxLength))}
                  </p>
                </div>
                <div
                  className='rounded-lg border p-3 text-sm'
                  aria-label={copy.senderPreview}
                  data-discord-sender-preview
                >
                  <p className='text-muted-foreground mb-2 text-xs'>{copy.senderPreview}</p>
                  <p className='break-words font-medium'>
                    {name || copy.senderNameLabel}{' '}
                    <span className='text-muted-foreground font-normal'>
                      · {isBot ? copy.senderBotKind : copy.senderWebhookKind}
                    </span>
                  </p>
                  <p className='mt-1'>{copy.senderExample}</p>
                </div>
                {isBot && (
                  <label className='flex min-h-11 items-start gap-3 text-sm'>
                    <input
                      type='checkbox'
                      aria-label={copy.senderSharedConfirm}
                      className='mt-1 size-4 shrink-0'
                      checked={shared}
                      disabled={busy}
                      onChange={(event) => setShared(event.target.checked)}
                    />
                    {copy.senderSharedConfirm}
                  </label>
                )}
                {saved && (
                  <p role='status' className='text-sm'>
                    {copy.senderSaved}
                  </p>
                )}
              </>
            )}
          </div>
          <DialogFooter className={DIALOG_FOOTER_PLAIN}>
            <Button
              variant='glass'
              className={CONTROL_44}
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {copy.senderClose}
            </Button>
            <Button
              className={CONTROL_44}
              disabled={busy || !validName || name === profile?.name || Boolean(isBot && !shared)}
              onClick={() => void save()}
            >
              {copy.senderSave}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
