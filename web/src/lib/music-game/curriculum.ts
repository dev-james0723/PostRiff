/**
 * Note Garden curriculum: levels, seeded question generation and round scoring for the children's music-theory game.
 * Pure (no imports) so node's test runner can load it directly (`web/tests/music-game.test.mjs`).
 */

export type LevelId = 'pitch' | 'staff' | 'beats' | 'motion';
/** A natural note between C4 and G5, written letter + octave ("E4"). */
export type NoteName = string;
export type NoteValue = 'quarter' | 'half' | 'dotted-half' | 'whole';
export type Tone = { note: NoteName; beats: number };
export type Choice = { id: string; label: string };
export type Visual =
  | { kind: 'pitch'; notes: NoteName[] }
  | { kind: 'staff'; notes: NoteName[] }
  | { kind: 'beats'; value: NoteValue }
  | { kind: 'motion'; notes: NoteName[] };

export type Question = {
  id: string;
  level: LevelId;
  prompt: string;
  choices: Choice[];
  answer: string;
  hint: string;
  /** Shown after a correct answer so the child learns why. */
  explain: string;
  sound: Tone[];
  visual: Visual;
};

export type Level = { id: LevelId; number: number; title: string; blurb: string; questionCount: number };

export const LEVELS: Level[] = [
  { id: 'pitch', number: 1, title: 'High or low', blurb: 'Hear two sounds. Did the second one go up or down?', questionCount: 6 },
  { id: 'staff', number: 2, title: 'Name the note', blurb: 'Find the letter name of a note on the treble staff.', questionCount: 6 },
  { id: 'beats', number: 3, title: 'Count the beats', blurb: 'How long does each note last?', questionCount: 6 },
  { id: 'motion', number: 4, title: 'Step, skip or repeat', blurb: 'Do two notes move next door, jump, or stay put?', questionCount: 6 }
];

/** C4 to G5, the naturals a beginner meets first on the treble staff. */
export const STAFF_NOTES: NoteName[] = ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5'];

const LETTERS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const SEMITONES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

export const PRAISE = ['Yes! Great listening.', 'You got it!', 'Well done!', 'Super! That is right.', 'Brilliant!', 'Spot on!'];
export const TRY_AGAIN = ['Nearly! Have another go.', 'Good try. Listen again and pick another one.', 'Not this one. You can do it!'];

/** mulberry32: tiny, fast and good enough to vary questions; the same seed always gives the same game. */
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

function pick<T>(rng: () => number, items: T[]): T {
  return items[Math.floor(rng() * items.length)];
}

function shuffle<T>(rng: () => number, items: T[]): T[] {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** An even mix of answers (e.g. 3 higher + 3 lower), so guessing one button never wins. */
function balanced<T>(rng: () => number, kinds: T[], count: number): T[] {
  return shuffle(rng, Array.from({ length: count }, (_, i) => kinds[i % kinds.length]));
}

function pitchQuestions(rng: () => number, count: number): Question[] {
  return balanced(rng, ['higher', 'lower'], count).map((answer, i) => {
    let low: NoteName;
    let high: NoteName;
    do {
      low = pick(rng, STAFF_NOTES);
      high = pick(rng, STAFF_NOTES);
    } while (noteToMidi(high) - noteToMidi(low) < 5);
    const notes = answer === 'higher' ? [low, high] : [high, low];
    return {
      id: `pitch-${i}`,
      level: 'pitch',
      prompt: 'Listen to two sounds. Is the second sound higher or lower?',
      choices: [
        { id: 'higher', label: 'Higher' },
        { id: 'lower', label: 'Lower' }
      ],
      answer,
      hint: 'High sounds are like a little bird. Low sounds are like a big bear. Play them again and point up or down as you listen.',
      explain: answer === 'higher' ? 'The second sound went up. It was higher.' : 'The second sound went down. It was lower.',
      sound: notes.map((note) => ({ note, beats: 1 })),
      visual: { kind: 'pitch', notes }
    };
  });
}

function staffHint(note: NoteName): string {
  const step = staffStep(note);
  if (step < -1) return 'This note sits on a short extra line below the staff. It is the note in the middle of the piano.';
  if (step === -1) return 'This note hangs just under the bottom line. It comes right after middle C.';
  if (step > 8) return 'This note sits just above the top line. It comes right after F.';
  if (step % 2 === 0) return 'This note sits on a line. From the bottom, the lines are E, G, B, D, F: Every Good Bird Does Fly.';
  return 'This note sits in a space. From the bottom, the spaces spell F, A, C, E: FACE.';
}

function staffQuestions(rng: () => number, count: number): Question[] {
  const questions: Question[] = [];
  let previous = '';
  for (let i = 0; i < count; i++) {
    const note = pick(rng, STAFF_NOTES.filter((n) => n !== previous));
    previous = note;
    const letter = note[0];
    const others = shuffle(rng, LETTERS.filter((l) => l !== letter)).slice(0, 3);
    const choices = LETTERS.filter((l) => l === letter || others.includes(l)).map((l) => ({ id: l, label: l }));
    questions.push({
      id: `staff-${i}`,
      level: 'staff',
      prompt: 'What is the name of this note?',
      choices,
      answer: letter,
      hint: staffHint(note),
      explain: `This note is ${letter}.`,
      sound: [{ note, beats: 1 }],
      visual: { kind: 'staff', notes: [note] }
    });
  }
  return questions;
}

const BEATS: Record<NoteValue, number> = { quarter: 1, half: 2, 'dotted-half': 3, whole: 4 };
const VALUE_NAMES: Record<NoteValue, string> = { quarter: 'quarter note', half: 'half note', 'dotted-half': 'dotted half note', whole: 'whole note' };
const VALUE_HINTS: Record<NoteValue, string> = {
  quarter: 'A filled-in note with a stem is short: one clap.',
  half: 'A hollow note with a stem lasts as long as two filled-in notes.',
  'dotted-half': 'The dot adds half again. A hollow note with a stem, plus its dot.',
  whole: 'A hollow note with no stem is the longest one here. Hold it for the whole bar.'
};

function beatQuestions(rng: () => number, count: number): Question[] {
  const values = Object.keys(BEATS) as NoteValue[];
  const order = shuffle(rng, values);
  while (order.length < count) order.push(pick(rng, values.filter((v) => v !== order[order.length - 1])));
  return order.slice(0, count).map((value, i) => {
    const beats = BEATS[value];
    return {
      id: `beats-${i}`,
      level: 'beats',
      prompt: 'How many beats does this note get?',
      choices: [1, 2, 3, 4].map((n) => ({ id: String(n), label: n === 1 ? '1 beat' : `${n} beats` })),
      answer: String(beats),
      hint: VALUE_HINTS[value],
      explain: `A ${VALUE_NAMES[value]} gets ${beats === 1 ? '1 beat' : `${beats} beats`}.`,
      sound: [{ note: 'G4', beats }],
      visual: { kind: 'beats', value }
    };
  });
}

const MOTION_DISTANCE: Record<string, number> = { repeat: 0, step: 1, skip: 2 };

function motionQuestions(rng: () => number, count: number): Question[] {
  return balanced(rng, ['step', 'skip', 'repeat'], count).map((answer, i) => {
    const distance = MOTION_DISTANCE[answer];
    const start = Math.floor(rng() * STAFF_NOTES.length);
    let direction = rng() < 0.5 ? -1 : 1;
    if (start + direction * distance < 0 || start + direction * distance >= STAFF_NOTES.length) direction = -direction;
    const notes = [STAFF_NOTES[start], STAFF_NOTES[start + direction * distance]];
    const explain =
      answer === 'repeat'
        ? 'Both notes were the same. That is a repeat.'
        : answer === 'step'
          ? 'The notes moved to the very next line or space. That is a step.'
          : 'The notes jumped over one line or space. That is a skip.';
    return {
      id: `motion-${i}`,
      level: 'motion',
      prompt: 'Listen to two notes. Do they step, skip or repeat?',
      choices: [
        { id: 'step', label: 'Step' },
        { id: 'skip', label: 'Skip' },
        { id: 'repeat', label: 'Repeat' }
      ],
      answer,
      hint: 'A step goes to the very next note. A skip jumps over one note. A repeat plays the same note again.',
      explain,
      sound: notes.map((note) => ({ note, beats: 1 })),
      visual: { kind: 'motion', notes }
    };
  });
}

const GENERATORS: Record<LevelId, (rng: () => number, count: number) => Question[]> = {
  pitch: pitchQuestions,
  staff: staffQuestions,
  beats: beatQuestions,
  motion: motionQuestions
};

export function getLevel(id: LevelId): Level {
  return LEVELS.find((l) => l.id === id) ?? LEVELS[0];
}

export function generateQuestions(levelId: LevelId, seed: number): Question[] {
  return GENERATORS[levelId](createRng(seed), getLevel(levelId).questionCount);
}

export function isCorrect(question: Question, choiceId: string): boolean {
  return question.answer === choiceId;
}

/** Finishing always earns a star; first-try answers earn more. Three stars allows one slip. */
export function starsFor(firstTryCorrect: number, total: number): number {
  if (total - firstTryCorrect <= 1) return 3;
  if (firstTryCorrect * 2 >= total) return 2;
  return 1;
}

export function isLevelUnlocked(id: LevelId, stars: Partial<Record<LevelId, number>>): boolean {
  const index = LEVELS.findIndex((l) => l.id === id);
  if (index <= 0) return true;
  return (stars[LEVELS[index - 1].id] ?? 0) >= 1;
}

export type Round = {
  level: LevelId;
  questions: Question[];
  index: number;
  /** Wrong choices already tried on the current question. */
  ruledOut: string[];
  answered: boolean;
  firstTryCorrect: number;
  finished: boolean;
  stars: number;
};

export type RoundStep = { round: Round; outcome: 'correct' | 'try-again' | 'ignored' };

export function startRound(level: LevelId, seed: number): Round {
  return { level, questions: generateQuestions(level, seed), index: 0, ruledOut: [], answered: false, firstTryCorrect: 0, finished: false, stars: 0 };
}

export function answerRound(round: Round, choiceId: string): RoundStep {
  const question = round.questions[round.index];
  const known = question?.choices.some((c) => c.id === choiceId);
  if (round.finished || round.answered || !known || round.ruledOut.includes(choiceId)) return { round, outcome: 'ignored' };
  if (isCorrect(question, choiceId)) {
    const firstTry = round.ruledOut.length === 0 ? 1 : 0;
    return { round: { ...round, answered: true, firstTryCorrect: round.firstTryCorrect + firstTry }, outcome: 'correct' };
  }
  return { round: { ...round, ruledOut: [...round.ruledOut, choiceId] }, outcome: 'try-again' };
}

export function nextQuestion(round: Round): Round {
  if (round.finished || !round.answered) return round;
  if (round.index + 1 >= round.questions.length) {
    return { ...round, finished: true, stars: starsFor(round.firstTryCorrect, round.questions.length) };
  }
  return { ...round, index: round.index + 1, ruledOut: [], answered: false };
}
