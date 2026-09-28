'use client';

/**
 * Voice Mode controller: one GPT-Live session per tab, outside React, so moving between pages or re-framing the panel
 * (dock, sheet, drawer) never tears the call down (spec §6.2, §27). It holds no business logic: every request the
 * voice front-end delegates goes to the same `agent/turns` endpoint as text, in the same conversation, and Rafii only
 * says what that endpoint returned (its `speakableSummary`). Approvals are decided on the server; a spoken "yes" is just
 * another delegated request the backend binds (or refuses to bind) to one proposal.
 *
 * Panel commands are the exception, because they must feel instant (Contract 4): "take me to Channels", "show me how to
 * connect Instagram", "slower", "mute", "bye". A delegated request that is only one of these (`panel-commands.ts`) is
 * carried out here through the registered panel actions and confirmed in one sentence, without an agent turn. When the
 * panel can't do it on this screen, Rafii says so and the agent takes the request as before.
 *
 * "Stop talking" is real: GPT-Live has no response cancel, so the rest of the stopped reply (audio and words) is dropped
 * until the person speaks again or a new result is being said. A goodbye ends the call once Rafii's reply has gone
 * quiet. The transcript and hang-up rules are pure functions in `voice-transcript.ts`.
 *
 * State shown to the person is the session's real state: transcript deltas, the remote audio level, delegation results,
 * `session.closed` and the connection state — never timers.
 */
import { useSyncExternalStore } from 'react';
import { voiceOpening } from './voice-opening';
import { ApiError } from '@/lib/api/client';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';
import type { AgentApi } from './client';
import { createTransport, VoiceTransportError, type LiveEvent, type LiveTransport } from './live-transport';
import { panelActions } from './panel-actions';
import { confirmation, isFarewell, matchPanelCommand, styleInstructions, voiceCommandsIn, type PanelCommand, type VoiceCommand } from './panel-commands';
import type { AgentStylePatch } from './style';
import type { AgentResult, AgentTurnResponse } from './types';
import { applyTranscript, hangUpDue, lastUserLine, takeRequest, UTTERANCE_GAP_MS, type HangUp, type TranscriptEvent, type TranscriptLine } from './voice-transcript';

export type { TranscriptLine } from './voice-transcript';

export type VoiceState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'ending' | 'ended' | 'error';
export type Speaker = 'user' | 'rafii' | null;

export interface Delegation {
  id: string;
  request: string;
  status: 'collecting' | 'running' | 'done' | 'failed' | 'cancelled';
  runId?: string | null;
  result?: AgentResult | null;
  error?: string;
  startedAt: number;
  finishedAt?: number;
  /** Carried out in the browser as a panel command, without an agent turn. */
  local?: boolean;
}

export interface VoiceSnapshot {
  state: VoiceState;
  error: { code: string; message: string } | null;
  micMuted: boolean;
  /** True after "Stop talking" until the person speaks again or a new result is being said. */
  outputMuted: boolean;
  /** A goodbye was heard: the call ends once Rafii's reply has gone quiet. */
  endingAfterReply: boolean;
  speaker: Speaker;
  level: number;
  transcript: TranscriptLine[];
  delegations: Delegation[];
  conversationId: string | null;
  workspaceId: string | null;
  voiceSessionId: string | null;
  pendingImages: { assetId: string; index: number | null }[];
  usageSeconds: number | null;
  transport: 'webrtc' | 'fake' | null;
  locale: string;
}

export interface VoiceHost {
  api: AgentApi;
  workspaceId: string;
  conversationId: string | null;
  /** The call's language; left out, the server uses the person's saved style. */
  locale?: string;
  /** GPT-Live voice id; left out, the server uses the person's saved style. */
  voice?: string;
  timeZone?: string;
  model?: string;
  pageContext: () => SiteAgentPageContext;
  onConversation: (conversationId: string) => void;
  onAnswer: (response: AgentTurnResponse) => void;
}

const IDLE: VoiceSnapshot = {
  state: 'idle', error: null, micMuted: false, outputMuted: false, endingAfterReply: false, speaker: null, level: 0, transcript: [], delegations: [],
  conversationId: null, workspaceId: null, voiceSessionId: null, pendingImages: [], usageSeconds: null, transport: null, locale: 'auto'
};
const SETTLE_MS = 650;
const SETTLE_MAX_MS = 3000;
// Live accepts at most 500 tokens per append: about 1800 characters of English, but Chinese, Japanese or Korean text is
// close to a token per character.
const MAX_COMMENTARY_CHARS = 1800;
const MAX_COMMENTARY_CJK_CHARS = 450;
const TRANSCRIPT_BATCH = 50; // the server takes at most 50 lines per request
const SPEAKING_HOLD_MS = 700; // "Rafii is speaking" holds through short pauses instead of flickering
const SPOKEN = /[\p{L}\p{N}]/u; // a delta with words in it (not just spaces or punctuation)

let snapshot: VoiceSnapshot = IDLE;
const listeners = new Set<() => void>();
let transport: LiveTransport | null = null;
let host: VoiceHost | null = null;
let opening: ReturnType<typeof voiceOpening> | null = null;
let unsubscribe: (() => void)[] = [];
let levelTimer: ReturnType<typeof setInterval> | null = null;
let lastInputAt = 0;
let lastLoudAt = 0;
let lastOutputAt = 0;
let nextSeq = 0;
let lastDelegatedSeq = 0;
let unsent: TranscriptLine[] = [];
let flushing: Promise<void> | null = null;
let lastFlushFailure = 0;
let closedEarly = false;
/** Set after a goodbye; the level timer ends the call when `hangUpDue` says so. */
let hangUp: HangUp | null = null;
/** The open user line (id and length) last checked for a goodbye, so each version of it is checked once. */
let farewellChecked = '';

function set(patch: Partial<VoiceSnapshot>) {
  snapshot = { ...snapshot, ...patch };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function newKey() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function newTraceId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return 'trace_' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function newLine() {
  return { id: newKey(), seq: ++nextSeq };
}

/** Apply one transcript event to the snapshot; false when Rafii's words were dropped (a stopped reply still streaming). */
function applyLine(event: TranscriptEvent, patch: Partial<VoiceSnapshot> = {}): boolean {
  const step = applyTranscript({ lines: snapshot.transcript, stopped: snapshot.outputMuted }, event, newLine);
  if (step.dropped) return false;
  if (step.resumed) transport?.setOutputMuted(false);
  set({ ...patch, transcript: step.state.lines, outputMuted: step.state.stopped });
  for (const line of step.closed) {
    unsent.push(line);
    // Rafii has started answering the person's last words: if they were a goodbye, the call ends after this reply.
    if (line.role === 'user' && event.type === 'delta' && event.role === 'assistant' && isFarewell(line.text)) armHangUp();
  }
  return true;
}

function appendTranscript(role: 'user' | 'assistant', delta: string, startMs: number, endMs: number): boolean {
  const heard = applyLine({ type: 'delta', role, delta, startMs, endMs }, { speaker: role === 'user' ? 'user' : 'rafii' });
  // Stored as it goes (text only), so a long call or a closed tab keeps what was said and the backend sees it (with a
  // pause after a failed upload, so a failing endpoint isn't hit on every word).
  if (heard && unsent.length >= 20 && Date.now() - lastFlushFailure > 5000) void flushTranscript();
  return heard;
}

function commentaryLimit(content: string) {
  return /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]/.test(content) ? MAX_COMMENTARY_CJK_CHARS : MAX_COMMENTARY_CHARS;
}

function send(event: Record<string, unknown>) {
  transport?.send({ event_id: `evt_${newKey().slice(0, 12)}`, ...event });
}

/** Quiet context for GPT-Live (not spoken): progress, page changes, typed turns. */
function think(content: string, delegationId: string | null = null) {
  send({ type: 'session.thinking.append', delegation_id: delegationId, content: content.slice(0, commentaryLimit(content)) });
}

/** A result GPT-Live says aloud, paraphrased. A reply the person stopped stays stopped until this. */
function say(content: string, delegationId: string | null) {
  if (snapshot.outputMuted) applyLine({ type: 'resume' });
  send({ type: 'session.commentary.append', delegation_id: delegationId, content: content.slice(0, commentaryLimit(content)) });
}

/** The call ends once Rafii's reply to the goodbye has gone quiet (at most 10 s from now). */
function armHangUp() {
  if (snapshot.state !== 'live' && snapshot.state !== 'reconnecting') return;
  hangUp ??= { at: Date.now(), replied: false, lastSoundAt: 0 };
  if (!snapshot.endingAfterReply) set({ endingAfterReply: true });
}

function cancelHangUp() {
  hangUp = null;
  if (snapshot.endingAfterReply) set({ endingAfterReply: false });
}

/** Every level tick: a settled goodbye arms the hang-up (even if Rafii never answers it); a due hang-up ends the call. */
function watchFarewell(now: number) {
  if (snapshot.state !== 'live') return;
  if (hangUp) {
    if (hangUpDue(hangUp, now)) {
      hangUp = null;
      void voiceSession.end();
    }
    return;
  }
  const line = lastUserLine(snapshot.transcript);
  if (!line || line.final || now - lastInputAt < SETTLE_MS) return;
  const key = `${line.id}:${line.text.length}`;
  if (key === farewellChecked) return;
  farewellChecked = key;
  if (isFarewell(line.text)) armHangUp();
}

function userTextSinceLastDelegation(): string {
  const taken = takeRequest(snapshot.transcript, lastDelegatedSeq);
  lastDelegatedSeq = taken.lastSeq;
  if (taken.closed.length) {
    // Words said after this point start a new line, so they belong to the next request instead of this one.
    set({ transcript: taken.lines });
    unsent.push(...taken.closed);
  }
  return taken.request;
}

function updateDelegation(id: string, patch: Partial<Delegation>) {
  set({ delegations: snapshot.delegations.map((d) => (d.id === id ? { ...d, ...patch } : d)) });
}

/** GPT-Live is told how to talk from now on: fixed sentences picked by enum value, never the person's words. */
function applyLiveStyle(patch: AgentStylePatch) {
  const lines = styleInstructions(patch);
  if (lines.length) send({ type: 'session.instructions.append', delegation_id: null, content: lines.join(' ') });
  if (patch.language) set({ locale: patch.language });
}

/** Carry out a panel command here; true only when its handler exists and finished (a guide: said it started). */
async function carryOut(command: PanelCommand): Promise<boolean> {
  const actions = panelActions();
  try {
    switch (command.kind) {
      case 'end_call':
        armHangUp();
        return true;
      case 'mute':
        voiceSession.setMicMuted(true);
        return true;
      case 'stop_speaking':
        voiceSession.stopSpeaking();
        return true;
      case 'style': {
        const save = actions.setStyle;
        if (!save) return false;
        await save(command.patch);
        applyLiveStyle(command.patch);
        return true;
      }
      case 'open_style': {
        const open = actions.openStyle;
        if (!open) return false;
        open();
        return true;
      }
      case 'navigate': {
        const navigate = actions.navigate;
        if (!navigate) return false;
        navigate(command.href);
        return true;
      }
      case 'guide': {
        const start = actions.startGuide;
        return start ? (await start(command.guideId)) === true : false;
      }
    }
  } catch {
    return false;
  }
}

/** The local fast lane: true when the request was handled here (no agent turn), false to send it to the agent. */
async function runPanelCommand(id: string, request: string, command: PanelCommand): Promise<boolean> {
  updateDelegation(id, { request, status: 'running' });
  if (!(await carryOut(command))) {
    // Nothing is claimed: the panel couldn't do it on this screen, so the agent takes the request as before.
    say('I can’t do that from this screen, so I’m checking another way.', id);
    return false;
  }
  updateDelegation(id, { status: 'done', local: true, finishedAt: Date.now() });
  const spoken = confirmation(command);
  if (spoken) say(spoken, id);
  // "Stop talking" is confirmed by silence; GPT-Live still learns the request is done.
  else think('Done: the user asked Rafii to stop talking. Stay quiet until the user speaks again.', id);
  return true;
}

/** `voice_command` blocks from the agent's answer (Contract 2); true when the answer must not be said aloud. */
async function runVoiceCommands(commands: VoiceCommand[]): Promise<boolean> {
  let quiet = false;
  for (const item of commands) {
    if (item.command === 'style') {
      try {
        await panelActions().setStyle?.(item.style);
      } catch {
        /* the agent already saved it; this only refreshes the panel's copy */
      }
      applyLiveStyle(item.style);
    } else if (item.command === 'mute') {
      voiceSession.setMicMuted(true);
    } else if (item.command === 'stop_speaking') {
      voiceSession.stopSpeaking();
      quiet = true;
    } else if (quiet) {
      void voiceSession.end(); // quiet and goodbye: nothing more will be said
    } else {
      armHangUp();
    }
  }
  return quiet;
}

async function onDelegation(id: string) {
  const current = host;
  if (!current || !transport || snapshot.delegations.some((d) => d.id === id)) return;
  const pending: Delegation = { id, request: '', status: 'collecting', startedAt: Date.now() };
  set({ delegations: [...snapshot.delegations, pending].slice(-12) });
  // The delegation notice can arrive before the sentence is fully transcribed: wait for the words to settle.
  const started = Date.now();
  await new Promise<void>((resolve) => {
    const tick = () => (Date.now() - lastInputAt >= SETTLE_MS || Date.now() - started >= SETTLE_MAX_MS ? resolve() : setTimeout(tick, 100));
    tick();
  });
  const request = userTextSinceLastDelegation();
  if (!request) {
    if (snapshot.delegations.some((d) => d.id !== id && (d.status === 'running' || d.status === 'collecting'))) {
      // Two delegations for one request: the other one already has the words.
      updateDelegation(id, { status: 'cancelled', error: 'Same request as the one already running.' });
      say('I’m already working on that.', id);
      return;
    }
    updateDelegation(id, { status: 'failed', error: 'Nothing was heard to act on.' });
    say('I didn’t catch a request there. Could you say it again?', id);
    return;
  }
  // Panel commands never wait for a model turn.
  const command = matchPanelCommand(request);
  if (command && (await runPanelCommand(id, request, command))) return;
  updateDelegation(id, { request, status: 'running' });
  think(`Working on: ${request}. No result yet — don't state one.`, id);
  const images = snapshot.pendingImages;
  set({ pendingImages: [] });
  // The request belongs to the conversation it was sent in, even if the panel moves on while it runs.
  const sentIn = snapshot.conversationId;
  const progress = startProgress(id, sentIn);
  await flushTranscript(); // the backend reads what was just said (recentVoiceTranscript)
  const page = current.pageContext();
  // This session carries out `voice_command` blocks, so the agent may answer with them.
  const pageContext: SiteAgentPageContext = { ...page, uiCapabilities: [...new Set([...(page.uiCapabilities ?? []), 'voice'])] };
  try {
    const response = await current.api.turn(current.workspaceId, {
      // One key per delegation: a repeated event or a retried request is the same turn on the server.
      message: request, idempotencyKey: `voice:${snapshot.voiceSessionId ?? 'none'}:${id}`.slice(0, 100), conversationId: sentIn, modality: 'voice', pageContext,
      attachments: images.map((image) => ({ assetId: image.assetId })), timeZone: current.timeZone, locale: snapshot.locale, model: current.model,
      traceId: newTraceId(), delegationId: id, voiceSessionId: snapshot.voiceSessionId ?? undefined
    });
    progress.stop();
    // A request sent without a conversation started one: adopt it, unless the call has moved to another since.
    if (!sentIn && response.conversationId && snapshot.conversationId === null) {
      set({ conversationId: response.conversationId });
      current.onConversation(response.conversationId);
    }
    current.onAnswer(response);
    const result = response.result;
    updateDelegation(id, { status: 'done', runId: response.runId, result, finishedAt: Date.now() });
    if (snapshot.error && snapshot.error.code !== 'connection_lost') set({ error: null }); // the service is answering again
    // Only what the server returned is said; with no spoken summary, nothing is claimed beyond "it's in the panel".
    const spoken = result?.speakableSummary?.trim() || (result?.errors?.length ? 'That didn’t fully work. The details are in the panel.' : 'I’ve put the answer in the panel.');
    // Commands in the answer run only while this call is still the one that asked.
    const quiet = host === current && transport ? await runVoiceCommands(voiceCommandsIn(response)) : false;
    if (quiet) think(`The user asked for quiet, so this result is not said aloud: ${spoken}`, id);
    else say(spoken, id);
  } catch (error) {
    progress.stop();
    const message = error instanceof Error ? error.message : 'The request failed.';
    updateDelegation(id, { status: 'failed', error: message, finishedAt: Date.now() });
    // Never let a failure sound like success (spec §37), and never claim "nothing changed" unless the server refused the
    // request before doing anything (a dropped connection may come after the server applied it).
    const refused = error instanceof ApiError && [400, 401, 402, 403, 404, 409, 413, 415, 422, 429].includes(error.status);
    say(refused ? `That didn't go through: ${message} Nothing was changed by that request.` : `I couldn't confirm whether that went through (${message}). Check the panel before asking again.`, id);
  }
}

/** While a delegated request runs, pass real step progress to GPT-Live quietly (it can answer "how's it going?"). */
function startProgress(delegationId: string, conversationId: string | null) {
  let stopped = false;
  let seen = '';
  let timer: ReturnType<typeof setTimeout> | null = null;
  const poll = async () => {
    const current = host;
    if (stopped || !current || !conversationId) return;
    try {
      const state = await current.api.conversationState(current.workspaceId, conversationId);
      const line = (state.task?.steps ?? []).map((s) => `${s.label}: ${s.state.replace('_', ' ')}`).join('; ');
      if (!stopped && line && line !== seen) {
        seen = line;
        think(`Progress so far (not final): ${line}`, delegationId);
      }
    } catch {
      /* progress is best effort; the result is what counts */
    }
    if (!stopped) timer = setTimeout(() => void poll(), 1500);
  };
  timer = setTimeout(() => void poll(), 1500);
  return {
    stop: () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    }
  };
}

function onLiveEvent(event: LiveEvent) {
  switch (event.type) {
    case 'session.started':
      set({ state: 'live', error: null });
      opening?.started();
      break;
    case 'session.input_transcript.delta': {
      const delta = String(event.delta ?? '');
      if (SPOKEN.test(delta)) opening?.cancel();
      lastInputAt = Date.now();
      // Speaking again after a goodbye keeps the call on.
      if (hangUp && SPOKEN.test(delta)) cancelHangUp();
      appendTranscript('user', delta, Number(event.start_ms ?? 0), Number(event.end_ms ?? 0));
      break;
    }
    case 'session.output_transcript.delta':
      if (appendTranscript('assistant', String(event.delta ?? ''), Number(event.start_ms ?? 0), Number(event.end_ms ?? 0))) {
        lastOutputAt = Date.now();
        if (hangUp) {
          hangUp.replied = true;
          hangUp.lastSoundAt = lastOutputAt;
        }
      }
      break;
    case 'session.delegation.created': {
      const delegation = event.delegation as { id?: string } | undefined;
      if (delegation?.id) void onDelegation(delegation.id);
      break;
    }
    case 'session.usage.updated':
      set({ usageSeconds: Number((event.usage as { seconds?: number })?.seconds ?? snapshot.usageSeconds ?? 0) });
      break;
    case 'session.closed': {
      const usage = Number((event.usage as { seconds?: number })?.seconds ?? snapshot.usageSeconds ?? NaN);
      closedEarly = snapshot.state !== 'ending';
      void finish(String(event.reason ?? 'remote_hangup'), Number.isFinite(usage) ? usage : null);
      break;
    }
    case 'error': {
      const error = event.error as { message?: string; code?: string } | undefined;
      set({ error: { code: error?.code ?? 'live_error', message: error?.message ?? 'The voice service reported a problem.' } });
      break;
    }
    default:
      break;
  }
}

/** Upload lines to one voice session in batches of at most TRANSCRIPT_BATCH (the server's limit); what fails is returned. */
async function sendLines(api: AgentApi, workspaceId: string, sessionId: string, lines: TranscriptLine[]): Promise<TranscriptLine[]> {
  for (let index = 0; index < lines.length; index += TRANSCRIPT_BATCH) {
    const batch = lines.slice(index, index + TRANSCRIPT_BATCH);
    try {
      await api.voiceTranscript(workspaceId, sessionId, batch.map((l) => ({ role: l.role, text: l.text, startMs: Math.round(l.startMs) })));
    } catch {
      lastFlushFailure = Date.now();
      return lines.slice(index);
    }
  }
  return [];
}

async function flushTranscript(includeOpen = false) {
  // One flush at a time: wait for any running one (and any that started meanwhile) before taking lines.
  for (let running = flushing; running; running = flushing) await running;
  const current = host;
  const sessionId = snapshot.voiceSessionId;
  const lines = unsent.splice(0);
  const last = snapshot.transcript.at(-1);
  if (includeOpen && last && !last.final && !lines.some((line) => line.id === last.id)) lines.push({ ...last, final: true });
  if (!current || !sessionId || !lines.length) {
    unsent.unshift(...lines);
    return;
  }
  const mine = (async () => {
    const failed = await sendLines(current.api, current.workspaceId, sessionId, lines);
    if (failed.length && snapshot.voiceSessionId === sessionId) unsent.unshift(...failed);
  })();
  flushing = mine;
  try {
    await mine;
  } finally {
    if (flushing === mine) flushing = null;
  }
}

async function finish(reason: string, usageSeconds: number | null) {
  opening?.cancel();
  const current = host;
  const sessionId = snapshot.voiceSessionId;
  if (levelTimer) clearInterval(levelTimer);
  levelTimer = null;
  hangUp = null;
  await flushTranscript(true);
  for (const off of unsubscribe.splice(0)) off();
  transport?.close();
  transport = null;
  if (current && sessionId) {
    try {
      await current.api.voiceEnd(current.workspaceId, sessionId, { usageSeconds, reason });
    } catch {
      /* the server holds the usage as unknown until reconciled */
    }
  }
  const unexpected = closedEarly && reason !== 'close_requested';
  set({
    state: unexpected ? 'error' : 'ended', speaker: null, level: 0, voiceSessionId: null, transport: null, outputMuted: false, endingAfterReply: false,
    error: unexpected ? { code: reason, message: reason === 'expired' ? 'The voice session reached its time limit.' : 'Voice Mode stopped. You can keep typing, or start it again.' } : null
  });
  closedEarly = false;
}

export const voiceSession = {
  get: () => snapshot,
  subscribe,

  /** Start Voice Mode in this conversation (a user gesture must call this: browsers require it for the microphone). */
  async start(next: VoiceHost, resuming = false) {
    if (snapshot.state === 'connecting' || snapshot.state === 'live') return;
    host = next;
    lastDelegatedSeq = nextSeq;
    unsent = [];
    hangUp = null;
    farewellChecked = '';
    lastOutputAt = 0;
    lastLoudAt = 0;
    if (levelTimer) clearInterval(levelTimer);
    levelTimer = null;
    set({ ...IDLE, state: 'connecting', workspaceId: next.workspaceId, conversationId: next.conversationId, locale: next.locale ?? 'auto' });
    const live = createTransport();
    transport = live;
    opening = voiceOpening(send, resuming);
    unsubscribe = [
      live.onEvent(onLiveEvent),
      live.onState((state) => {
        if ((state === 'disconnected' || state === 'failed') && snapshot.state === 'live') {
          set({ state: 'reconnecting', error: { code: 'connection_lost', message: 'The voice connection dropped. Reconnect, or keep typing.' } });
        } else if (state === 'connected' && snapshot.state === 'reconnecting') {
          // A brief network drop that WebRTC recovered by itself: the call is live again.
          set({ state: 'live', error: null });
        }
      })
    ];
    try {
      await live.connect(async (sdp) => {
        if (transport !== live) throw new VoiceTransportError('negotiation_failed', 'Voice Mode was ended.');
        const started = await next.api.voiceStart(next.workspaceId, { sdp, conversationId: next.conversationId, locale: next.locale, voice: next.voice });
        if (transport !== live) {
          // Ended while the session was being created: end that session too, so it is neither left open nor billed to the cap.
          void next.api.voiceEnd(next.workspaceId, started.voiceSessionId, { reason: 'user_ended', usageSeconds: 0 }).catch(() => undefined);
          throw new VoiceTransportError('negotiation_failed', 'Voice Mode was ended.');
        }
        opening?.prepared(started.openingGreeting);
        // The server settles the call's language (the person's style when none was picked); requests use the same one.
        set({ voiceSessionId: started.voiceSessionId, conversationId: started.conversationId, locale: started.locale || snapshot.locale });
        if (started.conversationId !== next.conversationId) next.onConversation(started.conversationId);
        return started.sdp;
      });
      if (transport !== live) {
        // Ended (or signed out) while connecting: this connection is not the call any more.
        live.close();
        return;
      }
      set({ transport: live.kind });
      levelTimer = setInterval(() => {
        const level = transport?.outputLevel() ?? 0;
        const now = Date.now();
        if (level > 0.04) {
          lastLoudAt = now;
          if (hangUp) hangUp.lastSoundAt = now;
        }
        const speaker: Speaker = now - lastLoudAt < SPEAKING_HOLD_MS ? 'rafii' : now - lastInputAt < 900 ? 'user' : null;
        if (Math.abs(level - snapshot.level) > 0.02 || speaker !== snapshot.speaker) set({ level, speaker });
        watchFarewell(now);
      }, 120);
    } catch (error) {
      const abandoned = transport !== live;
      live.close();
      if (abandoned) return; // ended on purpose while connecting: not an error (finish already reset the state)
      for (const off of unsubscribe.splice(0)) off();
      transport = null;
      const code = error instanceof VoiceTransportError ? error.code : ((error as { code?: string })?.code ?? 'voice_failed');
      const message = error instanceof Error ? error.message : 'Voice Mode could not start. You can keep typing.';
      if (snapshot.voiceSessionId) void next.api.voiceEnd(next.workspaceId, snapshot.voiceSessionId, { reason: 'error' }).catch(() => undefined);
      set({ state: 'error', error: { code, message }, voiceSessionId: null });
    }
  },

  async end() {
    opening?.cancel();
    hangUp = null;
    if (!transport || snapshot.state === 'ending') {
      if (snapshot.state !== 'idle') set({ state: 'ended' });
      return;
    }
    if (!transport.connected() || snapshot.state === 'reconnecting') {
      // Nothing can hear a close request (still connecting, or the connection dropped): finish now, locally and on the server.
      closedEarly = false;
      await finish('close_requested', snapshot.usageSeconds);
      return;
    }
    set({ state: 'ending' });
    send({ type: 'session.close' });
    // Wait for session.closed (it carries the usage); don't wait forever.
    const deadline = Date.now() + 15_000;
    const ending = () => voiceSession.get().state === 'ending';
    while (ending() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 100));
    if (ending()) await finish('close_requested', snapshot.usageSeconds);
  },

  async reconnect() {
    const previous = host;
    if (!previous) return;
    if (levelTimer) clearInterval(levelTimer);
    levelTimer = null;
    // The old session's words are stored in the background: nothing is awaited before the new connection, so its audio is
    // still set up inside the person's click (WebKit requires that).
    const oldSession = snapshot.voiceSessionId;
    const last = snapshot.transcript.at(-1);
    const oldLines = [...unsent.splice(0), ...(last && !last.final ? [{ ...last, final: true }] : [])];
    if (oldSession && oldLines.length) void sendLines(previous.api, previous.workspaceId, oldSession, oldLines);
    if (transport) {
      for (const off of unsubscribe.splice(0)) off();
      transport.close();
      transport = null;
    }
    if (snapshot.voiceSessionId) void previous.api.voiceEnd(previous.workspaceId, snapshot.voiceSessionId, { reason: 'connection_lost', usageSeconds: snapshot.usageSeconds }).catch(() => undefined);
    set({ state: 'idle', voiceSessionId: null });
    // A new Live session in the same conversation (and language): the server gives it the conversation so far;
    // approvals live on the server.
    await voiceSession.start({ ...previous, conversationId: snapshot.conversationId, locale: snapshot.locale }, true);
  },

  setMicMuted(muted: boolean) {
    transport?.setMicEnabled(!muted);
    set({ micMuted: muted });
  },

  /**
   * Stop Rafii talking for good: GPT-Live can't cancel a reply, so its audio stays muted and the rest of its words are
   * dropped until the person speaks again or a new result is being said. The cut-off line is marked stopped.
   */
  stopSpeaking() {
    if (!transport) return;
    const now = Date.now();
    const inFlight = snapshot.speaker === 'rafii' || now - lastLoudAt < SPEAKING_HOLD_MS || now - lastOutputAt < UTTERANCE_GAP_MS;
    transport.setOutputMuted(true);
    send({ type: 'session.instructions.append', delegation_id: null, content: 'Stop speaking now and listen to the user.' });
    lastLoudAt = 0;
    applyLine({ type: 'stop', inFlight }, { speaker: null, level: 0 });
  },

  /** The person moved to another page with the call on: GPT-Live hears about it quietly. */
  pageChanged(title: string | null) {
    if (snapshot.state === 'live' && title) think(`The user is now looking at the ${title} page in Rafii.`);
  },

  /** A typed message during the call: the text turn already ran; GPT-Live gets it as context so the voice stays in step. */
  typedExchange(question: string, answer: AgentResult | null) {
    if (snapshot.state !== 'live') return;
    think(`The user typed: "${question.slice(0, 400)}". Rafii answered in the panel: ${(answer?.speakableSummary || answer?.answerText || '').slice(0, 800)}`);
  },

  /** An image added during the call belongs to the next request; GPT-Live can't see it, the backend can. */
  imageAttached(assetId: string, index: number | null) {
    set({ pendingImages: [...snapshot.pendingImages, { assetId, index }].slice(-4) });
    if (snapshot.state === 'live') think(`The user attached image ${index ?? ''} to the conversation. You cannot see images; delegate the request so Rafii can look at it.`);
  },

  setConversation(conversationId: string | null) {
    set({ conversationId });
  },

  /** The panel moved to another conversation (or started a new one) during the call: new requests go there. */
  followConversation(conversationId: string | null) {
    if (conversationId === snapshot.conversationId) return;
    set({ conversationId, pendingImages: [] });
    if (snapshot.state === 'live') {
      think(conversationId ? 'The user switched the panel to another conversation. Treat new requests as part of that conversation.'
        : 'The user started a new conversation in the panel. Earlier requests are finished; treat what they ask next as a fresh start.');
    }
  },

  reset() {
    if (transport) return;
    set(IDLE);
  }
};

export function useVoice<T>(selector: (s: VoiceSnapshot) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(snapshot),
    () => selector(IDLE)
  );
}
