'use client';

import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { StatefulButton } from '@/components/motion/button';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { BrandMode } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';

const MODES: { id: BrandMode; label: string; note: string }[] = [
  { id: 'personal', label: 'My personal brand', note: 'Share my experience, expertise and point of view.' },
  { id: 'niche', label: 'A niche or expertise', note: 'Build a focused channel around a subject.' },
  { id: 'business', label: 'A business', note: 'Speak for a company, studio or practice.' },
  { id: 'hybrid', label: 'A mix', note: 'Personal voice plus a subject or a business.' }
];

const TONES: { id: 'warm' | 'direct' | 'reflective'; label: string; note: string }[] = [
  { id: 'warm', label: 'Warm', note: 'Friendly, encouraging, first person.' },
  { id: 'direct', label: 'Direct', note: 'Short sentences, clear claims, no hedging.' },
  { id: 'reflective', label: 'Reflective', note: 'Thoughtful, slower, asks questions.' }
];

/**
 * Three short steps that create a voice profile for future drafts: starting point → purpose & audience → tone & sample → approve.
 * Every step is an explicit workspace action; nothing is inferred by a model.
 */
export function VoiceSetup({ onDone }: { onDone?: () => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;
  const provisional = state?.speaker?.provisional ?? null;
  // Approving the voice changes every member's drafts, so it is an owner decision (like learned preferences).
  const isOwner = snapshot.data?.membership?.role === 'owner';

  const [mode, setMode] = useState<BrandMode>((state?.brandHub?.mode as BrandMode) || 'personal');
  const [purpose, setPurpose] = useState(state?.brandHub?.purpose ?? '');
  const [audience, setAudience] = useState(state?.brandHub?.audience ?? '');
  const [subject, setSubject] = useState(state?.brandHub?.subject ?? '');
  const [speaker, setSpeaker] = useState(state?.brandHub?.speaker ?? '');
  const [tone, setTone] = useState<'warm' | 'direct' | 'reflective'>('warm');
  const [writing, setWriting] = useState('');
  const [note, setNote] = useState('');
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null);
  const reduce = useReducedMotion();
  const fieldTransition = reduce ? { duration: 0 } : { duration: 0.2, ease: EASE_OUT };

  const needsSubject = mode !== 'personal';
  const canPropose = purpose.trim() && audience.trim() && (!needsSubject || subject.trim()) && (mode !== 'hybrid' || speaker.trim());

  async function propose() {
    try {
      let current = revision;
      const modeResult = await act.mutateAsync({ revision: current, action: 'mode', payload: { mode } });
      current = modeResult.revision;
      const layers = mode === 'hybrid' ? ['voice', subject.trim() ? 'niche' : 'business'] : undefined;
      const contextResult = await act.mutateAsync({
        revision: current,
        action: 'context',
        payload: { purpose: purpose.trim(), audience: audience.trim(), subject: subject.trim(), speaker: speaker.trim(), ...(layers ? { layers } : {}) }
      });
      current = contextResult.revision;
      await act.mutateAsync({ revision: current, action: 'profile_propose', payload: { writing: writing.trim(), tone } });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The voice profile could not be proposed.');
    }
  }

  async function decide(decision: 'approve' | 'reject') {
    setDeciding(decision);
    try {
      await act.mutateAsync({ revision, action: 'profile_decide', payload: { decision, note: decision === 'approve' ? note.trim() : '' } });
      if (decision === 'approve') {
        toast.success('Voice profile active. New drafts will be written and scheduled against it.');
        onDone?.();
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The decision could not be saved.');
    } finally {
      setDeciding(null);
    }
  }

  if (provisional) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Review your provisional voice</CardTitle>
          <CardDescription>This is what drafts will be checked against. Approve it or start again — nothing here was analysed by a model.</CardDescription>
        </CardHeader>
        <CardContent className='flex flex-col gap-3 text-sm'>
          <p>
            Tone: <Badge variant='outline'>{provisional.tone}</Badge>
          </p>
          <ul className='list-disc pl-5'>
            {provisional.observations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {provisional.writingExample && <blockquote className='border-l-2 pl-3 whitespace-pre-wrap'>{provisional.writingExample}</blockquote>}
          <p className='text-muted-foreground text-xs'>Unknowns kept explicit: {provisional.unknowns.join(' ')}</p>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='voice-note'>Optional: one line in your words</Label>
            <Input id='voice-note' value={note} onChange={(e) => setNote(e.target.value)} maxLength={1500} placeholder='e.g. Plain, specific, never salesy.' />
          </div>
        </CardContent>
        <CardFooter className='flex flex-wrap gap-2'>
          {!isOwner && <p className='text-muted-foreground text-xs'>Only an owner can approve this voice or start again.</p>}
          <StatefulButton state={deciding === 'approve' ? 'loading' : 'idle'} loadingText='Saving…' disabled={act.isPending || !isOwner} onClick={() => void decide('approve')}>
            Use this voice
          </StatefulButton>
          <StatefulButton variant='outline' state={deciding === 'reject' ? 'loading' : 'idle'} loadingText='Saving…' disabled={act.isPending || !isOwner} onClick={() => setConfirmRestart(true)}>
            Start again
          </StatefulButton>
        </CardFooter>
        <AlertDialog open={confirmRestart} onOpenChange={setConfirmRestart}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Start the voice setup again?</AlertDialogTitle>
              <AlertDialogDescription>This discards the proposal and clears the active voice. Existing drafts need review, and waiting posts are held until approved again.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep this proposal</AlertDialogCancel>
              <AlertDialogAction disabled={act.isPending} onClick={() => void decide('reject')}>Start again</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set up your voice</CardTitle>
        <CardDescription>Two minutes to guide how future drafts sound. You can review and schedule drafts before setting this up.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-6'>
        <fieldset className='flex flex-col gap-2'>
          <legend className='mb-1 text-sm font-medium'>1. What are you building?</legend>
          <RadioGroup value={mode} onValueChange={(value) => setMode(value as BrandMode)} className='grid gap-2 sm:grid-cols-2'>
            {MODES.map((option) => (
              <RadioGroupItem
                key={option.id}
                id={`mode-${option.id}`}
                value={option.id}
                label={option.label}
                description={option.note}
                className='hover:bg-accent data-[state=checked]:border-primary rounded-lg border p-3 transition-colors'
              />
            ))}
          </RadioGroup>
        </fieldset>

        <fieldset className='flex flex-col gap-3'>
          <legend className='mb-1 text-sm font-medium'>2. Purpose and people</legend>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='voice-purpose'>What do you want your posts to do?</Label>
            <Input id='voice-purpose' value={purpose} onChange={(e) => setPurpose(e.target.value)} maxLength={1500} placeholder='e.g. Help beginners build a useful daily habit.' />
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='voice-audience'>Who are they for?</Label>
            <Input id='voice-audience' value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={1500} placeholder='e.g. Curious people getting started.' />
          </div>
          <AnimatePresence initial={false}>
            {needsSubject && (
              <motion.div key='subject' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-1.5'>
                <Label htmlFor='voice-subject'>{mode === 'business' ? 'The business' : 'The subject'}</Label>
                <Input id='voice-subject' value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={1500} />
              </motion.div>
            )}
            {mode === 'hybrid' && (
              <motion.div key='speaker' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-1.5'>
                <Label htmlFor='voice-speaker'>Who speaks in the first post?</Label>
                <Input id='voice-speaker' value={speaker} onChange={(e) => setSpeaker(e.target.value)} maxLength={1500} placeholder='e.g. Me, as the founder' />
              </motion.div>
            )}
          </AnimatePresence>
        </fieldset>

        <fieldset className='flex flex-col gap-3'>
          <legend className='mb-1 text-sm font-medium'>3. Tone and a sample</legend>
          <RadioGroup value={tone} onValueChange={(value) => setTone(value as 'warm' | 'direct' | 'reflective')} className='grid gap-2 sm:grid-cols-3'>
            {TONES.map((option) => (
              <RadioGroupItem
                key={option.id}
                id={`tone-${option.id}`}
                value={option.id}
                label={option.label}
                description={option.note}
                className='hover:bg-accent data-[state=checked]:border-primary rounded-lg border p-3 transition-colors'
              />
            ))}
          </RadioGroup>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='voice-writing'>Paste something you wrote (optional)</Label>
            <Textarea id='voice-writing' rows={4} value={writing} onChange={(e) => setWriting(e.target.value)} maxLength={6000} placeholder='A paragraph is enough. Writing routes receive it in VOICE.md as an example of how you write.' />
          </div>
        </fieldset>
      </CardContent>
      <CardFooter>
        <StatefulButton state={act.isPending ? 'loading' : 'idle'} loadingText='Saving…' disabled={!canPropose || act.isPending} onClick={() => void propose()}>
          Propose my voice
        </StatefulButton>
      </CardFooter>
    </Card>
  );
}

/** Small reusable notice for pages that need an active voice. */
export function useVoiceStatus() {
  const snapshot = useSnapshot();
  const speaker = snapshot.data?.state.speaker;
  return { loading: snapshot.isLoading, active: Boolean(speaker?.activeRevision), provisional: Boolean(speaker?.provisional) };
}
