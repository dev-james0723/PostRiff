'use client';

/**
 * Note Garden: a children's music-theory game (ages 6–10). Client-only, no accounts, no network calls; progress lives
 * in localStorage. Flow (docs/music-game/SPEC.md): title -> hello (first tap starts sound) -> garden map -> learn card
 * -> questions -> level done -> map. Grown-ups panel holds sound, volume, open-all and reset.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { LEVEL_DONE, LEVELS, isLevelUnlocked, type LevelNumber, type Round, type SoundEvent } from '@/lib/music-game/curriculum';
import { defaultProgress, loadProgress, recordRun, resetProgress, saveProgress, withAllOpen, withMuted, withVolume, type Progress, type Volume } from '@/lib/music-game/progress';
import { createSynth, type Synth } from '@/lib/music-game/synth';
import { Flower, Pip } from './drawings';
import { GrownUps } from './grown-ups';
import { LearnCard } from './learn-card';
import { StarRow } from './parts';
import { PlayScreen } from './play-screen';
import styles from './note-garden.module.css';

type Screen = 'title' | 'hello' | 'map' | 'learn' | 'play' | 'done' | 'grownups';

function browserStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

function audioFactory(): (() => AudioContext) | undefined {
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  return Ctor ? () => new Ctor() : undefined;
}

function freshSeed(): number {
  const buffer = new Uint32Array(1);
  crypto.getRandomValues(buffer);
  return buffer[0];
}

export function NoteGarden() {
  const [progress, setProgress] = useState<Progress>(defaultProgress);
  const [screen, setScreen] = useState<Screen>('title');
  const [level, setLevel] = useState<LevelNumber>(1);
  const [seed, setSeed] = useState(1);
  const [lastRun, setLastRun] = useState<Round | null>(null);
  const [audioOk, setAudioOk] = useState(true);
  const [grownupsFrom, setGrownupsFrom] = useState<Screen>('title');
  const synthRef = useRef<Synth | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const firstScreen = useRef(true);

  useEffect(() => {
    setProgress(loadProgress(browserStorage()));
  }, []);

  const getSynth = useCallback((): Synth => {
    if (!synthRef.current) {
      const current = loadProgress(browserStorage());
      synthRef.current = createSynth({ createContext: audioFactory(), muted: current.muted, volume: current.volume });
    }
    return synthRef.current;
  }, []);

  // Stop sound when the tab is hidden; release the AudioContext when the route unmounts.
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') synthRef.current?.stop();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      synthRef.current?.close();
      synthRef.current = null;
    };
  }, []);

  // Each new screen moves focus to its heading (the play screen focuses its own prompt).
  useEffect(() => {
    if (firstScreen.current) {
      firstScreen.current = false;
      return;
    }
    rootRef.current?.querySelector<HTMLElement>('[data-screen-heading]')?.focus();
  }, [screen]);

  const update = (change: (p: Progress) => Progress) => {
    const next = change(progress);
    setProgress(next);
    saveProgress(browserStorage(), next);
    return next;
  };

  const sound = useCallback(
    async (events: SoundEvent[], options?: { delay?: number; cue?: 'correct' | 'try-again' }) => {
      const synth = getSynth();
      if (!(await synth.unlock())) return;
      await synth.play(events, options);
    },
    [getSynth]
  );

  const stopSound = useCallback(() => synthRef.current?.stop(), []);

  /** Every screen change silences whatever the last screen was playing. */
  const go = (next: Screen) => {
    stopSound();
    setScreen(next);
  };

  async function letsGo() {
    const synth = getSynth();
    const ok = (await synth.unlock()) || progress.muted;
    setAudioOk(synth.supported() && ok);
    go('map');
  }

  function toggleMute() {
    const muted = !progress.muted;
    update((p) => withMuted(p, muted));
    const synth = getSynth();
    synth.setMuted(muted);
    if (!muted) void synth.unlock().then((ok) => setAudioOk(synth.supported() && ok));
  }

  function setVolume(volume: Volume) {
    update((p) => withVolume(p, volume));
    getSynth().setVolume(volume);
  }

  function openGrownUps() {
    setGrownupsFrom(screen);
    go('grownups');
  }

  function play(n: LevelNumber) {
    setLevel(n);
    go('learn');
  }

  function startRun() {
    setSeed(freshSeed());
    go('play');
  }

  function finish(round: Round) {
    getSynth().stop();
    update((p) => recordRun(p, round.level, round.stars));
    setLastRun(round);
    go('done');
  }

  const allDone = LEVELS.every((l) => progress.done[l.number]);
  const totalStars = LEVELS.reduce((sum, l) => sum + (progress.best[l.number] ?? 0), 0);

  return (
    <div ref={rootRef} className={styles.root} lang='en'>
      <div className={styles.shell}>
        {screen === 'title' && (
          <main className={`${styles.screen} ${styles.hero}`}>
            <Pip mood='happy' className={`${styles.pip} ${styles.pipBob}`} />
            <h1 className={styles.title} tabIndex={-1} data-screen-heading>
              Note Garden
            </h1>
            <p className={styles.tagline}>Grow flowers with music</p>
            {/* One flower for every star earned (12 in all). Decorative: the map states the stars in words. */}
            <div className={`${styles.garden} ${styles.titleGarden}`} aria-hidden='true'>
              {Array.from({ length: 12 }, (_, i) => (
                <span key={i} className={styles.flower}>
                  <Flower grown={i < totalStars} hue={i} />
                </span>
              ))}
            </div>
            <div className={styles.row}>
              <button type='button' className={styles.button} onClick={() => go('hello')}>
                Play
              </button>
              <button type='button' className={styles.linkButton} onClick={openGrownUps}>
                Grown-ups
              </button>
            </div>
          </main>
        )}

        {screen === 'hello' && (
          <main className={styles.screen}>
            <div className={styles.speech}>
              <Pip mood='cheer' className={`${styles.pip} ${styles.pipBob}`} />
              <h1 className={styles.bubble} tabIndex={-1} data-screen-heading>
                Hi! I&apos;m Pip. Let&apos;s make music!
              </h1>
            </div>
            <div className={styles.row}>
              <button type='button' className={styles.button} onClick={() => void letsGo()}>
                Let&apos;s go
              </button>
            </div>
          </main>
        )}

        {screen === 'map' && (
          <main className={styles.screen}>
            <div className={styles.topBar}>
              <h1 className={styles.heading} tabIndex={-1} data-screen-heading>
                Pick a garden bed!
              </h1>
            </div>
            {!audioOk && <p className={styles.notice}>Sound can&apos;t play on this device. You can still play with pictures.</p>}
            {allDone && <p className={styles.body}>You grew the whole Note Garden! 🌻 Play any level again.</p>}
            <ul className={styles.beds}>
              {LEVELS.map((l) => {
                const open = isLevelUnlocked(l.number, progress.done, progress.allOpen);
                return (
                  <li key={l.number}>
                    <button type='button' className={styles.bed} disabled={!open} onClick={() => play(l.number as LevelNumber)}>
                      <span className={styles.bedNumber} aria-hidden='true'>
                        {open ? l.number : '🔒'}
                      </span>
                      <span>
                        <span className={styles.bedTitle}>
                          <span className={styles.srOnly}>Level {l.number}: </span>
                          {l.title}
                        </span>
                        <span className={styles.bedNote}>{open ? l.goal : `Finish Level ${l.number - 1} to open`}</span>
                      </span>
                      {open && <StarRow stars={progress.best[l.number] ?? 0} />}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className={styles.row}>
              <button type='button' className={styles.linkButton} onClick={openGrownUps}>
                Grown-ups
              </button>
            </div>
          </main>
        )}

        {screen === 'learn' && <LearnCard level={level} sound={sound} onPlay={startRun} onBack={() => go('map')} />}

        {screen === 'play' && (
          <PlayScreen
            key={seed}
            level={level}
            seed={seed}
            muted={progress.muted}
            audioOk={audioOk}
            sound={sound}
            stopSound={stopSound}
            onToggleMute={toggleMute}
            onFinish={finish}
            onLeave={() => {
              getSynth().stop();
              go('map');
            }}
          />
        )}

        {screen === 'done' && lastRun && (
          <main className={styles.screen}>
            <div className={styles.speech}>
              <Pip mood='cheer' className={styles.pip} />
              <h1 className={styles.heading} tabIndex={-1} data-screen-heading>
                {LEVEL_DONE[lastRun.stars]}
              </h1>
            </div>
            <StarRow stars={lastRun.stars} big />
            {allDone && <p className={styles.body}>You grew the whole Note Garden! 🌻</p>}
            <div className={styles.row}>
              <button type='button' className={styles.button} onClick={startRun}>
                Play again
              </button>
              {level < 4 && (
                <button type='button' className={styles.ghost} onClick={() => play((level + 1) as LevelNumber)}>
                  Next level
                </button>
              )}
              <button type='button' className={styles.ghost} onClick={() => go('map')}>
                Garden map
              </button>
            </div>
          </main>
        )}

        {screen === 'grownups' && (
          <GrownUps
            muted={progress.muted}
            volume={progress.volume}
            allOpen={progress.allOpen}
            onToggleMute={toggleMute}
            onVolume={setVolume}
            onOpenAll={() => update((p) => withAllOpen(p, true))}
            onReset={() => setProgress(resetProgress(browserStorage(), progress))}
            onBack={() => go(grownupsFrom === 'grownups' ? 'title' : grownupsFrom)}
          />
        )}
      </div>
    </div>
  );
}
