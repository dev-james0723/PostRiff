/** Note Garden engine, checked against docs/music-game/SPEC.md (levels, banks, formats, scoring). */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BANKS,
  LEVELS,
  PATTERNS,
  STAFF_NOTES,
  TOKEN_BEATS,
  answerRound,
  createRng,
  generateQuestions,
  isLevelUnlocked,
  midiToFrequency,
  nextQuestion,
  noteToMidi,
  positionPhrase,
  rhythmEvents,
  staffStep,
  starsFor,
  startRound,
  toneEvents
} from '../src/lib/music-game/curriculum.ts';

const seeds = Array.from({ length: 40 }, (_, i) => i * 7919 + 1);
const pair = (q) => q.stage.notes.join('-');
const tones = (events) => events.filter((e) => e.kind === 'tone');

test('the seeded RNG is deterministic and stays in [0, 1)', () => {
  const run = (seed) => { const r = createRng(seed); return Array.from({ length: 50 }, () => r()); };
  assert.deepEqual(run(7), run(7));
  assert.notDeepEqual(run(7), run(8));
  for (const n of run(7)) assert.ok(n >= 0 && n < 1);
});

test('pitch helpers follow SPEC: A4 = 440 Hz, C4 = MIDI 60, staff position E4 = 0, C4 = -2, G5 = 9', () => {
  assert.equal(midiToFrequency(69), 440);
  assert.ok(Math.abs(midiToFrequency(noteToMidi('C4')) - 261.63) < 0.01);
  assert.ok(Math.abs(midiToFrequency(noteToMidi('G5')) - 783.99) < 0.01);
  assert.deepEqual([staffStep('C4'), staffStep('D4'), staffStep('E4'), staffStep('F5'), staffStep('G5')], [-2, -1, 0, 8, 9]);
  assert.deepEqual(STAFF_NOTES, ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5']);
});

test('staff positions are described in words, never by letter', () => {
  assert.equal(positionPhrase('E4'), 'on the bottom line');
  assert.equal(positionPhrase('G4'), 'on the second line from the bottom');
  assert.equal(positionPhrase('F4'), 'in the bottom space');
  assert.equal(positionPhrase('C5'), 'in the third space from the bottom');
  assert.equal(positionPhrase('F5'), 'on the top line');
  assert.equal(positionPhrase('C4'), 'on its own little line below the staff');
  assert.equal(positionPhrase('D4'), 'just under the staff');
  assert.equal(positionPhrase('G5'), 'on top of the staff');
});

test('four levels in SPEC order with SPEC question counts (6, 8, 6, 6)', () => {
  assert.deepEqual(LEVELS.map((l) => [l.number, l.title, l.questionCount]), [
    [1, 'High or Low?', 6],
    [2, 'Note Names', 8],
    [3, 'Long and Short', 6],
    [4, 'Step or Skip?', 6]
  ]);
});

test('every question has one correct option, a hint, a reveal line and no duplicate option ids', () => {
  for (const level of LEVELS) {
    for (const seed of seeds) {
      const questions = generateQuestions(level.number, seed);
      assert.equal(questions.length, level.questionCount);
      for (const q of questions) {
        const ids = q.options.map((o) => o.id);
        assert.equal(new Set(ids).size, ids.length);
        assert.equal(ids.filter((id) => id === q.answer).length, 1);
        assert.ok(q.prompt && q.hint && q.reveal, q.id);
        for (const o of q.options) assert.ok(o.label.length > 0);
      }
    }
  }
});

test('the same seed always builds the same run', () => {
  for (const level of LEVELS) assert.deepEqual(generateQuestions(level.number, 5), generateQuestions(level.number, 5));
});

test('the correct answer never sits in the same position three times in a row', () => {
  for (const level of LEVELS) {
    for (const seed of seeds) {
      const positions = generateQuestions(level.number, seed).map((q) => q.options.findIndex((o) => o.id === q.answer));
      for (let i = 2; i < positions.length; i++) {
        assert.ok(!(positions[i] === positions[i - 1] && positions[i] === positions[i - 2]), `level ${level.number} seed ${seed}`);
      }
    }
  }
});

test('L1: two same/different warm-ups (one of each), then big, medium, medium, small up/down from the SPEC banks', () => {
  for (const seed of seeds) {
    const q = generateQuestions(1, seed);
    assert.deepEqual(q.map((x) => x.type), ['same-different', 'same-different', 'up-down', 'up-down', 'up-down', 'up-down']);
    assert.deepEqual(q.slice(0, 2).map((x) => x.answer).sort(), ['different', 'same']);
    for (const x of q.slice(0, 2)) assert.ok((x.answer === 'same' ? BANKS.l1Same : BANKS.l1Different).includes(pair(x)));
    assert.ok(BANKS.l1Big.includes(pair(q[2])));
    assert.ok(BANKS.l1Medium.includes(pair(q[3])) && BANKS.l1Medium.includes(pair(q[4])));
    assert.notEqual(pair(q[3]), pair(q[4]), 'drawn without replacement');
    assert.ok(BANKS.l1Small.includes(pair(q[5])));
    for (const x of q.slice(2)) {
      const [a, b] = x.stage.notes.map(noteToMidi);
      assert.equal(x.answer, b > a ? 'up' : 'down');
    }
  }
});

test('L1 sounds: 600 ms notes 400 ms apart; the hint replays at 900 ms with an 800 ms gap', () => {
  const q = generateQuestions(1, 3)[2];
  assert.deepEqual(tones(q.sound).map((e) => [e.at, e.seconds]), [[0, 0.6], [1, 0.6]]);
  assert.deepEqual(tones(q.slowSound).map((e) => [e.at, e.seconds]), [[0, 0.9], [1.7, 0.9]]);
  assert.deepEqual(tones(q.sound).map((e) => e.note), q.stage.notes);
});

test('L2: name, name, name, find (low garden) then name, name, name, find (high garden)', () => {
  const low = ['C4', 'D4', 'E4', 'F4', 'G4'];
  const high = ['A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5'];
  for (const seed of seeds) {
    const q = generateQuestions(2, seed);
    assert.deepEqual(q.map((x) => x.type), ['name-note', 'name-note', 'name-note', 'find-note', 'name-note', 'name-note', 'name-note', 'find-note']);
    const targets = q.map((x) => (x.type === 'name-note' ? x.stage.notes[0] : x.answer));
    for (const t of targets.slice(0, 4)) assert.ok(low.includes(t));
    assert.equal(new Set(targets.slice(0, 4)).size, 4, 'low garden without replacement');
    for (const t of targets.slice(4, 7)) assert.ok(high.includes(t) || t === 'E4' || t === 'G4');
    assert.ok(targets.slice(4, 7).some((t) => high.includes(t)));
    assert.ok(high.includes(targets[7]));
    assert.equal(new Set(targets.slice(4)).size, 4);
  }
});

test('L2 name-note options: the answer, a letter one step away and a letter three steps away', () => {
  const letters = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
  const distance = (a, b) => { const d = Math.abs(letters.indexOf(a) - letters.indexOf(b)); return Math.min(d, 7 - d); };
  for (const seed of seeds) {
    for (const q of generateQuestions(2, seed).filter((x) => x.type === 'name-note')) {
      assert.equal(q.answer, q.stage.notes[0][0]);
      assert.equal(q.options.length, 3);
      const others = q.options.map((o) => o.id).filter((id) => id !== q.answer).map((l) => distance(l, q.answer)).sort();
      assert.deepEqual(others, [1, 3]);
      assert.equal(q.stageLabel, `A note ${positionPhrase(q.stage.notes[0])}.`, 'the staff label gives the position, never the letter');
    }
  }
});

test('L2 find-note: three mini-staff cards with different letters, prompt names the target letter', () => {
  for (const seed of seeds) {
    for (const q of generateQuestions(2, seed).filter((x) => x.type === 'find-note')) {
      assert.equal(q.options.length, 3);
      assert.equal(new Set(q.options.map((o) => o.id[0])).size, 3);
      assert.equal(q.prompt, `Tap the ${q.answer[0]}!`);
      for (const o of q.options) assert.equal(o.ariaLabel, `A note ${positionPhrase(o.id)}`);
    }
  }
});

test('L3: count, count, fill, fill, hear, hear with SPEC banks and beat maths', () => {
  for (const seed of seeds) {
    const q = generateQuestions(3, seed);
    assert.deepEqual(q.map((x) => x.type), ['count-beats', 'count-beats', 'fill-bar', 'fill-bar', 'hear-rhythm', 'hear-rhythm']);
    assert.ok(['Q', 'H', 'W'].includes(q[0].stage.token));
    assert.ok(['E2', 'R', 'H'].includes(q[1].stage.token));
    for (const x of q.slice(0, 2)) {
      assert.deepEqual(x.options.map((o) => o.id).sort(), ['1', '2', '4']);
      assert.equal(x.answer, String(TOKEN_BEATS[x.stage.token]));
    }
    for (const x of q.slice(2, 4)) {
      const filled = x.stage.tokens.reduce((sum, t) => sum + (t ? TOKEN_BEATS[t] : 0), 0);
      assert.equal(filled + TOKEN_BEATS[x.answer], 4, 'the answer completes a 4-beat bar');
      assert.deepEqual(x.options.map((o) => o.id).sort(), ['H', 'Q', 'W']);
    }
    assert.notEqual(q[2].stage.tokens.join(), q[3].stage.tokens.join());
    for (const x of q.slice(4)) {
      assert.equal(x.options.length, 3);
      assert.ok(x.options.every((o) => PATTERNS[o.id]));
    }
    assert.notEqual(q[4].answer, q[5].answer, 'two different rhythm triples');
  }
});

test('every pattern and bar adds up to exactly 4 beats', () => {
  for (const [id, tokens] of Object.entries(PATTERNS)) assert.equal(tokens.reduce((s, t) => s + TOKEN_BEATS[t], 0), 4, id);
});

test('rhythm sound: 4 count-in clicks (first accented) then notes on C5 sounding 85% of their value at 80 bpm', () => {
  const events = rhythmEvents(['Q', 'H', 'R', 'E2'].slice(0, 3), { bpm: 80, countIn: true });
  const clicks = events.filter((e) => e.kind === 'click');
  const beat = 60 / 80;
  assert.ok(clicks.length >= 4);
  assert.deepEqual(clicks.slice(0, 4).map((c) => [c.at, c.accent]), [[0, true], [beat, false], [2 * beat, false], [3 * beat, false]]);
  const notes = tones(events);
  assert.deepEqual(notes.map((n) => n.note), ['C5', 'C5'], 'the rest is silent');
  assert.equal(notes[0].at, 4 * beat);
  assert.ok(Math.abs(notes[0].seconds - 0.85 * beat) < 1e-9);
  assert.ok(Math.abs(notes[1].seconds - 0.85 * 2 * beat) < 1e-9);
  const eighths = tones(rhythmEvents(['E2'], { bpm: 80 }));
  assert.equal(eighths.length, 2);
  assert.ok(Math.abs(eighths[1].at - beat / 2) < 1e-9);
});

test('no sound in the game is longer than the 3 s whole note', () => {
  for (const level of LEVELS) {
    for (const seed of seeds.slice(0, 10)) {
      for (const q of generateQuestions(level.number, seed)) {
        for (const e of [...q.sound, ...q.slowSound, ...q.answerSound]) if (e.kind === 'tone') assert.ok(e.seconds <= 3, `${q.id} ${e.seconds}`);
      }
    }
  }
});

test('L4: three seen step/skip (at least one of each), one heard (step or 5th), two heard (step or 3rd)', () => {
  const fifths = ['C4-G4', 'A4-E5', 'G5-C5'];
  for (const seed of seeds) {
    const q = generateQuestions(4, seed);
    assert.ok(q.every((x) => x.type === 'step-skip'));
    assert.deepEqual(q.map((x) => x.seen), [true, true, true, false, false, false]);
    assert.deepEqual(new Set(q.slice(0, 3).map((x) => x.answer)), new Set(['step', 'skip']));
    for (const x of q) {
      const d = Math.abs(staffStep(x.stage.notes[0]) - staffStep(x.stage.notes[1]));
      assert.equal(x.answer, d === 1 ? 'step' : 'skip');
      assert.ok((d === 1 ? BANKS.l4Steps : BANKS.l4Skips).includes(pair(x)));
    }
    assert.ok(q[3].answer === 'step' || fifths.includes(pair(q[3])));
    for (const x of q.slice(4)) assert.ok(x.answer === 'step' || Math.abs(staffStep(x.stage.notes[0]) - staffStep(x.stage.notes[1])) === 2);
    assert.equal(new Set(q.map(pair)).size, 6, 'no pair twice in a run');
  }
});

test('stars: 3 if at most one first-try miss, 2 if at least half, else 1 (SPEC n=6 and n=8)', () => {
  assert.deepEqual([6, 5, 4, 3, 2, 0].map((f) => starsFor(f, 6)), [3, 3, 2, 2, 1, 1]);
  assert.deepEqual([8, 7, 6, 4, 3].map((f) => starsFor(f, 8)), [3, 3, 2, 2, 1]);
});

test('unlocking: L1 open; finishing level k opens k+1; "open all levels" opens everything', () => {
  assert.equal(isLevelUnlocked(1, {}, false), true);
  assert.equal(isLevelUnlocked(2, {}, false), false);
  assert.equal(isLevelUnlocked(2, { 1: true }, false), true);
  assert.equal(isLevelUnlocked(3, { 1: true }, false), false);
  assert.equal(isLevelUnlocked(4, {}, true), true);
});

test('round: first miss marks the option tried; second miss reveals; first tries alone earn stars', () => {
  let round = startRound(3, 11); // 3-option questions
  const q = round.questions[0];
  const wrong = q.options.filter((o) => o.id !== q.answer).map((o) => o.id);
  let step = answerRound(round, wrong[0]);
  assert.equal(step.outcome, 'try-again');
  assert.deepEqual(step.round.tried, [wrong[0]]);
  assert.equal(answerRound(step.round, wrong[0]).outcome, 'ignored', 'a tried option cannot be picked again');
  step = answerRound(step.round, wrong[1]);
  assert.equal(step.outcome, 'reveal');
  assert.equal(step.round.status, 'revealed');
  assert.equal(answerRound(step.round, q.answer).outcome, 'ignored');
  round = nextQuestion(step.round);
  assert.equal(round.index, 1);
  assert.equal(round.flowers, 1, 'a flower grows for every finished question, right or wrong');
  while (!round.finished) round = nextQuestion(answerRound(round, round.questions[round.index].answer).round);
  assert.equal(round.firstTryCorrect, 5);
  assert.equal(round.stars, 3);
  assert.equal(round.flowers, 6);
});

test('round: with two options, one miss leaves one option, so the answer is revealed at once', () => {
  const round = startRound(1, 2);
  const q = round.questions[0];
  const step = answerRound(round, q.options.find((o) => o.id !== q.answer).id);
  assert.equal(step.outcome, 'reveal');
});

test('round: next does nothing until the question is settled; finished rounds stay finished', () => {
  const round = startRound(4, 9);
  assert.equal(nextQuestion(round), round);
  let r = round;
  while (!r.finished) r = nextQuestion(answerRound(r, r.questions[r.index].answer).round);
  assert.equal(nextQuestion(r), r);
  assert.equal(r.stars, 3);
});

test('toneEvents spaces notes by duration plus gap', () => {
  assert.deepEqual(toneEvents(['C4', 'D4'], 0.6, 0.4), [
    { kind: 'tone', note: 'C4', at: 0, seconds: 0.6 },
    { kind: 'tone', note: 'D4', at: 1, seconds: 0.6 }
  ]);
});
