'use client';

import { useState } from 'react';
import type { BrainAction } from './brand/brain-types';
import { useBrainCopy } from './brand/brain-copy';
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
export function VoiceSetup({ onDone, proposalOnly = false, onProposed, candidateRun }: { onDone?: () => void; proposalOnly?: boolean; onProposed?: () => void; candidateRun?: BrainAction }) {
  const t = useBrainCopy();
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
  const [proposing, setProposing] = useState(false);
  const [writing, setWriting] = useState('');
  const [note, setNote] = useState('');
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null);
  const reduce = useReducedMotion();
  const fieldTransition = reduce ? { duration: 0 } : { duration: 0.2, ease: EASE_OUT };

  const needsSubject = mode !== 'personal';
  const canPropose = !state?.workspace?.sample && Boolean(tone) && purpose.trim() && audience.trim() && (!needsSubject || subject.trim()) && (mode !== 'hybrid' || speaker.trim());

  async function propose() {
    if (!canPropose || proposing) return;
    if (proposalOnly && candidateRun) {
      setProposing(true);
      try {
        const layers = mode === 'hybrid' ? ['voice', subject.trim() ? 'niche' : 'business'] : undefined;
        if (await candidateRun('brand_brain_manual', { mode, tone, context: { purpose: purpose.trim(), audience: audience.trim(), subject: subject.trim(), speaker: speaker.trim(), ...(layers ? { layers } : {}) } })) onProposed?.();
      } finally { setProposing(false); }
      return;
    }
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
      await act.mutateAsync({ revision: current, action: 'profile_propose', payload: { writing: proposalOnly ? '' : writing.trim(), tone } });
      onProposed?.();
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

  if (provisional && proposalOnly) return <Button variant='glass' className='min-h-11' onClick={onProposed}>{t('Review proposed voice', '審閱風格提案', '审阅风格提案')}</Button>;

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
                  <Icons.spinner className='motion-safe:animate-spin' /> {t('Saving…', '儲存中…', '保存中…')}
                </>
              ) : (
                'Use this voice'
              )}
            </Button>
            <Button variant='glass' size='control' disabled={act.isPending || !isOwner} aria-busy={deciding === 'reject' || undefined} onClick={() => setConfirmRestart(true)}>
              {deciding === 'reject' ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> {t('Saving…', '儲存中…', '保存中…')}
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
    <Panel material='glass' title={t('Set up your voice', '設定你的寫作風格', '设置你的写作风格')} titleId='voice-setup-heading' bodyClassName='gap-6'>
      <fieldset className='flex flex-col gap-2'>
        <legend className='text-foreground mb-2 text-sm font-medium'>{t('1. What are you building?', '1. 你想建立甚麼？', '1. 你想建立什么？')}</legend>
        <RadioGroup value={mode} onValueChange={(value) => setMode(value as BrandMode)} className='grid gap-2 sm:grid-cols-2'>
          {MODES.map((option) => (
            <RadioGroupItem key={option.id} id={`mode-${option.id}`} value={option.id} label={t(option.label, ({ personal: '個人品牌', niche: '專業領域', business: '商業品牌', hybrid: '混合', warm: '溫暖', direct: '直接', reflective: '深思' } as Record<string, string>)[option.id] ?? option.label, ({ personal: '个人品牌', niche: '专业领域', business: '商业品牌', hybrid: '混合', warm: '温暖', direct: '直接', reflective: '深思' } as Record<string, string>)[option.id] ?? option.label)} description={t(option.note, ({ personal: '以你個人為中心', niche: '分享你的專業或興趣', business: '代表業務或機構', hybrid: '結合個人與品牌', warm: '友善、鼓勵、使用第一人稱', direct: '簡短清晰，直接表達', reflective: '深思熟慮，提出問題' } as Record<string, string>)[option.id] ?? option.note, ({ personal: '以你个人为中心', niche: '分享你的专业或兴趣', business: '代表业务或机构', hybrid: '结合个人与品牌', warm: '友善、鼓励、使用第一人称', direct: '简短清晰，直接表达', reflective: '深思熟虑，提出问题' } as Record<string, string>)[option.id] ?? option.note)} className={CHOICE_CLASS} />
          ))}
        </RadioGroup>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-2 text-sm font-medium'>{t('2. Purpose and people', '2. 目標與受眾', '2. 目标与受众')}</legend>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-purpose'>{t(interview.questions.find((q) => q.key === 'purpose')?.question ?? 'Purpose', '這個品牌希望達成甚麼？', '这个品牌希望实现什么？')}</Label>
          <Input id='voice-purpose' value={purpose} onChange={(e) => setPurpose(e.target.value)} maxLength={1500} placeholder={t('Help beginners build a daily habit', '幫助初學者建立日常習慣', '帮助初学者建立日常习惯')} className={FIELD_CLASS} />
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-audience'>{t(interview.questions.find((q) => q.key === 'audience')?.question ?? 'Audience', '你的目標受眾是誰？', '你的目标受众是谁？')}</Label>
          <Input id='voice-audience' value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={1500} placeholder={t('Curious people getting started', '剛開始探索的新手', '刚开始探索的新手')} className={FIELD_CLASS} />
        </div>
        <AnimatePresence initial={false}>
          {needsSubject && (
            <motion.div key='subject' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-2'>
              <Label htmlFor='voice-subject'>{mode === 'business' ? t('The business', '業務', '业务') : t('The subject', '主題', '主题')}</Label>
              <Input id='voice-subject' value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={1500} className={FIELD_CLASS} />
            </motion.div>
          )}
          {mode === 'hybrid' && (
            <motion.div key='speaker' initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={fieldTransition} className='flex flex-col gap-2'>
              <Label htmlFor='voice-speaker'>{t('Who speaks in the first post?', '首篇貼文由誰發言？', '首篇帖子由谁发言？')}</Label>
              <Input id='voice-speaker' value={speaker} onChange={(e) => setSpeaker(e.target.value)} maxLength={1500} placeholder={t('Me, as the founder', '以創辦人身分發言的我', '以创始人身份发言的我')} className={FIELD_CLASS} />
            </motion.div>
          )}
        </AnimatePresence>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-2 text-sm font-medium'>{t('3. Choose a core voice', '3. 選擇核心風格', '3. 选择核心风格')}</legend>
        <p className='text-muted-foreground text-xs'>{t('Your preference, not a learned conclusion.', '這是你的偏好，並非學習結論。', '这是你的偏好，并非学习结论。')}</p>
        <RadioGroup value={tone} onValueChange={(value) => setTone(value as 'warm' | 'direct' | 'reflective')} className='grid gap-2 sm:grid-cols-3'>
          {TONES.map((option) => (
            <RadioGroupItem key={option.id} id={`tone-${option.id}`} value={option.id} label={t(option.label, ({ personal: '個人品牌', niche: '專業領域', business: '商業品牌', hybrid: '混合', warm: '溫暖', direct: '直接', reflective: '深思' } as Record<string, string>)[option.id] ?? option.label, ({ personal: '个人品牌', niche: '专业领域', business: '商业品牌', hybrid: '混合', warm: '温暖', direct: '直接', reflective: '深思' } as Record<string, string>)[option.id] ?? option.label)} description={t(option.note, ({ personal: '以你個人為中心', niche: '分享你的專業或興趣', business: '代表業務或機構', hybrid: '結合個人與品牌', warm: '友善、鼓勵、使用第一人稱', direct: '簡短清晰，直接表達', reflective: '深思熟慮，提出問題' } as Record<string, string>)[option.id] ?? option.note, ({ personal: '以你个人为中心', niche: '分享你的专业或兴趣', business: '代表业务或机构', hybrid: '结合个人与品牌', warm: '友善、鼓励、使用第一人称', direct: '简短清晰，直接表达', reflective: '深思熟虑，提出问题' } as Record<string, string>)[option.id] ?? option.note)} className={CHOICE_CLASS} />
          ))}
        </RadioGroup>
        {!proposalOnly && <div className='flex flex-col gap-2'>
          <Label htmlFor='voice-writing'>Paste something you wrote (optional)</Label>
          <Textarea id='voice-writing' rows={4} value={writing} onChange={(e) => setWriting(e.target.value)} maxLength={6000} placeholder='A paragraph is enough.' className={TEXTAREA_CLASS} />
        </div>}
      </fieldset>

      <div>
        <Button variant='action' size='control' data-testid='bb-manual-propose' disabled={!canPropose || act.isPending || proposing} aria-busy={act.isPending || undefined} onClick={() => void propose()}>
          {act.isPending || proposing ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' /> {t('Saving…', '儲存中…', '保存中…')}
            </>
          ) : (
            t('Propose my voice', '提出我的風格提案', '提出我的风格提案')
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
