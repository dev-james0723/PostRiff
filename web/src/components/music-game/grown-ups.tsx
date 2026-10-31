'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { Volume } from '@/lib/music-game/progress';
import { ConfirmDialog, SoundToggle } from './parts';
import styles from './note-garden.module.css';

const VOLUMES: { value: Volume; text: string }[] = [
  { value: 'soft', text: 'Soft' },
  { value: 'medium', text: 'Medium' }
];

export function GrownUps({
  muted,
  volume,
  allOpen,
  onToggleMute,
  onVolume,
  onOpenAll,
  onReset,
  onBack
}: {
  muted: boolean;
  volume: Volume;
  allOpen: boolean;
  onToggleMute: () => void;
  onVolume: (volume: Volume) => void;
  onOpenAll: () => void;
  onReset: () => void;
  onBack: () => void;
}) {
  const [confirm, setConfirm] = useState<'open' | 'reset' | null>(null);
  const [status, setStatus] = useState('');

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading} tabIndex={-1} data-screen-heading>
        For grown-ups
      </h1>
      {/* Only what the game guarantees (D3). /play sends no analytics or telemetry (D1). A Privacy link waits for the
          site policy's children's section (privacy F4: docs/music-game/PRIVACY-NOTICE-DRAFT.md, for counsel). */}
      <p className={styles.body}>
        <span className={styles.line}>Note Garden has no accounts.</span>
        <span className={styles.line}>It never asks for names or personal details.</span>
        <span className={styles.line}>Progress is saved only on this device.</span>
        <span className={styles.line}>There are no ads.</span>
      </p>

      <section className={styles.card} aria-labelledby='ng-sound'>
        <h2 id='ng-sound' className={styles.bedTitle} style={{ marginTop: 0 }}>
          Sound
        </h2>
        <div className={styles.row}>
          <SoundToggle muted={muted} onToggle={onToggleMute} />
        </div>
        <fieldset className={styles.fieldset} style={{ marginTop: 12 }}>
          <legend>Volume</legend>
          <div className={styles.row}>
            {VOLUMES.map(({ value, text }) => (
              <label key={value} className={`${styles.ghost} ${styles.radio}`}>
                <input type='radio' name='ng-volume' value={value} checked={volume === value} onChange={() => onVolume(value)} aria-label={text} />
                {text}
              </label>
            ))}
          </div>
        </fieldset>
        <p className={styles.small} style={{ marginTop: 12 }}>
          Keep headphone volume low.
        </p>
      </section>

      <section className={styles.card} aria-labelledby='ng-levels'>
        <h2 id='ng-levels' className={styles.bedTitle} style={{ marginTop: 0 }}>
          Levels and progress
        </h2>
        <div className={styles.row}>
          {allOpen ? (
            <p className={styles.body}>All levels are open.</p>
          ) : (
            <button type='button' className={styles.ghost} onClick={() => setConfirm('open')}>
              Open all levels
            </button>
          )}
          <button type='button' className={styles.ghost} onClick={() => setConfirm('reset')}>
            Reset progress
          </button>
        </div>
        <p className={styles.small} role='status' style={{ marginTop: 12 }}>
          {status}
        </p>
      </section>

      <div className={styles.row}>
        <button type='button' className={styles.button} onClick={onBack}>
          Back
        </button>
        <Link className={styles.linkButton} href='/' prefetch={false}>
          Back to Rafii
        </Link>
      </div>

      <ConfirmDialog
        open={confirm === 'open'}
        title='Open all four levels on this device?'
        cancelLabel='Cancel'
        confirmLabel='Open'
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          onOpenAll();
          setStatus('All levels are open.');
        }}
      />
      <ConfirmDialog
        open={confirm === 'reset'}
        title='Delete stars on this device?'
        cancelLabel='Cancel'
        confirmLabel='Delete'
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          onReset();
          setStatus('Progress deleted. The garden is ready to grow again.');
        }}
      />
    </main>
  );
}
