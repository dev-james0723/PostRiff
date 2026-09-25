'use client';

import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { FIELD_CLASS, Panel, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { BrandMode } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { ProfileDetails } from './brand/voice-card';

// Generated copy of src/postriff_alpha/voice_interview.json; parity is checked by the Python contract test.
import interview from './voice-interview.generated.json';
const MODES = interview.modes;
const TONES = interview.tones;

/** A choice tile: quiet at rest, selected glass when chosen (DNA §5.2). */
const CHOICE_CLASS = 'rafii-quiet data-[state=checked]:rafii-glass-selected rounded-[var(--rafii-radius-control)] p-3.5 transition-colors';

/**
 * Three short steps that create a voice profile for future drafts: starting point → purpose & audience → tone & sample → approve.
 * Every step is an explicit workspace action. A selected-sample proposal may also arrive
 * from the local evidence analyser, but remains provisional until an owner approves it.
 */
export function VoiceSetup({ onDone }: { onDone?: () => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;
  const provisional = state?.speaker?.provisional ?? null;
  // Approving the voice changes every member's drafts, so it is an owner decision (like learned preferences).
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const proposalStale = provisional?.status === 'stale';

  const [mode, setMode] = useState<BrandMode>((state?.brandHub?.mode as BrandMode) || 'personal');
  const [purpose, setPurpose] = useState(state?.brandHub?.purpose ?? '');
  const [audience, setAudience] = useState(state?.brandHub?.audience ?? '');
  const [subject, setSubject] = useState(state?.brandHub?.subject ?? '');
  const [speaker, setSpeaker] = useState(state?.brandHub?.speaker ?? '');
  const [tone, setTone] = useState<'' | 'warm' | 'direct' | 'reflective'>('');
  const [writing, setWriting] = useState('');
  const [note, setNote] = useState('');
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null);
  const reduce = useReducedMotion();
  const fieldTransition = reduce ? { duration: 0 } : { duration: 0.2, ease: EASE_OUT };

  const needsSubject = mode !== 'personal';
  const canPropose = Boolean(tone) && purpose.trim() && audience.trim() && (!needsSubject || subject.trim()) && (mode !== 'hybrid' || speaker.trim());

  async function propose() {
    if (!canPropose) return;
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
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t save your voice. Try again.');
    }
  }

  async function decide(decision: 'approve' | 'reject') {
    setDeciding(decision);
    try {
      await act.mutateAsync({ revision, action: 'profile_decide', payload: { decision, note: decision === 'approve' ? note.trim() : '' } });
      if (decision === 'approve') {
        toast.success('Voice active');
        onDone?.();
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t save. Try again.');
    } finally {
      setDeciding(null);
    }
  }

  if (provisional) {
    return (
      <Panel
        material='glass'
        title='Review your voice'
        titleId='voice-provisional-heading'
        description={
          proposalStale
            ? 'A sample changed. Analyse your samples again before approving.'
            : provisional.analysisRoute
              ? provisional.analysisMethod === 'ai'
                ? 'Proposed by AI from the samples you allowed.'
                : 'From local writing statistics, not AI.'
              : undefined
        }
        bodyClassName='gap-5 text-sm'
      >
        <ProfileDetails profile={provisional} observationsLabel='Observations in this proposal' />
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-note'>Your guidance (optional)</Label>
          <Input id='voice-note' value={note} onChange={(e) => setNote(e.target.value)} maxLength={1500} placeholder='Plain, specific, never salesy.' className={FIELD_CLASS} />
        </div>
        <div className='flex flex-col gap-3'>
          {!isOwner && <p className='text-muted-foreground text-xs'>Only an owner can approve or start again.</p>}
          <div className='flex flex-wrap gap-2'>
            <Button variant='action' size='control' disabled={act.isPending || !isOwner || proposalStale} aria-busy={deciding === 'approve' || undefined} onClick={() => void decide('approve')}>
              {deciding === 'approve' ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Saving…
                </>
              ) : (
                'Use this voice'
              )}
            </Button>
            <Button variant='glass' size='control' disabled={act.isPending || !isOwner} aria-busy={deciding === 'reject' || undefined} onClick={() => setConfirmRestart(true)}>
              {deciding === 'reject' ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Saving…
                </>
              ) : (
                'Start again'
              )}
            </Button>
          </div>
        </div>
        <AlertDialog open={confirmRestart} onOpenChange={setConfirmRestart}>
          <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 md:rounded-[var(--rafii-radius-dialog)] md:p-6'>
            <AlertDialogHeader>
              <AlertDialogTitle>Start the voice setup again?</AlertDialogTitle>
              <AlertDialogDescription>This discards the proposal and clears the active voice. Drafts need review, and waiting posts are held until approved again.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel variant='glass' size='control'>
                Keep this proposal
              </AlertDialogCancel>
              <AlertDialogAction variant='action' size='control' disabled={act.isPending} onClick={() => void decide('reject')}>
                Start again
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </Panel>
    );
  }

  return (
    <Panel material='glass' title='Set up your voice' titleId='voice-setup-heading' bodyClassName='gap-6'>
      <fieldset className='flex flex-col gap-2'>
        <legend className='text-foreground mb-2 text-sm font-medium'>1. What are you building?</legend>
        <RadioGroup value={mode} onValueChange={(value) => setMode(value as BrandMode)} className='grid gap-2 sm:grid-cols-2'>
          {MODES.map((option) => (
            <RadioGroupItem key={option.id} id={`mode-${option.id}`} value={option.id} label={option.label} description={option.note} className={CHOICE_CLASS} />
          ))}
        </RadioGroup>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-2 text-sm font-medium'>2. Purpose and people</legend>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-purpose'>{interview.questions.find((q) => q.key === 'purpose')?.question}</Label>
          <Input id='voice-purpose' value={purpose} onChange={(e) => setPurpose(e.target.value)} maxLength={1500} placeholder='Help beginners build a daily habit' className={FIELD_CLASS} />
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-audience'>{interview.questions.find((q) => q.key === 'audience')?.question}</Label>
          <Input id='voice-audience' value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={1500} placeholder='Curious people getting started' className={FIELD_CLASS} />
        </div>
        <AnimatePresence initial={false}>
          {needsSubject && (
            <motion.div key='subject' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-2'>
              <Label htmlFor='voice-subject'>{mode === 'business' ? 'The business' : 'The subject'}</Label>
              <Input id='voice-subject' value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={1500} className={FIELD_CLASS} />
            </motion.div>
          )}
          {mode === 'hybrid' && (
            <motion.div key='speaker' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-2'>
              <Label htmlFor='voice-speaker'>Who speaks in the first post?</Label>
              <Input id='voice-speaker' value={speaker} onChange={(e) => setSpeaker(e.target.value)} maxLength={1500} placeholder='Me, as the founder' className={FIELD_CLASS} />
            </motion.div>
          )}
        </AnimatePresence>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-2 text-sm font-medium'>3. Tone and a sample</legend>
        <p className='text-muted-foreground text-xs'>Your preference, not a learned conclusion.</p>
        <RadioGroup value={tone} onValueChange={(value) => setTone(value as 'warm' | 'direct' | 'reflective')} className='grid gap-2 sm:grid-cols-3'>
          {TONES.map((option) => (
            <RadioGroupItem key={option.id} id={`tone-${option.id}`} value={option.id} label={option.label} description={option.note} className={CHOICE_CLASS} />
          ))}
        </RadioGroup>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-writing'>Paste something you wrote (optional)</Label>
          <Textarea id='voice-writing' rows={4} value={writing} onChange={(e) => setWriting(e.target.value)} maxLength={6000} placeholder='A paragraph is enough.' className={TEXTAREA_CLASS} />
        </div>
      </fieldset>

      <div>
        <Button variant='action' size='control' disabled={!canPropose || act.isPending} aria-busy={act.isPending || undefined} onClick={() => void propose()}>
          {act.isPending ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' /> Saving…
            </>
          ) : (
            'Propose my voice'
          )}
        </Button>
      </div>
    </Panel>
  );
}

/** Small reusable notice for pages that need an active voice. */
export function useVoiceStatus() {
  const snapshot = useSnapshot();
  const speaker = snapshot.data?.state.speaker;
  return { loading: snapshot.isLoading, active: Boolean(speaker?.activeRevision), provisional: Boolean(speaker?.provisional) };
}
