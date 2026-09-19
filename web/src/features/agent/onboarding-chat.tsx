'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Message } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

type Progress = { complete: boolean; question: { key: string; question: string; hint?: string; limit?: number; optional?: boolean; options?: { id: string; label: string }[] } | null };

export function StartVoiceInterview() {
  const { api, workspaceId } = useWorkspaceApi();
  const router = useRouter();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function start() {
    setBusy(true);
    try {
      const conversation = await api.createConversation(workspaceId, 'Voice interview');
      await api.onboarding(workspaceId, conversation.conversationId, 0);
      await client.invalidateQueries({ queryKey: keys.conversations(workspaceId) });
      router.push(`/app/agent/${encodeURIComponent(conversation.conversationId)}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'The voice interview could not be started.');
    } finally { setBusy(false); }
  }
  return <Button variant='outline' size='sm' disabled={busy} onClick={() => void start()}>{busy ? 'Starting…' : 'Set up my voice in chat'}</Button>;
}

export function OnboardingAnswer({ message, conversationId, canEdit }: { message: Message; conversationId: string; canEdit: boolean }) {
  const progress = message.body.onboarding as Progress | undefined;
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const question = progress?.question;
  async function send(value: string) {
    setBusy(true);
    try {
      await api.onboarding(workspaceId, conversationId, message.seq, value);
      await Promise.all([keys.messages(workspaceId, conversationId), keys.snapshot(workspaceId), keys.memory(workspaceId), keys.audit(workspaceId)].map(queryKey => client.invalidateQueries({ queryKey })));
      setAnswer('');
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'The answer could not be saved.');
      if (error instanceof ApiError && error.status === 409) await client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
    } finally { setBusy(false); }
  }
  if (progress?.complete) return <Button variant='outline' render={<Link href='/app/workspace/brand' aria-label='Review proposed voice on Brand' />}>Review proposed voice on Brand</Button>;
  if (!canEdit) return <p className='text-muted-foreground text-sm'>An editor can continue this interview. Only an owner can activate the proposal.</p>;
  if (!question) return null;
  return <section aria-label='Voice interview answer' className='bg-card flex flex-col gap-3 rounded-xl border p-4'>
    {question.hint && <p className='text-muted-foreground text-xs'>{question.hint}</p>}
    {question.options ? <div className='flex flex-wrap gap-2'>{question.options.map(option => <Button key={option.id} variant='outline' disabled={busy} onClick={() => void send(option.id)}>{option.label}</Button>)}</div> : <>
      <Textarea aria-label={question.question} value={answer} maxLength={question.limit ?? 1500} onChange={event => setAnswer(event.target.value)} disabled={busy} />
      <div className='flex gap-2'><Button disabled={busy || !answer.trim()} onClick={() => void send(answer)}>Save answer</Button>{question.optional && <Button variant='ghost' disabled={busy} onClick={() => void send('')}>Skip sample</Button>}</div>
    </>}
    <p className='text-muted-foreground text-xs'>Answers are saved in this workspace conversation. No model is called. Your current voice stays active until an owner approves the proposal.</p>
    <Link href='/app' className='text-sm underline'>Return to drafting</Link>
  </section>;
}
