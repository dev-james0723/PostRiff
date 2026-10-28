'use client';

import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { DiscordCopy } from '@/lib/channels/discord-copy';
import { discordRefusal } from '@/lib/channels/discord-refusal';
import { verifyMessage } from '@/lib/channels/discord-sender-state-copy';
import { VERIFIED_STATES } from '@/lib/channels/state';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export interface VerifyResult {
  kind: 'done' | 'repeat' | 'failed';
  text: string;
}

/**
 * Verifies one Discord connection with the same request as the Verify button on its card. For a bot installation a
 * verification is what records the bot's nickname, which an approval then freezes and the dispatch preflight guards.
 * Pressing it twice sends one request, and the result is words, never a silent state.
 */
export function useVerifyDiscordConnection(channelId: string, copy: DiscordCopy) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const inFlight = useRef(false);

  async function run() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setResult(null);
    try {
      const outcome = await api.verifyChannel(workspaceId, channelId);
      await Promise.all([keys.channels, keys.snapshot, keys.audit].map((key) => client.invalidateQueries({ queryKey: key(workspaceId) })));
      setResult(verifyMessage(copy, { verified: VERIFIED_STATES.has(outcome.state), state: outcome.state, detail: outcome.detail }));
    } catch (error) {
      setResult({ kind: 'failed', text: copy.senderVerifyFailed.replace('{detail}', error instanceof ApiError ? discordRefusal(error, copy) : copy.senderVerifyRepeat) });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { run, busy, result };
}
