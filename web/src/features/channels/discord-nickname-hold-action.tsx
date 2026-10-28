'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/button';
import { discordCopy } from '@/lib/channels/discord-copy';
import { usePreferences } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import { CONTROL_44 } from './rafii-materials';
import { useVerifyDiscordConnection } from './use-verify-discord-connection';

/**
 * Under the held-post line the nickname guard writes: what happened in the person's language and the one action that
 * moves it forward. The guard holds a bot post when Discord shows another nickname than the one recorded at approval,
 * and re-reviewing records the same old value again until a verification refreshes it.
 */
export function DiscordNicknameHoldAction({ channelId }: { channelId: string }) {
  const { locale } = usePreferences();
  const copy = discordCopy(locale);
  const verify = useVerifyDiscordConnection(channelId, copy);
  const id = useId();
  return (
    <div className='flex min-w-0 flex-col gap-1.5 pt-1 text-xs' data-discord-nickname-hold>
      <p id={`${id}-note`}>{copy.senderHoldNote}</p>
      <Button
        type='button'
        variant='glass'
        className={cn(CONTROL_44, 'self-start aria-disabled:cursor-not-allowed aria-disabled:opacity-60')}
        aria-disabled={verify.busy}
        aria-describedby={`${id}-note`}
        data-discord-verify
        onClick={() => {
          if (!verify.busy) void verify.run();
        }}
      >
        {verify.busy ? copy.senderVerifying : copy.senderVerifyLabel}
      </Button>
      <p role='status' aria-live='polite' data-discord-verify-result={verify.result?.kind}>
        {verify.result?.text}
      </p>
    </div>
  );
}
