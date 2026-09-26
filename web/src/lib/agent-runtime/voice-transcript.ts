/**
 * Voice Mode's transcript and hang-up timing, as pure functions (no React, no timers, no transport), so the rules are
 * tested in node (`web/tests/voice-transcript.test.cjs`) and the session only wires them to live events.
 *
 * "Stop talking" is real: GPT-Live has no response cancel, so the reply in flight keeps streaming its transcript after
 * the person stops it. Those words are dropped (and the audio stays muted) until the person speaks again or a new
 * delegation result is being said. The line that was cut off ends there, marked `stopped`.
 */

export interface TranscriptLine {
  id: string;
  /** Increases with every new line; a delegation takes the words after the last one it used (the list itself is capped). */
  seq: number;
  role: 'user' | 'assistant';
  text: string;
  final: boolean;
  startMs: number;
  endMs: number;
  /** Rafii's line was cut off by "Stop talking" (shown with a short "(stopped)" note). */
  stopped?: boolean;
}

export interface TranscriptState {
  lines: TranscriptLine[];
  /** After "Stop talking": Rafii's words are dropped until the person speaks or a new result is being said. */
  stopped: boolean;
}

export type TranscriptEvent =
  | { type: 'delta'; role: 'user' | 'assistant'; delta: string; startMs: number; endMs: number }
  /** `inFlight`: Rafii was speaking (or its words were still arriving) when the person stopped it. */
  | { type: 'stop'; inFlight: boolean }
  /** A new delegation result is about to be said: Rafii may be heard again. */
  | { type: 'resume' };

export interface TranscriptStep {
  state: TranscriptState;
  /** Lines this event finished; the session stores them. */
  closed: TranscriptLine[];
  /** This event ended a "Stop talking" (the audio can be unmuted). */
  resumed: boolean;
  /** Rafii's words were dropped because the person stopped the reply. */
  dropped: boolean;
}

export const UTTERANCE_GAP_MS = 1200;
export const MAX_LINES = 60;

export type NewLine = () => { id: string; seq: number };

/** Apply one live event to the transcript. Never mutates `state`. */
export function applyTranscript(
  state: TranscriptState,
  event: TranscriptEvent,
  newLine: NewLine,
  options: { gapMs?: number; maxLines?: number } = {}
): TranscriptStep {
  const gapMs = options.gapMs ?? UTTERANCE_GAP_MS;
  const maxLines = options.maxLines ?? MAX_LINES;
  if (event.type === 'resume') {
    return { state: state.stopped ? { ...state, stopped: false } : state, closed: [], resumed: state.stopped, dropped: false };
  }
  if (event.type === 'stop') {
    const lines = [...state.lines];
    const last = lines.at(-1);
    const closed: TranscriptLine[] = [];
    // Only the reply being spoken is cut off; a line Rafii finished earlier keeps its words as they were.
    if (event.inFlight && last && last.role === 'assistant' && !last.final) {
      lines[lines.length - 1] = { ...last, final: true, stopped: true };
      closed.push(lines[lines.length - 1]);
    }
    return { state: { lines, stopped: true }, closed, resumed: false, dropped: false };
  }
  let stopped = state.stopped;
  let resumed = false;
  if (event.role === 'assistant' && stopped) {
    // The stopped reply is still streaming from GPT-Live: none of it is shown, stored or counted.
    return { state, closed: [], resumed: false, dropped: true };
  }
  if (event.role === 'user' && stopped && event.delta.trim()) {
    stopped = false;
    resumed = true;
  }
  const lines = [...state.lines];
  const last = lines.at(-1);
  const closed: TranscriptLine[] = [];
  if (last && last.role === event.role && !last.final && event.startMs - last.endMs < gapMs) {
    lines[lines.length - 1] = { ...last, text: last.text + event.delta, endMs: event.endMs };
  } else {
    if (last && !last.final) {
      lines[lines.length - 1] = { ...last, final: true };
      closed.push(lines[lines.length - 1]);
    }
    const { id, seq } = newLine();
    lines.push({ id, seq, role: event.role, text: event.delta.trimStart(), final: false, startMs: event.startMs, endMs: event.endMs });
  }
  return { state: { lines: lines.slice(-maxLines), stopped }, closed, resumed, dropped: false };
}

/**
 * The words a delegation acts on: every user line after the last one a delegation used. The open line is finished
 * here, so words said after this point start a new line and belong to the next request instead of this one.
 */
export function takeRequest(lines: TranscriptLine[], afterSeq: number): { request: string; lines: TranscriptLine[]; closed: TranscriptLine[]; lastSeq: number } {
  const next = [...lines];
  const fresh = next.filter((line) => line.seq > afterSeq && line.role === 'user' && line.text.trim());
  const last = next.at(-1);
  const closed: TranscriptLine[] = [];
  if (last && !last.final) {
    next[next.length - 1] = { ...last, final: true };
    closed.push(next[next.length - 1]);
  }
  return {
    request: fresh.map((line) => line.text.trim()).join(' ').trim(),
    lines: closed.length ? next : lines,
    closed,
    lastSeq: last?.seq ?? afterSeq
  };
}

/** The latest user line, when nothing (no reply, no later words) has come after it. */
export function lastUserLine(lines: TranscriptLine[]): TranscriptLine | null {
  const last = lines.at(-1);
  return last && last.role === 'user' ? last : null;
}

export interface HangUp {
  /** When the goodbye was heard (or the end-call command arrived). */
  at: number;
  /** Rafii's reply has produced at least one word since then. */
  replied: boolean;
  /** Last time Rafii was heard: a transcript word or audible output, whichever is later. */
  lastSoundAt: number;
}

export const HANG_UP_QUIET_MS = 1200;
export const HANG_UP_MAX_MS = 10_000;

/**
 * After a goodbye the call ends once Rafii's reply has started and then gone quiet for about 1.2 s, and at most 10 s
 * after the goodbye whatever happens (a reply that never comes, or one that runs on).
 */
export function hangUpDue(hangUp: HangUp, now: number, options: { quietMs?: number; maxMs?: number } = {}): boolean {
  if (now - hangUp.at >= (options.maxMs ?? HANG_UP_MAX_MS)) return true;
  if (!hangUp.replied) return false;
  return now - Math.max(hangUp.lastSoundAt, hangUp.at) >= (options.quietMs ?? HANG_UP_QUIET_MS);
}
