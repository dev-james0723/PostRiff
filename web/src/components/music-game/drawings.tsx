/**
 * Hand-authored SVG for Note Garden (DESIGN §5–6): treble staff, sound-picture dots, rhythm symbols, beat pots,
 * Pip the mascot, flowers and stars. All shapes are original primitives; no font glyphs or image files.
 */
import { noteToMidi, staffStep, TOKEN_BEATS, type NoteName, type Token } from '@/lib/music-game/curriculum';

const INK = 'var(--ng-ink)';
const S = 20; // staff line spacing
const Y0 = 130; // bottom line (E4)
const noteY = (note: NoteName) => Y0 - (staffStep(note) * S) / 2;

/** Simplified original treble clef outline, drawn as one stroke. */
const CLEF = 'M44 170 Q36 172 36 164 Q36 156 46 158 L52 40 Q54 22 64 30 Q70 40 50 66 Q26 90 30 112 Q34 132 54 130 Q70 126 66 110 Q62 96 48 100 Q38 104 42 116';

function NoteHead({ note, x, filled = true }: { note: NoteName; x: number; filled?: boolean }) {
  const y = noteY(note);
  const p = staffStep(note);
  const up = p < 4;
  return (
    <g>
      {p <= -2 && <line x1={x - 16} x2={x + 16} y1={Y0 + S} y2={Y0 + S} stroke={INK} strokeWidth={2} />}
      <ellipse cx={x} cy={y} rx={11.5} ry={8.5} transform={`rotate(-20 ${x} ${y})`} fill={filled ? INK : 'none'} stroke={INK} strokeWidth={2} />
      <line x1={up ? x + 10 : x - 10} x2={up ? x + 10 : x - 10} y1={y} y2={up ? y - 3.5 * S : y + 3.5 * S} stroke={INK} strokeWidth={3} />
    </g>
  );
}

/**
 * A treble staff with up to two notes. `hidden` draws "?" stones instead (L4 heard-only); `letters` writes each
 * note's letter under the staff once the question is settled.
 */
export function Staff({ notes, hidden = false, letters = false, label, compact = false }: { notes: NoteName[]; hidden?: boolean; letters?: boolean; label: string; compact?: boolean }) {
  const xs = notes.length === 1 ? [200] : [160, 250];
  return (
    <svg viewBox={compact ? '20 20 300 170' : '0 10 320 190'} {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}>
      {[0, 1, 2, 3, 4].map((k) => (
        <line key={k} x1={8} x2={312} y1={Y0 - k * S} y2={Y0 - k * S} stroke={INK} strokeWidth={2} />
      ))}
      <path d={CLEF} fill='none' stroke={INK} strokeWidth={4} strokeLinecap='round' strokeLinejoin='round' aria-hidden='true' />
      {notes.map((note, i) =>
        hidden ? (
          <g key={i}>
            <circle cx={xs[i]} cy={90} r={22} fill='var(--ng-mint)' stroke={INK} strokeWidth={2} />
            <text x={xs[i]} y={99} textAnchor='middle' fontSize={26} fontWeight={700} fill={INK}>
              ?
            </text>
          </g>
        ) : (
          <NoteHead key={i} note={note} x={xs[i]} />
        )
      )}
      {letters &&
        !hidden &&
        notes.map((note, i) => (
          <text key={`l${i}`} x={xs[i]} y={190} textAnchor='middle' fontSize={26} fontWeight={700} fill='var(--ng-leaf)'>
            {note[0]}
          </text>
        ))}
    </svg>
  );
}

/** Height of a dot for C4 (low, y 150) to G5 (high, y 30). */
const dotY = (note: NoteName) => 150 - ((noteToMidi(note) - 60) / 19) * 120;

/** "Picture of the sound": two dots at their notes' relative heights (L1, L4 heard, sound off). */
export function SoundDots({ notes, label }: { notes: NoteName[]; label: string }) {
  const y = dotY;
  return (
    <svg viewBox='0 0 320 180' role='img' aria-label={label}>
      <line x1={20} x2={300} y1={170} y2={170} stroke='var(--ng-leaf)' strokeWidth={4} strokeLinecap='round' />
      {notes.map((note, i) => (
        <g key={i}>
          <circle cx={110 + i * 100} cy={y(note)} r={20} fill={i === 0 ? 'var(--ng-sky)' : 'var(--ng-sun)'} stroke={INK} strokeWidth={3} />
          <text x={110 + i * 100} y={y(note) + 8} textAnchor='middle' fontSize={22} fontWeight={700} fill={INK}>
            {i + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}

const TOKEN_WIDTH: Record<Token, number> = { Q: 40, H: 44, W: 52, E2: 64, R: 40 };

function TokenShape({ token, x, y }: { token: Token; x: number; y: number }) {
  const head = (cx: number, filled: boolean, rx = 11) => (
    <ellipse cx={cx} cy={y} rx={rx} ry={8.5} transform={`rotate(-20 ${cx} ${y})`} fill={filled ? INK : 'none'} stroke={INK} strokeWidth={3} />
  );
  const stem = (cx: number) => <line x1={cx + 10} x2={cx + 10} y1={y} y2={y - 62} stroke={INK} strokeWidth={3} />;
  switch (token) {
    case 'Q':
      return <g>{head(x, true)}{stem(x)}</g>;
    case 'H':
      return <g>{head(x, false)}{stem(x)}</g>;
    case 'W':
      return <g>{head(x, false, 14)}</g>;
    case 'E2':
      return (
        <g>
          {head(x - 14, true)}
          {stem(x - 14)}
          {head(x + 14, true)}
          {stem(x + 14)}
          <rect x={x - 4} y={y - 64} width={28} height={6} fill={INK} />
        </g>
      );
    case 'R':
      return (
        <path
          d={`M${x - 4} ${y - 48} L${x + 6} ${y - 34} L${x - 4} ${y - 22} L${x + 6} ${y - 8} Q${x - 10} ${y - 12} ${x} ${y + 6}`}
          fill='none'
          stroke={INK}
          strokeWidth={5}
          strokeLinecap='round'
          strokeLinejoin='round'
        />
      );
  }
}

/** A row of rhythm symbols (count-beats stage, fill-bar options, hear-rhythm cards). */
export function Rhythm({ tokens, label, decorative = false }: { tokens: Token[]; label?: string; decorative?: boolean }) {
  const widths = tokens.map((t) => TOKEN_WIDTH[t]);
  const total = widths.reduce((a, b) => a + b, 0) + 16;
  let x = 8;
  return (
    <svg viewBox={`0 0 ${total} 100`} {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label })} style={{ maxHeight: 120 }}>
      {tokens.map((token, i) => {
        const cx = x + widths[i] / 2;
        x += widths[i];
        return <TokenShape key={i} token={token} x={cx} y={78} />;
      })}
    </svg>
  );
}

function Pot({ x, label, empty = false }: { x: number; label?: string; empty?: boolean }) {
  return (
    <g>
      <path d={`M${x + 6} 120 L${x + 64} 120 L${x + 56} 160 L${x + 14} 160 Z`} fill={empty ? 'none' : 'var(--ng-orange)'} stroke={INK} strokeWidth={2} strokeDasharray={empty ? '6 5' : undefined} />
      {label && (
        <text x={x + 35} y={150} textAnchor='middle' fontSize={22} fontWeight={700} fill={INK}>
          {label}
        </text>
      )}
    </g>
  );
}

/** A 4-beat bar over four flower pots; `null` is the gap. With `counts`, each filled pot shows the running beat count. */
export function BeatBar({ tokens, label, counts = false }: { tokens: (Token | null)[]; label: string; counts?: boolean }) {
  let beat = 0;
  const filledBeats = tokens.reduce((sum, t) => sum + (t ? TOKEN_BEATS[t] : 0), 0);
  const parts = tokens.map((token) => {
    const beats = token ? TOKEN_BEATS[token] : 4 - filledBeats;
    const part = { token, start: beat, beats };
    beat += beats;
    return part;
  });
  return (
    <svg viewBox='0 0 300 170' role='img' aria-label={label}>
      {[0, 1, 2, 3].map((i) => {
        const part = parts.find((p) => i >= p.start && i < p.start + p.beats);
        const empty = !part?.token;
        return <Pot key={i} x={10 + i * 70} empty={empty} label={counts && !empty ? String(i + 1) : undefined} />;
      })}
      {parts.map((p, i) =>
        p.token ? (
          <TokenShape key={i} token={p.token} x={10 + p.start * 70 + (p.beats * 70) / 2} y={100} />
        ) : (
          <rect key={i} x={14 + p.start * 70} y={20} width={p.beats * 70 - 8} height={92} rx={14} fill='none' stroke='var(--ng-sky-deep)' strokeWidth={3} strokeDasharray='8 6' />
        )
      )}
    </svg>
  );
}

/** Sound-off picture of a rhythm: one block per note, as long as the note lasts. */
export function RhythmBlocks({ tokens, label }: { tokens: Token[]; label: string }) {
  let x = 10;
  const unit = 70;
  return (
    <svg viewBox='0 0 300 80' role='img' aria-label={label}>
      {tokens.flatMap((token, i) => {
        const start = x;
        x += TOKEN_BEATS[token] * unit;
        if (token === 'R') return [<rect key={i} x={start + 4} y={30} width={unit - 8} height={20} rx={10} fill='none' stroke={INK} strokeWidth={2} strokeDasharray='4 4' />];
        if (token === 'E2')
          return [0, 1].map((h) => <rect key={`${i}-${h}`} x={start + 4 + (h * unit) / 2} y={25} width={unit / 2 - 8} height={30} rx={10} fill='var(--ng-sky)' stroke={INK} strokeWidth={2} />);
        return [<rect key={i} x={start + 4} y={25} width={TOKEN_BEATS[token] * unit - 8} height={30} rx={12} fill='var(--ng-sky)' stroke={INK} strokeWidth={2} />];
      })}
    </svg>
  );
}

export type PipMood = 'happy' | 'thinking' | 'cheer';

/** Pip, a seed sprout. Decorative: whatever Pip "says" is real text next to it. Never sad. */
export function Pip({ mood = 'happy', className }: { mood?: PipMood; className?: string }) {
  const leafUp = mood === 'cheer';
  return (
    <svg viewBox='0 0 100 100' className={className} aria-hidden='true'>
      <ellipse cx={leafUp ? 34 : 30} cy={leafUp ? 20 : 28} rx={14} ry={7} transform={`rotate(${leafUp ? -60 : -25} ${leafUp ? 34 : 30} ${leafUp ? 20 : 28})`} fill='var(--ng-leaf)' />
      <ellipse cx={leafUp ? 66 : 70} cy={leafUp ? 20 : 28} rx={14} ry={7} transform={`rotate(${leafUp ? 60 : 25} ${leafUp ? 66 : 70} ${leafUp ? 20 : 28})`} fill='var(--ng-leaf)' />
      <circle cx={50} cy={60} r={32} fill='var(--ng-mint)' stroke={INK} strokeWidth={3} />
      {mood === 'thinking' ? (
        <>
          <circle cx={39} cy={56} r={3.5} fill={INK} />
          <circle cx={61} cy={56} r={3.5} fill={INK} />
          <path d='M55 46 L67 43' stroke={INK} strokeWidth={3} strokeLinecap='round' />
          <path d='M43 72 Q50 75 57 72' fill='none' stroke={INK} strokeWidth={3} strokeLinecap='round' />
        </>
      ) : (
        <>
          <path d='M34 57 Q39 51 44 57' fill='none' stroke={INK} strokeWidth={3} strokeLinecap='round' />
          <path d='M56 57 Q61 51 66 57' fill='none' stroke={INK} strokeWidth={3} strokeLinecap='round' />
          <path d='M40 69 Q50 79 60 69' fill='none' stroke={INK} strokeWidth={3} strokeLinecap='round' />
        </>
      )}
    </svg>
  );
}

export function Flower({ grown, hue }: { grown: boolean; hue: number }) {
  const petal = ['var(--ng-petal)', 'var(--ng-sun)', 'var(--ng-sky)'][hue % 3];
  return (
    <svg viewBox='0 0 40 52' aria-hidden='true' data-grown={grown}>
      {grown ? (
        <>
          <line x1={20} x2={20} y1={24} y2={52} stroke='var(--ng-leaf)' strokeWidth={3} />
          <ellipse cx={13} cy={40} rx={6} ry={3} fill='var(--ng-leaf)' transform='rotate(-30 13 40)' />
          {[0, 72, 144, 216, 288].map((deg) => (
            <ellipse key={deg} cx={20} cy={11} rx={5} ry={8} fill={petal} stroke={INK} strokeWidth={1.5} transform={`rotate(${deg} 20 19)`} />
          ))}
          <circle cx={20} cy={19} r={5} fill='var(--ng-sun)' stroke={INK} strokeWidth={1.5} />
        </>
      ) : (
        <ellipse cx={20} cy={48} rx={5} ry={3.5} fill='#8a6a44' />
      )}
    </svg>
  );
}

export function Star({ on }: { on: boolean }) {
  return (
    <svg viewBox='0 0 24 24' aria-hidden='true' data-on={on}>
      <path
        d='M12 2.5l2.9 6.1 6.6.8-4.9 4.5 1.3 6.6L12 17.2l-5.9 3.3 1.3-6.6-4.9-4.5 6.6-.8z'
        fill={on ? 'var(--ng-sun)' : 'none'}
        stroke={INK}
        strokeWidth={1.6}
        strokeLinejoin='round'
      />
    </svg>
  );
}
