'use client';

import { useEffect, useRef } from 'react';
import { Star } from './drawings';
import styles from './note-garden.module.css';

export function StarRow({ stars, big = false }: { stars: number; big?: boolean }) {
  return (
    <span className={big ? `${styles.stars} ${styles.bigStars}` : styles.stars}>
      {[1, 2, 3].map((n) => (
        <Star key={n} on={n <= stars} />
      ))}
      <span className={styles.srOnly}>{`${stars} of 3 stars`}</span>
    </span>
  );
}

/** Native modal dialog: focus is trapped and Escape means the safe choice (cancel). */
export function ConfirmDialog({
  open,
  title,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel
}: {
  open: boolean;
  title: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby='ng-dialog-title'
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <p id='ng-dialog-title' className={styles.body} style={{ fontWeight: 700, marginBottom: 16 }}>
        {title}
      </p>
      <div className={styles.row}>
        <button type='button' className={styles.button} onClick={onCancel}>
          {cancelLabel}
        </button>
        <button type='button' className={styles.ghost} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}

export function SoundToggle({ muted, onToggle }: { muted: boolean; onToggle: () => void }) {
  return (
    <button type='button' className={styles.iconButton} aria-pressed={!muted} onClick={onToggle}>
      <span aria-hidden='true' className={styles.icon}>
        {muted ? '🔇' : '🔊'}
      </span>
      Sound
    </button>
  );
}
