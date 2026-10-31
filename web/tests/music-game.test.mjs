import test from 'node:test';
import assert from 'node:assert/strict';
import {
  LEVELS,
  STAFF_NOTES,
  answerRound,
  createRng,
  generateQuestions,
  isCorrect,
  isLevelUnlocked,
  midiToFrequency,
  nextQuestion,
  noteToMidi,
  staffStep,
  starsFor,
  startRound
} from '../src/lib/music-game/curriculum.ts';

const seeds = [1, 2, 3, 42, 2026, 99999];

test('the seeded RNG is deterministic and stays in [0, 1)', () => {
  const a = createRng(7);
  const b = createRng(7);
  const c = createRng(8);
  const runA = Array.from({ length: 50 }, () => a());
  const runB = Array.from({ length: 50 }, () => b());
  const runC = Array.from({ length: 50 }, () => c());
  assert.deepEqual(runA, runB);
  assert.notDeepEqual(runA, runC);
  for (const n of runA) assert.ok(n >= 0 && n < 1);
});

test('pitch helpers: A4 is 440 Hz, C4 is MIDI 60 and the staff counts from the bottom line E4', () => {
  assert.equal(midiToFrequency(69), 440);
  assert.ok(Math.abs(midiToFrequency(60) - 261.63) < 0.01);
  assert.equal(noteToMidi('C4'), 60);
  assert.equal(noteToMidi('G5'), 79);
  assert.equal(staffStep('E4'), 0);
  assert.equal(staffStep('F5'), 8);
  assert.equal(staffStep('C4'), -2);
  assert.deepEqual(STAFF_NOTES[0], 'C4');
  assert.deepEqual(STAFF_NOTES.at(-1), 'G5');
});

test('there are four levels, each with 3 to 8 questions, in curriculum order', () => {
  assert.deepEqual(LEVELS.map((l) => l.id), ['pitch', 'staff', 'beats', 'motion']);
  for (const level of LEVELS) {
    assert.ok(level.questionCount >= 3 && level.questionCount <= 8, level.id);
    assert.ok(level.title.length > 0 && level.blurb.length > 0);
  }
});

test('every generated question is answerable: exactly one correct choice, a hint and a sound', () => {
  for (const level of LEVELS) {
    for (const seed of seeds) {
      const questions = generateQuestions(level.id, seed);
      assert.equal(questions.length, level.questionCount);
      for (const q of questions) {
        assert.equal(q.level, level.id);
        const ids = q.choices.map((c) => c.id);
        assert.equal(new Set(ids).size, ids.length, 'choice ids are unique');
        assert.equal(ids.filter((id) => isCorrect(q, id)).length, 1, 'one correct answer');
        assert.ok(q.prompt.length > 0 && q.hint.length > 0);
        assert.ok(q.sound.length >= 1);
        for (const tone of q.sound) assert.ok(STAFF_NOTES.includes(tone.note) && tone.beats > 0);
      }
    }
  }
});

test('the same seed gives the same questions; a different seed changes them', () => {
  for (const level of LEVELS) {
    assert.deepEqual(generateQuestions(level.id, 5), generateQuestions(level.id, 5));
  }
  const differs = LEVELS.some((l) => JSON.stringify(generateQuestions(l.id, 5)) !== JSON.stringify(generateQuestions(l.id, 6)));
  assert.ok(differs);
});

test('high/low questions compare two clearly different pitches and the answer matches their direction', () => {
  for (const seed of seeds) {
    for (const q of generateQuestions('pitch', seed)) {
      const [first, second] = q.sound.map((t) => noteToMidi(t.note));
      assert.ok(Math.abs(second - first) >= 5, 'at least a fourth apart for young ears');
      assert.equal(q.answer, second > first ? 'higher' : 'lower');
    }
  }
});

test('staff questions ask for the letter of the note drawn, with the sound of that same note', () => {
  for (const seed of seeds) {
    const questions = generateQuestions('staff', seed);
    for (let i = 0; i < questions.length; i++) {
      const q = questions[i];
      assert.equal(q.visual.kind, 'staff');
      assert.equal(q.answer, q.visual.notes[0][0]);
      assert.equal(q.sound[0].note, q.visual.notes[0]);
      assert.ok(q.choices.length >= 3 && q.choices.length <= 4);
      if (i > 0) assert.notEqual(q.visual.notes[0], questions[i - 1].visual.notes[0], 'no immediate repeats');
    }
  }
});

test('beat questions match the note value to its beat count', () => {
  const beats = { quarter: 1, half: 2, 'dotted-half': 3, whole: 4 };
  for (const seed of seeds) {
    for (const q of generateQuestions('beats', seed)) {
      assert.equal(q.visual.kind, 'beats');
      assert.equal(q.answer, String(beats[q.visual.value]));
      assert.equal(q.sound[0].beats, beats[q.visual.value]);
    }
  }
});

test('step/skip/repeat questions classify the distance between two staff notes', () => {
  for (const seed of seeds) {
    for (const q of generateQuestions('motion', seed)) {
      const [a, b] = q.visual.notes;
      const distance = Math.abs(staffStep(a) - staffStep(b));
      assert.equal(q.answer, distance === 0 ? 'repeat' : distance === 1 ? 'step' : 'skip');
      assert.ok(distance <= 2);
    }
  }
});

test('stars reward first-try answers but finishing always earns at least one star', () => {
  assert.equal(starsFor(6, 6), 3);
  assert.equal(starsFor(5, 6), 3);
  assert.equal(starsFor(4, 6), 2);
  assert.equal(starsFor(3, 6), 2);
  assert.equal(starsFor(2, 6), 1);
  assert.equal(starsFor(0, 6), 1);
  assert.equal(starsFor(4, 4), 3);
});

test('level 1 is always open; each next level opens once the one before has a star', () => {
  assert.equal(isLevelUnlocked('pitch', {}), true);
  assert.equal(isLevelUnlocked('staff', {}), false);
  assert.equal(isLevelUnlocked('staff', { pitch: 1 }), true);
  assert.equal(isLevelUnlocked('beats', { pitch: 3 }), false);
  assert.equal(isLevelUnlocked('motion', { pitch: 1, staff: 2, beats: 1 }), true);
});

test('a round lets a child retry after a wrong answer and only counts first tries for stars', () => {
  let round = startRound('pitch', 11);
  const total = round.questions.length;
  const first = round.questions[0];
  const wrong = first.choices.find((c) => !isCorrect(first, c.id)).id;

  let step = answerRound(round, wrong);
  assert.equal(step.outcome, 'try-again');
  assert.deepEqual(step.round.ruledOut, [wrong]);
  assert.equal(answerRound(step.round, wrong).outcome, 'ignored', 'ruled-out choices cannot be picked again');

  step = answerRound(step.round, first.answer);
  assert.equal(step.outcome, 'correct');
  assert.equal(step.round.firstTryCorrect, 0);
  assert.equal(answerRound(step.round, first.answer).outcome, 'ignored', 'no double answers before moving on');
  round = nextQuestion(step.round);
  assert.equal(round.index, 1);
  assert.deepEqual(round.ruledOut, []);

  while (!round.finished) {
    const q = round.questions[round.index];
    const result = answerRound(round, q.answer);
    assert.equal(result.outcome, 'correct');
    round = nextQuestion(result.round);
  }
  assert.equal(round.firstTryCorrect, total - 1);
  assert.equal(round.stars, starsFor(total - 1, total));
  assert.equal(nextQuestion(round), round, 'finished rounds stay finished');
});

test('nextQuestion does nothing until the current question is answered', () => {
  const round = startRound('beats', 3);
  assert.equal(nextQuestion(round), round);
});
