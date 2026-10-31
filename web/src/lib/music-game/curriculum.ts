/**
 * Note Garden engine: levels, question banks, seeded run generation, sound schedules and round scoring for the
 * children's music-theory game. Follows docs/music-game/SPEC.md (slots, banks, copy, stars, unlocking).
 * Pure (no imports) so node's test runner can load it directly (`web/tests/music-game.test.mjs`).
 */

export type LevelNumber = 1 | 2 | 3 | 4;
/** A natural note between C4 and G5, written letter + octave ("E4"). */
export type NoteName = string;
/** Q quarter, H half, W whole, E2 two beamed eighths, R quarter rest. */
export type Token = 'Q' | 'H' | 'W' | 'E2' | 'R';
export type QuestionType = 'same-different' | 'up-down' | 'name-note' | 'find-note' | 'count-beats' | 'fill-bar' | 'hear-rhythm' | 'step-skip';

export type SoundEvent = { kind: 'tone'; note: NoteName; at: number; seconds: number } | { kind: 'click'; at: number; accent: boolean };

export type Option = {
  id: string;
  /** Visible text. */
  label: string;
  /** Full accessible name when the visible text alone is not enough (it always contains the label). */
  ariaLabel?: string;
  icon?: 'same' | 'different' | 'up' | 'down' | 'step' | 'skip';
  /** find-note cards draw this note on a mini staff. */
  note?: NoteName;
  /** fill-bar and hear-rhythm options draw these symbols. */
  tokens?: Token[];
};

export type Stage =
  | { kind: 'dots'; notes: NoteName[] }
  | { kind: 'staff'; notes: NoteName[] }
  | { kind: 'none'; notes: NoteName[] }
  | { kind: 'symbol'; token: Token; notes: NoteName[] }
  | { kind: 'bar'; tokens: (Token | null)[]; notes: NoteName[] }
  | { kind: 'rhythm'; tokens: Token[]; notes: NoteName[] };

export type Question = {
  id: string;
  level: LevelNumber;
  type: QuestionType;
  /** L4 only: true when both notes are drawn on the staff before answering. */
  seen: boolean;
  prompt: string;
  options: Option[];
  answer: string;
  hint: string;
  /** Shown after a correct answer or a reveal so the child learns why. */
  reveal: string;
  /** Words for the stage picture (screen readers). Never names the answer. */
  stageLabel: string;
  sound: SoundEvent[];
  slowSound: SoundEvent[];
  /** Played after the question is settled (e.g. the whole bar with the gap filled). */
  answerSound: SoundEvent[];
  stage: Stage;
};

export type Level = { number: LevelNumber; title: string; goal: string; questionCount: number };

export const LEVELS: Level[] = [
  { number: 1, title: 'High or Low?', goal: 'Hear if music goes up or down.', questionCount: 6 },
  { number: 2, title: 'Note Names', goal: 'Name notes on the music staff.', questionCount: 8 },
  { number: 3, title: 'Long and Short', goal: 'Count how many beats a note lasts.', questionCount: 6 },
  { number: 4, title: 'Step or Skip?', goal: 'Hear notes step next door or skip.', questionCount: 6 }
];

/** C4 to G5, the naturals a beginner meets first on the treble staff. */
export const STAFF_NOTES: NoteName[] = ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5'];

/** SPEC banks. Pairs are written "first-second". */
export const BANKS = {
  l1Same: ['C4-C4', 'G4-G4', 'E5-E5'],
  l1Different: ['C4-C5', 'G4-C4', 'E5-G4'],
  l1Big: ['C4-C5', 'C5-C4', 'G4-G5', 'G5-G4', 'E4-C5', 'A4-C4'],
  l1Medium: ['C4-G4', 'G4-C4', 'F4-C5', 'D5-G4', 'G4-D5', 'C5-F4'],
  l1Small: ['G4-E4', 'E4-G4', 'D5-B4', 'B4-D5'],
  l2Low: ['C4', 'D4', 'E4', 'F4', 'G4'],
  l2High: ['A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5'],
  l3CountA: ['Q', 'H', 'W'] as Token[],
  l3CountB: ['E2', 'R', 'H'] as Token[],
  l3Bars: ['H Q _', 'Q Q _', '_', 'Q _ Q', 'H _', 'E2 Q _', 'H E2 _', 'R Q _'],
  l3Triples: ['P1 P2 P8', 'P2 P1 P3', 'P4 P5 P1', 'P5 P4 P3', 'P6 P1 P8', 'P8 P1 P2', 'P9 P1 P2'],
  l4Steps: ['C4-D4', 'E4-F4', 'G4-A4', 'B4-C5', 'D5-C5', 'F5-E5', 'A4-G4', 'G5-F5'],
  l4Skips: ['C4-E4', 'E4-G4', 'G4-B4', 'F4-A4', 'D5-B4', 'E5-C5', 'C4-G4', 'A4-E5', 'G5-C5'],
  l4Fifths: ['C4-G4', 'A4-E5', 'G5-C5']
};

export const PATTERNS: Record<string, Token[]> = {
  P1: ['Q', 'Q', 'Q', 'Q'],
  P2: ['H', 'H'],
  P3: ['W'],
  P4: ['Q', 'Q', 'H'],
  P5: ['H', 'Q', 'Q'],
  P6: ['E2', 'Q', 'E2', 'Q'],
  P8: ['E2', 'E2', 'Q', 'Q'],
  P9: ['Q', 'R', 'Q', 'R']
};

export const TOKEN_BEATS: Record<Token, number> = { Q: 1, H: 2, W: 4, E2: 1, R: 1 };
const TOKEN_NAMES: Record<Token, string> = { Q: 'quarter note', H: 'half note', W: 'whole note', E2: 'two eighth notes', R: 'quarter rest' };
const TOKEN_WORDS: Record<Token, string> = { Q: 'quarter', H: 'half', W: 'whole', E2: 'two eighths', R: 'rest' };
const SYLLABLES: Record<Token, string> = { Q: 'ta', H: 'ta-a', W: 'ta-a-a-a', E2: 'ti-ti', R: 'shh' };

export type PraiseKind = 'listen' | 'look' | 'count';
/** SPEC praise lines, grouped so the praise names the skill the child just used. */
export const PRAISE: Record<PraiseKind, string[]> = {
  listen: ['Yes! Great listening!', 'Brilliant ear!', 'You got it!', 'Correct! Your garden is growing!'],
  look: ["That's right! Nice looking!", 'You got it!', 'Sharp eyes!', 'Correct! Your garden is growing!'],
  count: ['Well done. You counted carefully!', 'You got it!', 'Correct! Your garden is growing!']
};

export function praiseKind(question: Question): PraiseKind {
  if (question.type === 'count-beats' || question.type === 'fill-bar') return 'count';
  if (question.type === 'name-note' || question.type === 'find-note' || (question.type === 'step-skip' && question.seen)) return 'look';
  return 'listen';
}

/**
 * The n-th praise line of the right kind. The lists differ in length and share lines, so a change of skill could land
 * on the line just shown; pass `previous` and the next line is used instead.
 */
export function praiseFor(question: Question, n: number, previous?: string): string {
  const lines = PRAISE[praiseKind(question)];
  const line = lines[n % lines.length];
  return line === previous ? lines[(n + 1) % lines.length] : line;
}
export const TRY_AGAIN = ['Not quite. Try again!', 'So close! Have another go.', 'Hmm, listen once more.'];
export const REVEAL_LEAD = "Let's see together.";
export const LEVEL_DONE: Record<number, string> = {
  3: 'Amazing! Your garden is full of flowers!',
  2: 'Great work! Your flowers are blooming!',
  1: 'You finished! Every try helps you grow.'
};

const LETTERS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const SEMITONES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const ORDINALS = ['bottom', 'second', 'third', 'fourth', 'top'];
const L1_TIMING = { seconds: 0.6, gap: 0.4 };
const SLOW_TIMING = { seconds: 0.9, gap: 0.8 };
const BPM = 80;
const SLOW_BPM = 60;
/** DESIGN §9: no single sound longer than the whole note at 80 bpm. */
const LONGEST_TONE = 3;

/** mulberry32: tiny, fast and good enough to vary questions; the same seed always gives the same run. */
export function createRng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function midiToFrequency(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

export function noteToMidi(note: NoteName): number {
  return 12 * (Number(note.slice(1)) + 1) + SEMITONES[note[0]];
}

/** Staff position counted in lines and spaces from the bottom line (E4 = 0, F5 = 8, middle C = -2). */
export function staffStep(note: NoteName): number {
  return Number(note.slice(1)) * 7 + LETTERS.indexOf(note[0]) - 30;
}

/** Where a note sits, in words a child (or a screen reader) can follow. Never says the letter. */
export function positionPhrase(note: NoteName): string {
  const step = staffStep(note);
  if (step <= -2) return 'on its own little line below the staff';
  if (step === -1) return 'just under the staff';
  if (step >= 9) return 'on top of the staff';
  if (step % 2 === 0) {
    const n = step / 2;
    return n === 0 ? 'on the bottom line' : n === 4 ? 'on the top line' : `on the ${ORDINALS[n]} line from the bottom`;
  }
  const n = (step - 1) / 2;
  return n === 0 ? 'in the bottom space' : n === 3 ? 'in the top space' : `in the ${ORDINALS[n]} space from the bottom`;
}

const round3 = (n: number) => Math.round(n * 1000) / 1000;

export function toneEvents(notes: NoteName[], seconds: number, gap: number): SoundEvent[] {
  return notes.map((note, i) => ({ kind: 'tone', note, at: round3(i * (seconds + gap)), seconds }));
}

/** A rhythm on C5 at `bpm`, each note sounding 85% of its value, with an optional 4-click count-in and beat clicks. */
export function rhythmEvents(tokens: (Token | null)[], options: { bpm: number; countIn?: boolean; clicks?: boolean }): SoundEvent[] {
  const beat = 60 / options.bpm;
  const events: SoundEvent[] = [];
  const start = options.countIn ? 4 * beat : 0;
  if (options.countIn) for (let i = 0; i < 4; i++) events.push({ kind: 'click', at: i * beat, accent: i === 0 });
  let elapsed = 0;
  for (const token of tokens) {
    const beats = token ? TOKEN_BEATS[token] : 1;
    if (options.clicks) for (let i = 0; i < beats; i++) events.push({ kind: 'click', at: start + (elapsed + i) * beat, accent: false });
    if (token === 'E2') {
      for (const half of [0, 0.5]) events.push({ kind: 'tone', note: 'C5', at: start + (elapsed + half) * beat, seconds: 0.85 * 0.5 * beat });
    } else if (token && token !== 'R') {
      events.push({ kind: 'tone', note: 'C5', at: start + elapsed * beat, seconds: Math.min(LONGEST_TONE, 0.85 * beats * beat) });
    }
    elapsed += beats;
  }
  return events;
}

function shuffle<T>(rng: () => number, items: T[]): T[] {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Draw without replacement: removes the picked item from `pool`. */
function draw<T>(rng: () => number, pool: T[], allowed: (item: T) => boolean = () => true): T {
  const candidates = pool.filter(allowed);
  const item = candidates[Math.floor(rng() * candidates.length)];
  pool.splice(pool.indexOf(item), 1);
  return item;
}

const plural = (n: number) => (n === 1 ? '1 beat' : `${n} beats`);
const notesOf = (pair: string) => pair.split('-');

type Draft = Omit<Question, 'id' | 'level' | 'seen' | 'slowSound' | 'answerSound' | 'stageLabel'> &
  Partial<Pick<Question, 'seen' | 'slowSound' | 'answerSound' | 'stageLabel'>>;

function dotsLabel(notes: NoteName[]): string {
  const [a, b] = notes.map(noteToMidi);
  if (a === b) return 'Picture of the sound: two dots at the same height.';
  return `Picture of the sound: the second dot is ${b > a ? 'higher' : 'lower'}.`;
}

function sameDifferent(pair: string): Draft {
  const notes = notesOf(pair);
  const same = notes[0] === notes[1];
  return {
    type: 'same-different',
    prompt: 'Listen. Same or different?',
    options: [
      { id: 'same', label: 'Same', icon: 'same' },
      { id: 'different', label: 'Different', icon: 'different' }
    ],
    answer: same ? 'same' : 'different',
    hint: "Let's listen slowly.",
    reveal: same ? 'They were the same note.' : 'They were different notes.',
    stageLabel: dotsLabel(notes),
    sound: toneEvents(notes, L1_TIMING.seconds, L1_TIMING.gap),
    slowSound: toneEvents(notes, SLOW_TIMING.seconds, SLOW_TIMING.gap),
    stage: { kind: 'dots', notes }
  };
}

function upDown(pair: string): Draft {
  const notes = notesOf(pair);
  const up = noteToMidi(notes[1]) > noteToMidi(notes[0]);
  return {
    type: 'up-down',
    prompt: 'Listen. Did the music go up or down?',
    options: [
      { id: 'up', label: 'Up', icon: 'up' },
      { id: 'down', label: 'Down', icon: 'down' }
    ],
    answer: up ? 'up' : 'down',
    hint: "Let's listen slowly.",
    reveal: up ? 'It went up, higher like a bird.' : 'It went down, lower like a frog.',
    stageLabel: dotsLabel(notes),
    sound: toneEvents(notes, L1_TIMING.seconds, L1_TIMING.gap),
    slowSound: toneEvents(notes, SLOW_TIMING.seconds, SLOW_TIMING.gap),
    stage: { kind: 'dots', notes }
  };
}

function noteHint(note: NoteName): string {
  const step = staffStep(note);
  if (step <= -2) return "This note has its own little line below the staff. It's Middle C!";
  if (step === -1) return "This note hangs just under the bottom line. It's one step up from Middle C.";
  if (step >= 9) return 'This note sits on top of the staff, one step above the top line (F).';
  if (step % 2 === 0) return 'Line notes from the bottom: E G B D F. Every Green Bug Digs Fast!';
  return 'Space notes from the bottom spell F A C E.';
}

const noteReveal = (note: NoteName) => `This is ${note[0]}. It sits ${positionPhrase(note)}.`;

function nameNote(rng: () => number, note: NoteName): Draft {
  const letter = note[0];
  const at = LETTERS.indexOf(letter);
  const near = LETTERS[(at + (rng() < 0.5 ? 1 : 6)) % 7];
  const far = LETTERS[(at + (rng() < 0.5 ? 3 : 4)) % 7];
  const tone = toneEvents([note], L1_TIMING.seconds, 0);
  return {
    type: 'name-note',
    prompt: 'What is this note?',
    options: shuffle(rng, [letter, near, far]).map((l) => ({ id: l, label: l })),
    answer: letter,
    hint: noteHint(note),
    reveal: noteReveal(note),
    stageLabel: `A note ${positionPhrase(note)}.`,
    sound: tone,
    stage: { kind: 'staff', notes: [note] }
  };
}

function findNote(rng: () => number, target: NoteName, distractorPool: NoteName[]): Draft {
  const used = new Set([target[0]]);
  const cards = [target];
  for (const candidate of shuffle(rng, distractorPool)) {
    if (cards.length === 3) break;
    if (used.has(candidate[0])) continue;
    used.add(candidate[0]);
    cards.push(candidate);
  }
  return {
    type: 'find-note',
    prompt: `Tap the ${target[0]}!`,
    options: shuffle(rng, cards).map((note) => ({ id: note, label: `A note ${positionPhrase(note)}`, ariaLabel: `A note ${positionPhrase(note)}`, note })),
    answer: target,
    hint: noteHint(target),
    reveal: noteReveal(target),
    stageLabel: '',
    sound: [],
    slowSound: [],
    answerSound: toneEvents([target], L1_TIMING.seconds, 0),
    stage: { kind: 'none', notes: [] }
  };
}

const BEAT_OPTIONS: Option[] = [1, 2, 4].map((n) => ({ id: String(n), label: plural(n) }));

function countBeats(token: Token): Draft {
  const beats = TOKEN_BEATS[token];
  const reveal =
    token === 'E2' ? 'Two eighth notes last 1 beat together.' : token === 'R' ? 'A quarter rest lasts 1 quiet beat.' : `A ${TOKEN_NAMES[token]} lasts ${plural(beats)}.`;
  return {
    type: 'count-beats',
    prompt: 'How many beats?',
    options: BEAT_OPTIONS,
    answer: String(beats),
    hint: 'Clap and count: 1, 2, 3, 4. How many claps does the note last?',
    reveal,
    stageLabel: token === 'E2' ? 'Two eighth notes joined by a beam.' : `A ${TOKEN_NAMES[token]}.`,
    sound: rhythmEvents([token], { bpm: BPM, clicks: true }),
    stage: { kind: 'symbol', token, notes: [] }
  };
}

const FILL_OPTIONS: Option[] = (['Q', 'H', 'W'] as Token[]).map((t) => ({
  id: t,
  label: plural(TOKEN_BEATS[t]),
  ariaLabel: `${TOKEN_NAMES[t][0].toUpperCase()}${TOKEN_NAMES[t].slice(1)}, ${plural(TOKEN_BEATS[t])}`,
  tokens: [t]
}));

function fillBar(rng: () => number, bar: string): Draft {
  const tokens = bar.split(' ').map((t) => (t === '_' ? null : (t as Token)));
  const known = tokens.filter((t): t is Token => t !== null);
  const have = known.reduce((sum, t) => sum + TOKEN_BEATS[t], 0);
  const answer = (['Q', 'H', 'W'] as Token[]).find((t) => TOKEN_BEATS[t] === 4 - have) as Token;
  const sum = known.length === 0 ? '' : known.length === 1 ? `That's ${plural(have)}. ` : `${known.map((t) => TOKEN_BEATS[t]).join(' + ')} = ${plural(have)}. `;
  const reveal =
    known.length === 0
      ? "An empty bar needs all 4 beats, so it's a whole note."
      : `${sum}We need ${4 - have} more, so it's a ${TOKEN_NAMES[answer]}.`;
  const parts = tokens.map((t) => (t ? TOKEN_NAMES[t] : 'a gap'));
  return {
    type: 'fill-bar',
    prompt: 'Which note fills the gap?',
    options: shuffle(rng, FILL_OPTIONS),
    answer,
    hint: 'Every bar has 4 beats. Count the beats you already have.',
    reveal,
    stageLabel: `A bar of 4 beats: ${parts.join(', ')}.`,
    sound: rhythmEvents(tokens, { bpm: BPM, clicks: true }),
    answerSound: rhythmEvents(tokens.map((t) => t ?? answer), { bpm: BPM, clicks: true }),
    stage: { kind: 'bar', tokens, notes: [] }
  };
}

const RHYTHM_FEEL: Record<Token, string> = { Q: 'short', H: 'long', W: 'very long', E2: 'quick quick', R: 'rest' };

function hearRhythm(rng: () => number, triple: string): Draft {
  const ids = triple.split(' ');
  const target = ids[0];
  return {
    type: 'hear-rhythm',
    prompt: 'Which rhythm did you hear?',
    // Labels (Rhythm A/B/C) are given once the final order is fixed; see labelRhythms.
    options: shuffle(rng, ids).map((id) => ({ id, label: id, tokens: PATTERNS[id] })),
    answer: target,
    hint: 'Listen again, slowly.',
    reveal: `You heard ${PATTERNS[target].map((t) => SYLLABLES[t]).join(' ')}.`,
    stageLabel: `Picture of the rhythm: ${PATTERNS[target].map((t) => RHYTHM_FEEL[t]).join(', ')}.`,
    sound: rhythmEvents(PATTERNS[target], { bpm: BPM, countIn: true }),
    slowSound: rhythmEvents(PATTERNS[target], { bpm: SLOW_BPM, countIn: true }),
    stage: { kind: 'rhythm', tokens: PATTERNS[target], notes: [] }
  };
}

function labelRhythms(question: Question): Question {
  if (question.type !== 'hear-rhythm') return question;
  return {
    ...question,
    options: question.options.map((o, i) => {
      const label = `Rhythm ${'ABC'[i]}`;
      return { ...o, label, ariaLabel: `${label}: ${(o.tokens ?? []).map((t) => TOKEN_WORDS[t]).join(', ')}` };
    })
  };
}

function stepSkip(pair: string, seen: boolean): Draft {
  const notes = notesOf(pair);
  const distance = Math.abs(staffStep(notes[0]) - staffStep(notes[1]));
  const step = distance === 1;
  const jumped = distance - 1;
  return {
    type: 'step-skip',
    seen,
    prompt: seen ? 'Look and listen. Step or skip?' : 'Listen. Step or skip?',
    options: [
      { id: 'step', label: 'Step', icon: 'step' },
      { id: 'skip', label: 'Skip', icon: 'skip' }
    ],
    answer: step ? 'step' : 'skip',
    hint: seen ? 'Look! Next-door notes are steps. Line to line or space to space is a skip.' : "Let's listen slowly.",
    reveal: step ? 'That was a step, to the next-door note.' : `That was a skip. It jumped over ${jumped} ${jumped === 1 ? 'note' : 'notes'}.`,
    stageLabel: seen
      ? `Two notes: the first ${positionPhrase(notes[0])}, the second ${positionPhrase(notes[1])}.`
      : 'Two hidden notes. Listen to them.',
    sound: toneEvents(notes, L1_TIMING.seconds, L1_TIMING.gap),
    slowSound: toneEvents(notes, SLOW_TIMING.seconds, SLOW_TIMING.gap),
    stage: { kind: 'staff', notes }
  };
}

function level1(rng: () => number): Draft[] {
  const warmups = shuffle(rng, [sameDifferent(draw(rng, BANKS.l1Same.slice())), sameDifferent(draw(rng, BANKS.l1Different.slice()))]);
  const medium = BANKS.l1Medium.slice();
  return [...warmups, upDown(draw(rng, BANKS.l1Big.slice())), upDown(draw(rng, medium)), upDown(draw(rng, medium)), upDown(draw(rng, BANKS.l1Small.slice()))];
}

function level2(rng: () => number): Draft[] {
  const low = BANKS.l2Low.slice();
  const high = [...BANKS.l2High, rng() < 0.5 ? 'E4' : 'G4'];
  const out: Draft[] = [];
  for (let i = 0; i < 3; i++) out.push(nameNote(rng, draw(rng, low)));
  out.push(findNote(rng, draw(rng, low), BANKS.l2Low));
  const highNames: NoteName[] = [];
  for (let i = 0; i < 3; i++) {
    // At least one of Q5-Q7 comes from the high garden itself, not only the low-garden revisit.
    const mustBeHigh = i === 2 && highNames.every((n) => !BANKS.l2High.includes(n));
    highNames.push(draw(rng, high, (n) => !mustBeHigh || BANKS.l2High.includes(n)));
  }
  for (const note of highNames) out.push(nameNote(rng, note));
  out.push(findNote(rng, draw(rng, high, (n) => BANKS.l2High.includes(n)), STAFF_NOTES));
  return out;
}

function level3(rng: () => number): Draft[] {
  const first = draw(rng, BANKS.l3CountA.slice());
  const second = draw(rng, BANKS.l3CountB.slice(), (t) => t !== first);
  const bars = BANKS.l3Bars.slice();
  const triples = BANKS.l3Triples.slice();
  return [countBeats(first), countBeats(second), fillBar(rng, draw(rng, bars)), fillBar(rng, draw(rng, bars)), hearRhythm(rng, draw(rng, triples)), hearRhythm(rng, draw(rng, triples))];
}

function level4(rng: () => number): Draft[] {
  const steps = BANKS.l4Steps.slice();
  const skips = BANKS.l4Skips.slice();
  const seenKinds = shuffle(rng, ['step', 'skip', rng() < 0.5 ? 'step' : 'skip']);
  const seen = seenKinds.map((kind) => stepSkip(draw(rng, kind === 'step' ? steps : skips), true));
  const thirds = (p: string) => Math.abs(staffStep(notesOf(p)[0]) - staffStep(notesOf(p)[1])) === 2;
  const fourth = rng() < 0.5 ? draw(rng, steps) : draw(rng, skips, (p) => BANKS.l4Fifths.includes(p));
  const heard = [fourth];
  for (let i = 0; i < 2; i++) heard.push(rng() < 0.5 ? draw(rng, steps) : draw(rng, skips, thirds));
  return [...seen, ...heard.map((p) => stepSkip(p, false))];
}

const BUILDERS: Record<LevelNumber, (rng: () => number) => Draft[]> = { 1: level1, 2: level2, 3: level3, 4: level4 };

/** SPEC: never put the correct answer in the same position three times in a row. */
function spreadAnswers(rng: () => number, questions: Question[]): Question[] {
  const positions: number[] = [];
  return questions.map((q) => {
    let options = q.options;
    let at = options.findIndex((o) => o.id === q.answer);
    const n = positions.length;
    if (n >= 2 && positions[n - 1] === at && positions[n - 2] === at) {
      const others = options.map((_, i) => i).filter((i) => i !== at);
      const to = others[Math.floor(rng() * others.length)];
      options = options.slice();
      [options[at], options[to]] = [options[to], options[at]];
      at = to;
    }
    positions.push(at);
    return options === q.options ? q : { ...q, options };
  });
}

export function getLevel(number: number): Level {
  return LEVELS.find((l) => l.number === number) ?? LEVELS[0];
}

export function generateQuestions(level: LevelNumber, seed: number): Question[] {
  const rng = createRng(seed);
  const drafts = BUILDERS[level](rng);
  const questions = drafts.map((d, i): Question => ({
    seen: false,
    slowSound: d.sound,
    answerSound: d.sound,
    stageLabel: '',
    ...d,
    id: `l${level}-q${i + 1}`,
    level
  }));
  return spreadAnswers(rng, questions).map(labelRhythms);
}

/** Finishing always earns a star; first tries earn more. Hints never cost stars. */
export function starsFor(firstTryCorrect: number, total: number): number {
  if (firstTryCorrect >= total - 1) return 3;
  if (firstTryCorrect >= Math.ceil(total / 2)) return 2;
  return 1;
}

export function isLevelUnlocked(level: number, done: Partial<Record<number, boolean>>, allOpen: boolean): boolean {
  return allOpen || level <= 1 || done[level - 1] === true;
}

export type Round = {
  level: LevelNumber;
  questions: Question[];
  index: number;
  /** Wrong options already tried on the current question. */
  tried: string[];
  status: 'asking' | 'correct' | 'revealed';
  firstTryCorrect: number;
  /** One per finished question, right or wrong. Flowers never wilt. */
  flowers: number;
  finished: boolean;
  stars: number;
};

export type RoundStep = { round: Round; outcome: 'correct' | 'try-again' | 'reveal' | 'ignored' };

export function startRound(level: LevelNumber, seed: number): Round {
  return { level, questions: generateQuestions(level, seed), index: 0, tried: [], status: 'asking', firstTryCorrect: 0, flowers: 0, finished: false, stars: 0 };
}

export function answerRound(round: Round, optionId: string): RoundStep {
  const question = round.questions[round.index];
  const known = question?.options.some((o) => o.id === optionId);
  if (round.finished || round.status !== 'asking' || !known || round.tried.includes(optionId)) return { round, outcome: 'ignored' };
  if (optionId === question.answer) {
    const firstTry = round.tried.length === 0 ? 1 : 0;
    return { round: { ...round, status: 'correct', firstTryCorrect: round.firstTryCorrect + firstTry }, outcome: 'correct' };
  }
  const tried = [...round.tried, optionId];
  // Second miss, or only one option left: show the answer so nobody gets stuck.
  if (tried.length >= 2 || question.options.length - tried.length <= 1) return { round: { ...round, tried, status: 'revealed' }, outcome: 'reveal' };
  return { round: { ...round, tried }, outcome: 'try-again' };
}

export function nextQuestion(round: Round): Round {
  if (round.finished || round.status === 'asking') return round;
  const flowers = round.flowers + 1;
  if (round.index + 1 >= round.questions.length) {
    return { ...round, flowers, finished: true, stars: starsFor(round.firstTryCorrect, round.questions.length) };
  }
  return { ...round, flowers, index: round.index + 1, tried: [], status: 'asking' };
}
