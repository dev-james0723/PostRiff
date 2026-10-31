'use client';

import { useState } from 'react';
import { getLevel, positionPhrase, rhythmEvents, toneEvents, type LevelNumber, type Token } from '@/lib/music-game/curriculum';
import { Pip, Rhythm, Staff } from './drawings';
import type { PlaySound } from './play-screen';
import styles from './note-garden.module.css';

const INTRO: Record<LevelNumber, string> = {
  1: 'High sounds are up like birds. Low sounds are down like frogs. Tap them!',
  2: 'The music staff has 5 lines and 4 spaces. Notes sit on a line or in a space. Tap a note to hear its name!',
  3: 'Music has a steady beat, like walking. Some notes last 1 beat, some last longer!',
  4: 'A step goes to the next stone. A skip jumps over a stone!'
};

const SYMBOLS: { token: Token; name: string; caption: string }[] = [
  { token: 'Q', name: 'Quarter note (crotchet)', caption: '1 beat, “ta”' },
  { token: 'E2', name: 'Two eighth notes (quavers)', caption: '1 beat together, “ti-ti”' },
  { token: 'H', name: 'Half note (minim)', caption: '2 beats, “ta-a”' },
  { token: 'W', name: 'Whole note (semibreve)', caption: '4 beats, “ta-a-a-a”' },
  { token: 'R', name: 'Quarter rest (crotchet rest)', caption: '1 quiet beat, “shh”' }
];

const LEARN_NOTES = ['C4', 'E4', 'G4', 'B4', 'D5', 'F5'];

function Tiles({ level, sound }: { level: LevelNumber; sound: PlaySound }) {
  const [named, setNamed] = useState<string[]>([]);
  const [demo, setDemo] = useState<string[]>(['C4', 'D4']);
  const tone = (note: string) => void sound(toneEvents([note], 0.6, 0));

  if (level === 1) {
    return (
      <div className={styles.learnGrid}>
        <button type='button' className={`${styles.ghost} ${styles.learnTile}`} onClick={() => tone('G5')}>
          <span aria-hidden='true' style={{ fontSize: '3rem' }}>
            🌻
          </span>
          Sunflower: high sound
        </button>
        <button type='button' className={`${styles.ghost} ${styles.learnTile}`} onClick={() => tone('C4')}>
          <span aria-hidden='true' style={{ fontSize: '3rem' }}>
            🍄
          </span>
          Mushroom: low sound
        </button>
      </div>
    );
  }
  if (level === 2) {
    return (
      <div className={styles.learnGrid}>
        {LEARN_NOTES.map((note) => {
          const shown = named.includes(note);
          return (
            <button
              key={note}
              type='button'
              className={`${styles.ghost} ${styles.learnTile}`}
              aria-label={shown ? `${note[0]}, a note ${positionPhrase(note)}` : `A note ${positionPhrase(note)}`}
              onClick={() => {
                tone(note);
                setNamed((list) => (list.includes(note) ? list : [...list, note]));
              }}
            >
              <Staff notes={[note]} letters={shown} label='' compact />
            </button>
          );
        })}
      </div>
    );
  }
  if (level === 3) {
    return (
      <div className={styles.learnGrid}>
        {SYMBOLS.map(({ token, name, caption }) => (
          <button key={token} type='button' className={`${styles.ghost} ${styles.learnTile}`} onClick={() => void sound(rhythmEvents([token], { bpm: 80, clicks: true }))}>
            <Rhythm tokens={[token]} decorative />
            <span>
              {name}
              <span className={styles.bedNote}>{caption}</span>
            </span>
          </button>
        ))}
      </div>
    );
  }
  return (
    <>
      <div className={styles.stage}>
        <Staff notes={demo} letters label={`Two notes: the first ${positionPhrase(demo[0])}, the second ${positionPhrase(demo[1])}.`} />
      </div>
      <div className={styles.row}>
        {[
          { label: 'Show a step', notes: ['C4', 'D4'] },
          { label: 'Show a skip', notes: ['C4', 'E4'] }
        ].map(({ label, notes }) => (
          <button
            key={label}
            type='button'
            className={styles.ghost}
            onClick={() => {
              setDemo(notes);
              void sound(toneEvents(notes, 0.6, 0.4));
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </>
  );
}

export function LearnCard({ level, sound, onPlay, onBack }: { level: LevelNumber; sound: PlaySound; onPlay: () => void; onBack: () => void }) {
  return (
    <main className={styles.screen}>
      <h1 className={styles.heading} tabIndex={-1} data-screen-heading>
        Level {level}: {getLevel(level).title}
      </h1>
      <div className={styles.speech}>
        <Pip mood='happy' className={styles.pip} />
        <p className={styles.bubble}>{INTRO[level]}</p>
      </div>
      <Tiles level={level} sound={sound} />
      <div className={styles.row}>
        <button type='button' className={styles.button} onClick={onPlay}>
          Let&apos;s play
        </button>
        <button type='button' className={styles.ghost} onClick={onBack}>
          Back
        </button>
      </div>
    </main>
  );
}
