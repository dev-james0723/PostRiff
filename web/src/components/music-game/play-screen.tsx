'use client';

import { useEffect, useRef, useState } from 'react';
import {
  PRAISE,
  REVEAL_LEAD,
  TRY_AGAIN,
  answerRound,
  getLevel,
  nextQuestion,
  positionPhrase,
  startRound,
  type LevelNumber,
  type Option,
  type Question,
  type Round,
  type SoundEvent
} from '@/lib/music-game/curriculum';
import { BeatBar, Flower, Pip, Rhythm, RhythmBlocks, SoundDots, Staff } from './drawings';
import { ConfirmDialog, SoundToggle } from './parts';
import styles from './note-garden.module.css';

type Feedback = { tone: 'right' | 'try' | 'reveal'; lead: string; text: string };
/** Plays `events`, replacing anything still sounding (the synth keeps one schedule at a time). */
export type PlaySound = (events: SoundEvent[], options?: { delay?: number; cue?: 'correct' | 'try-again' }) => Promise<void>;

const ICONS: Record<NonNullable<Option['icon']>, string> = { same: '=', different: '≠', up: '↑ 🐦', down: '↓ 🐸', step: '👣', skip: '🐸' };
/** DESIGN §9: lock answers only while a short prompt sound plays the first time. */
const LOCK_LIMIT_SECONDS = 3.5;

const soundLength = (events: SoundEvent[]) => events.reduce((end, e) => Math.max(end, e.at + (e.kind === 'tone' ? e.seconds : 0.06)), 0);

function Stage({ q, settled, showPicture, hint, soundOff }: { q: Question; settled: boolean; showPicture: boolean; hint: boolean; soundOff: string | null }) {
  const stage = q.stage;
  const listen = (
    <>
      <Pip mood='happy' className={styles.pip} />
      <p className={styles.notice}>Listen carefully. Tap “Hear it again” to listen once more.</p>
    </>
  );
  let picture: React.ReactNode = null;
  let isSoundPicture = false;
  switch (stage.kind) {
    case 'dots':
      isSoundPicture = !settled;
      picture = settled || showPicture ? <SoundDots notes={stage.notes} label={q.stageLabel} /> : listen;
      break;
    case 'staff':
      if (q.type === 'step-skip' && !q.seen && !settled) {
        isSoundPicture = showPicture || hint;
        picture = isSoundPicture ? <SoundDots notes={stage.notes} label={`Picture of the sound: ${q.stageLabel}`} /> : <Staff notes={stage.notes} hidden label={q.stageLabel} />;
      } else {
        picture = <Staff notes={stage.notes} letters={settled} label={
            settled && q.type === 'step-skip' && !q.seen
              ? `Two notes: the first ${positionPhrase(stage.notes[0])}, the second ${positionPhrase(stage.notes[1])}.`
              : q.stageLabel
          } />;
      }
      break;
    case 'symbol':
      picture = <Rhythm tokens={[stage.token]} label={q.stageLabel} />;
      break;
    case 'bar':
      picture = <BeatBar tokens={stage.tokens} counts={hint} label={q.stageLabel} />;
      break;
    case 'rhythm':
      isSoundPicture = !settled;
      picture = settled || showPicture ? <RhythmBlocks tokens={stage.tokens} label={q.stageLabel} /> : listen;
      break;
    case 'none':
      return null;
  }
  return (
    <div className={styles.stage}>
      {picture}
      {soundOff && isSoundPicture && showPicture && <p className={styles.notice}>{soundOff}</p>}
    </div>
  );
}

export function PlayScreen({
  level,
  seed,
  muted,
  audioOk,
  sound,
  stopSound,
  onToggleMute,
  onFinish,
  onLeave
}: {
  level: LevelNumber;
  seed: number;
  muted: boolean;
  audioOk: boolean;
  sound: PlaySound;
  stopSound: () => void;
  onToggleMute: () => void;
  onFinish: (round: Round) => void;
  onLeave: () => void;
}) {
  const silent = muted || !audioOk;
  /** Answers wait while a short question sound plays the first time; decided with the question, never after paint. */
  const lockFor = (question: Question) => (!silent && question.sound.length > 0 && soundLength(question.sound) <= LOCK_LIMIT_SECONDS ? question.id : null);
  const [round, setRound] = useState<Round>(() => startRound(level, seed));
  const [lockedId, setLockedId] = useState<string | null>(() => lockFor(round.questions[0]));
  const [hint, setHint] = useState(false);
  const [picture, setPicture] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [shake, setShake] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const praise = useRef(0);
  const nudge = useRef(0);
  const promptRef = useRef<HTMLHeadingElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const answersRef = useRef<HTMLDivElement>(null);
  const announced = useRef('');

  const q = round.questions[round.index];
  const settled = round.status !== 'asking';
  const locked = lockedId === q.id;
  const showPicture = silent || picture;
  const soundOff = !audioOk ? "Sound can't play on this device. You can still play with pictures." : muted ? 'Sound is off. Here is a picture of the sound.' : null;
  const title = getLevel(level).title;

  // New question: reset helpers, move focus to the prompt and play the question once (answers wait for a short sound).
  useEffect(() => {
    if (announced.current === q.id) return;
    announced.current = q.id;
    setHint(false);
    setPicture(false);
    setFeedback(null);
    setShake(null);
    promptRef.current?.focus();
    if (silent || q.sound.length === 0) return;
    // Released when this sound ends, or as soon as a replay, an answer, mute or leaving replaces it.
    void sound(q.sound).finally(() => setLockedId((id) => (id === q.id ? null : id)));
  }, [q, silent, sound]);

  // After an answer: focus Next when settled, else the first option still open.
  useEffect(() => {
    if (round.status !== 'asking') nextRef.current?.focus();
    else if (round.tried.length > 0) answersRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
  }, [round.status, round.tried.length]);

  function choose(id: string) {
    const step = answerRound(round, id);
    if (step.outcome === 'ignored') return;
    setRound(step.round);
    // Each answer sound replaces the question sound, so a long rhythm prompt never plays under the feedback.
    if (step.outcome === 'correct') {
      void sound(q.answerSound, { delay: 0.35, cue: 'correct' });
      setFeedback({ tone: 'right', lead: PRAISE[praise.current++ % PRAISE.length], text: q.reveal });
    } else if (step.outcome === 'try-again') {
      void sound([], { cue: 'try-again' });
      setShake(id);
      setFeedback({ tone: 'try', lead: TRY_AGAIN[nudge.current++ % TRY_AGAIN.length], text: '' });
    } else {
      void sound(q.answerSound);
      setFeedback({ tone: 'reveal', lead: REVEAL_LEAD, text: q.reveal });
    }
  }

  function next() {
    stopSound();
    const after = nextQuestion(round);
    if (after.finished) {
      onFinish(after);
      return;
    }
    setRound(after);
    setLockedId(lockFor(after.questions[after.index]));
  }

  function hearAgain() {
    if (silent) setPicture(true);
    else void sound(q.sound);
  }

  function help() {
    setHint(true);
    if (!silent && q.slowSound !== q.sound && q.slowSound.length > 0) void sound(q.slowSound);
  }

  const feedbackClass = feedback?.tone === 'try' ? styles.feedbackTry : feedback ? styles.feedbackRight : '';
  const grown = round.flowers + (settled ? 1 : 0);

  return (
    <div className={styles.screen}>
      <nav className={styles.topBar} aria-label='Game'>
        <button type='button' className={styles.iconButton} onClick={() => setLeaving(true)}>
          <span aria-hidden='true'>←</span> Back
        </button>
        <p className={styles.counter}>
          Question {round.index + 1} of {round.questions.length}
        </p>
        <SoundToggle muted={muted} onToggle={onToggleMute} />
      </nav>

      <main className={styles.screen} style={{ animation: 'none' }}>
        <h1 className={styles.small}>
          Level {level}: {title}
        </h1>
        <div className={styles.playGrid}>
          <Stage q={q} settled={settled} showPicture={showPicture} hint={hint} soundOff={soundOff} />
          <div className={styles.screen} style={{ animation: 'none' }}>
            <h2 ref={promptRef} tabIndex={-1} className={styles.prompt}>
              {q.prompt}
            </h2>
            <div ref={answersRef} className={styles.answers} data-count={q.options.length} role='group' aria-label='Answers'>
              {q.options.map((option) => {
                const tried = round.tried.includes(option.id);
                const right = settled && option.id === q.answer;
                const state = right ? 'right' : tried ? 'tried' : undefined;
                const name = option.ariaLabel ? `${option.ariaLabel}${tried ? ', tried' : ''}${right ? ', the answer' : ''}` : undefined;
                return (
                  <button
                    key={option.id}
                    type='button'
                    className={styles.answer}
                    data-state={state}
                    data-shake={shake === option.id && tried}
                    data-locked={locked && !settled}
                    data-letter={q.type === 'name-note'}
                    data-card={!!option.note || !!option.tokens}
                    disabled={tried || settled || locked}
                    aria-label={name}
                    onClick={() => choose(option.id)}
                  >
                    {option.icon && (
                      <span aria-hidden='true' className={styles.icon}>
                        {ICONS[option.icon]}
                      </span>
                    )}
                    {option.note && <Staff notes={[option.note]} label='' compact />}
                    {option.tokens && <Rhythm tokens={option.tokens} decorative />}
                    {!option.note && <span>{option.label}</span>}
                    {tried && (
                      <span className={`${styles.mark} ${styles.markTried}`}>
                        <span aria-hidden='true'>✕</span> Tried
                      </span>
                    )}
                    {right && (
                      <span className={`${styles.mark} ${styles.markRight}`} aria-hidden='true'>
                        ✓
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div aria-live='polite' className={`${styles.feedback} ${feedbackClass}`}>
          {feedback && (
            <p className={styles.body}>
              <strong>{feedback.lead}</strong> {feedback.text}
            </p>
          )}
        </div>

        <div className={styles.row}>
          {q.sound.length > 0 && (
            <button type='button' className={styles.ghost} onClick={hearAgain}>
              <span aria-hidden='true'>🔊</span> Hear it again
            </button>
          )}
          <button type='button' className={styles.ghost} onClick={help} disabled={hint || settled}>
            <span aria-hidden='true'>💡</span> Help me
          </button>
        </div>
        {hint && !settled && (
          <p className={styles.hint}>
            <Pip mood='thinking' className={styles.pip} />
            <span>{q.hint}</span>
          </p>
        )}

        <div className={styles.garden} aria-hidden='true'>
          {round.questions.map((question, i) => (
            <span key={question.id} className={styles.flower}>
              <Flower grown={i < grown} hue={i} />
            </span>
          ))}
        </div>

        {settled && (
          <div className={styles.nextBar}>
            <button ref={nextRef} type='button' className={styles.button} onClick={next}>
              Next
            </button>
          </div>
        )}
      </main>

      <ConfirmDialog
        open={leaving}
        title='Leave this level? Your flowers will wait for you next time.'
        cancelLabel='Keep playing'
        confirmLabel='Leave'
        onCancel={() => setLeaving(false)}
        onConfirm={() => {
          setLeaving(false);
          onLeave();
        }}
      />
    </div>
  );
}
