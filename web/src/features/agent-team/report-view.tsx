'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import PageContainer from '@/components/layout/page-container';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';

type ReportKind = 'half_day' | 'whole_day';
type Selection = { workday: string; kind: ReportKind; version: number };
type Coverage = { source: string; status: string; count: number; complete: boolean; gaps: string[]; freshAt: string | null };
type Evidence = { id: string; source: string; capturedAt: string; observedAt: string; url: string | null };
type Report = {
  version: number;
  fingerprint: string;
  summary: string;
  asOf: string;
  generatedAt: string;
  period: { workday: string; kind: ReportKind; key: string; start: string; cutoff: string; timezone: string };
  counts: { completed: number; autonomouslyResolved: number; running: number | null; needsHuman: number | null };
  coverage: Coverage[];
  gaps: string[];
  evidence: Evidence[];
};
type LoadState =
  | { key: string; state: 'loading' }
  | { key: string; state: 'error'; message: string }
  | { key: string; state: 'ready'; report: Report; imageUrl: string };
type PcmWav = { channels: number; sampleRate: number; bitsPerSample: number; frames: number; durationSeconds: number; byteCount: number };
type VerifiedAudio = { bytes: ArrayBuffer; sha256: string; narrationSha256: string; pcm: PcmWav };
type AudioState =
  | { key: string; state: 'loading' }
  | { key: string; state: 'error'; message: string }
  | { key: string; state: 'ready'; url: string; captionsUrl: string; transcript: string; sha256: string; pcm: PcmWav };
type AudioRequest = { key: string; abort: AbortController; timeout: ReturnType<typeof setTimeout> | null; url: string | null; captionsUrl: string | null };

const TIMEZONE = 'America/Indiana/Indianapolis';
const ORIGINAL_SOURCES = ['luci', 'typeless', 'codex', 'claude', 'browser', 'mission', 'token_pilot'];
const SOURCES = [...ORIGINAL_SOURCES, 'git'];
const VERSION_HEADER = 'X-Agent-Team-Report-Version';
const FINGERPRINT_HEADER = 'X-Agent-Team-Report-Fingerprint';
const INVALID_REPORT = '報告資料與指定日期或版本不符，暫時無法顯示。';
const AUDIO_SHA_HEADER = 'X-Agent-Team-Audio-Sha256';
const NARRATION_SHA_HEADER = 'X-Agent-Team-Audio-Narration-Sha256';
export const MAX_REPORT_AUDIO_BYTES = 2 * 1024 * 1024;
const INVALID_AUDIO = '音訊檔的版本、指紋或格式未能核對，暫時無法播放。';

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function text(value: unknown, max = 500): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= max;
}
function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 1024 && value.every((item) => text(item, 1000));
}
function timestamp(value: unknown): value is string {
  return text(value, 80) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}
function localBoundary(value: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: TIMEZONE, calendar: 'iso8601', numberingSystem: 'latn', hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).formatToParts(new Date(value));
  const part = (name: string) => parts.find((item) => item.type === name)?.value ?? '';
  return `${part('year').padStart(4, '0')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}:${part('second')}`;
}

// URLs from source observations never carry credentials, queries or local endpoints.
export function safeEvidenceUrl(value: unknown): string | null {
  if (!text(value, 2000)) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (
      url.protocol !== 'https:' || url.username || url.password || url.search || url.hash ||
      (url.port && url.port !== '443') || !host.includes('.') || host.includes(':') ||
      /^[\d.]+$/.test(host) || host === 'localhost' ||
      /\.(?:localhost|local|internal|lan|home|corp|test|invalid)$/.test(host)
    ) return null;
    return url.href;
  } catch { return null; }
}

export function parseAgentTeamReport(value: unknown, selection: Selection): Report {
  const invalid = () => { throw new Error(INVALID_REPORT); };
  const dayStart = new Date(`${selection.workday}T00:00:00Z`);
  if (
    !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(selection.workday) || !Number.isFinite(dayStart.getTime()) ||
    dayStart.toISOString().slice(0, 10) !== selection.workday ||
    !['half_day', 'whole_day'].includes(selection.kind) || !count(selection.version) || selection.version < 1 || selection.version > 9999
  ) return invalid();
  if (!object(value) || value.schemaVersion !== 1 || value.executionState !== 'generated') return invalid();
  const { period, counts, coverage, gaps, evidence } = value;
  if (
    value.version !== selection.version || !text(value.fingerprint, 64) || !/^[a-f0-9]{64}$/.test(value.fingerprint) ||
    !text(value.summary, 12000) || !value.summary.trim() || !timestamp(value.asOf) || !timestamp(value.generatedAt) ||
    !object(period) || period.workday !== selection.workday || period.kind !== selection.kind ||
    period.key !== `agent-team:v1:${selection.workday}:${selection.kind}` || period.timezone !== TIMEZONE ||
    !timestamp(period.start) || !timestamp(period.cutoff) || Date.parse(period.start) >= Date.parse(period.cutoff) ||
    Date.parse(value.asOf) > Date.parse(period.cutoff) || Date.parse(value.asOf) < Date.parse(period.start) ||
    Date.parse(value.generatedAt) < Date.parse(value.asOf) || !object(counts) ||
    !count(counts.completed) || !count(counts.autonomouslyResolved) ||
    !(counts.running === null || count(counts.running)) || !(counts.needsHuman === null || count(counts.needsHuman)) ||
    !Array.isArray(coverage) || ![ORIGINAL_SOURCES.length, SOURCES.length].includes(coverage.length) || !strings(gaps) ||
    !Array.isArray(evidence) || evidence.length > 10000
  ) return invalid();
  const nextDay = new Date(dayStart.getTime());
  nextDay.setUTCDate(nextDay.getUTCDate() + 1);
  const cutoffDay = selection.kind === 'whole_day' ? nextDay.toISOString().slice(0, 10) : selection.workday;
  if (
    localBoundary(period.start) !== `${selection.workday} 01:00:00` ||
    localBoundary(period.cutoff) !== `${cutoffDay} ${selection.kind === 'whole_day' ? '01' : '17'}:00:00`
  ) return invalid();
  const seen = new Set<string>();
  const parsedCoverage: Coverage[] = coverage.map((row: unknown) => {
    if (
      !object(row) || !text(row.source, 80) || !SOURCES.includes(row.source) || seen.has(row.source) ||
      !text(row.status, 80) || !count(row.count) || typeof row.complete !== 'boolean' || !strings(row.gaps) ||
      !(row.freshAt === null || timestamp(row.freshAt)) || (row.complete && (row.status !== 'ok' || row.gaps.length > 0 || row.freshAt === null))
    ) return invalid();
    seen.add(row.source);
    return { source: row.source, status: row.status, count: row.count, complete: row.complete, gaps: row.gaps, freshAt: row.freshAt };
  });
  // Immutable earlier versions keep their original seven-source projection.
  // New versions add Git/CI; another source cannot replace a required one.
  if (!ORIGINAL_SOURCES.every((source) => seen.has(source))) return invalid();
  const parsedEvidence: Evidence[] = evidence.map((row: unknown) => {
    if (!object(row) || !text(row.id, 64) || !/^[a-f0-9]{64}$/.test(row.id) || !text(row.source, 80) || !timestamp(row.capturedAt) || !timestamp(row.observedAt)) return invalid();
    return { id: row.id, source: row.source, capturedAt: row.capturedAt, observedAt: row.observedAt, url: safeEvidenceUrl(row.url) };
  });
  return {
    version: selection.version, fingerprint: value.fingerprint, summary: value.summary, asOf: value.asOf, generatedAt: value.generatedAt,
    period: { workday: selection.workday, kind: selection.kind, key: period.key as string, start: period.start, cutoff: period.cutoff, timezone: TIMEZONE },
    counts: { completed: counts.completed, autonomouslyResolved: counts.autonomouslyResolved, running: counts.running, needsHuman: counts.needsHuman },
    coverage: parsedCoverage, gaps, evidence: parsedEvidence
  };
}

function responseIdentity(response: Response, version: number, fingerprint?: string): void {
  const cache = response.headers.get('Cache-Control') ?? '';
  if (
    !/(?:^|,)\s*private\s*(?:,|$)/i.test(cache) || !/(?:^|,)\s*no-store\s*(?:,|$)/i.test(cache) ||
    response.headers.get(VERSION_HEADER) !== String(version) ||
    !/^[a-f0-9]{64}$/.test(response.headers.get(FINGERPRINT_HEADER) ?? '') ||
    (fingerprint !== undefined && response.headers.get(FINGERPRINT_HEADER) !== fingerprint)
  ) throw new Error(INVALID_REPORT);
}

// Matches the service's bounded Sinji PCM contract; never invokes a decoder.
export function parseAgentTeamPcmWav(raw: ArrayBuffer): PcmWav {
  const invalid = () => { throw new Error(INVALID_AUDIO); };
  if (!(raw instanceof ArrayBuffer) || raw.byteLength < 44 || raw.byteLength > MAX_REPORT_AUDIO_BYTES) return invalid();
  const bytes = new Uint8Array(raw);
  const view = new DataView(raw);
  const fourcc = (offset: number) => String.fromCharCode(...bytes.subarray(offset, offset + 4));
  if (fourcc(0) !== 'RIFF' || fourcc(8) !== 'WAVE' || view.getUint32(4, true) + 8 !== raw.byteLength) return invalid();
  let position = 12;
  let chunks = 0;
  let format: number[] | null = null;
  let samples: Uint8Array | null = null;
  while (position < raw.byteLength) {
    if (++chunks > 32 || position + 8 > raw.byteLength) return invalid();
    const name = fourcc(position);
    const length = view.getUint32(position + 4, true);
    position += 8;
    const end = position + length;
    if (end > raw.byteLength) return invalid();
    if (name === 'fmt ') {
      if (format || (length !== 16 && length !== 18)) return invalid();
      format = [view.getUint16(position, true), view.getUint16(position + 2, true), view.getUint32(position + 4, true), view.getUint32(position + 8, true), view.getUint16(position + 12, true), view.getUint16(position + 14, true)];
      if (length === 18 && view.getUint16(position + 16, true) !== 0) return invalid();
    } else if (name === 'data') {
      if (samples) return invalid();
      samples = bytes.subarray(position, end);
    } else if (!['JUNK', 'LIST', 'FLLR', 'fact'].includes(name)) return invalid();
    position = end + (length % 2);
    if (position > raw.byteLength) return invalid();
  }
  const expected = [1, 1, 16000, 32000, 2, 16];
  if (!format || format.some((value, index) => value !== expected[index]) || !samples || samples.byteLength === 0 || samples.byteLength % 2 !== 0 || !samples.some((value) => value !== 0)) return invalid();
  const frames = samples.byteLength / 2;
  const durationSeconds = frames / 16000;
  if (!(durationSeconds > 0 && durationSeconds <= 45)) return invalid();
  return { channels: 1, sampleRate: 16000, bitsPerSample: 16, frames, durationSeconds, byteCount: raw.byteLength };
}

async function boundedAudioBytes(response: Response, signal: AbortSignal): Promise<ArrayBuffer> {
  const length = response.headers.get('Content-Length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) < 44 || Number(length) > MAX_REPORT_AUDIO_BYTES)) throw new Error(INVALID_AUDIO);
  if (!response.body) throw new Error(INVALID_AUDIO);
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let received = 0;
  try {
    while (true) {
      if (signal.aborted) throw new DOMException('Audio request aborted', 'AbortError');
      const part = await reader.read();
      if (part.done) break;
      received += part.value.byteLength;
      if (received > MAX_REPORT_AUDIO_BYTES) throw new Error('音訊檔超出 2 MiB 上限，暫時無法播放。');
      parts.push(part.value);
    }
    if (length !== null && received !== Number(length)) throw new Error(INVALID_AUDIO);
    const raw = new ArrayBuffer(received);
    const bytes = new Uint8Array(raw);
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    return raw;
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

// Called by the explicit audio button only. Dependency injection permits cloud fixtures.
export async function fetchAgentTeamAudio(selection: Selection, fingerprint: string, getToken: () => Promise<string | null>, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<VerifiedAudio> {
  const day = new Date(`${selection.workday}T00:00:00Z`);
  if (selection.kind !== 'whole_day' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(selection.workday) || !Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== selection.workday || !Number.isSafeInteger(selection.version) || selection.version < 1 || selection.version > 9999 || !/^[a-f0-9]{64}$/.test(fingerprint)) throw new Error(INVALID_AUDIO);
  const token = await getToken();
  if (signal.aborted) throw new DOMException('Audio request aborted', 'AbortError');
  if (!token) throw new Error('登入已失效，請重新登入後取得音訊檔。');
  let response: Response | null = null;
  try {
    response = await fetcher(`/api/internal/james-agent-team/reports/${selection.workday}/whole_day/wav?version=${selection.version}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'audio/wav' }, signal,
      cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer'
    });
    if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? '目前登入的帳戶無法取得這份音訊檔。' : response.status === 404 ? '本版音訊檔尚未提供。' : '音訊服務暫時無法使用，請稍後重試。');
    try { responseIdentity(response, selection.version, fingerprint); } catch { throw new Error(INVALID_AUDIO); }
    const sha256 = response.headers.get(AUDIO_SHA_HEADER) ?? '';
    const narrationSha256 = response.headers.get(NARRATION_SHA_HEADER) ?? '';
    if (!/^[a-f0-9]{64}$/.test(sha256) || !/^[a-f0-9]{64}$/.test(narrationSha256) || !/^audio\/wav(?:\s*;|$)/i.test(response.headers.get('Content-Type') ?? '')) throw new Error(INVALID_AUDIO);
    const bytes = await boundedAudioBytes(response, signal);
    const pcm = parseAgentTeamPcmWav(bytes);
    if (!globalThis.crypto?.subtle) throw new Error('這部裝置無法核對音訊檔雜湊，暫時無法播放。');
    const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
    const actualHash = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
    if (actualHash !== sha256) throw new Error('音訊檔 SHA-256 與服務記錄不符，暫時無法播放。');
    if (signal.aborted) throw new DOMException('Audio request aborted', 'AbortError');
    return { bytes, sha256, narrationSha256, pcm };
  } catch (error) {
    await response?.body?.cancel().catch(() => undefined);
    throw error;
  }
}

// Mirrors agent_team/audio.py _narration's 64 Unicode-code-point excerpt.
// Its hash must match this exact stored asset before we expose a transcript.
export async function verifiedAgentTeamAudioCaptions(summary: string, durationSeconds: number, narrationSha256: string): Promise<{ transcript: string; vtt: string }> {
  const characters = Array.from(summary);
  const hasControl = characters.some((character) => (character.codePointAt(0) ?? 0) < 32 || character.codePointAt(0) === 127);
  if (!characters.length || characters.length > 800 || hasControl || !Number.isFinite(durationSeconds) || durationSeconds <= 0 || durationSeconds > 45 || !/^[a-f0-9]{64}$/.test(narrationSha256) || !globalThis.crypto?.subtle) throw new Error(INVALID_AUDIO);
  let transcript = summary;
  if (characters.length > 64) {
    const prefix = characters.slice(0, 64);
    let lastStop = -1;
    for (let index = 0; index < prefix.length; index++) if (/[。！？.!?]/.test(prefix[index])) lastStop = index;
    transcript = lastStop >= 0 ? prefix.slice(0, lastStop + 1).join('') : prefix.slice(0, 63).join('') + '…';
  }
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(transcript)));
  const actualHash = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actualHash !== narrationSha256) throw new Error('音訊逐字稿與服務記錄不符，暫時無法播放。');
  const endMilliseconds = Math.ceil(durationSeconds * 1000);
  const end = `00:00:${String(Math.floor(endMilliseconds / 1000)).padStart(2, '0')}.${String(endMilliseconds % 1000).padStart(3, '0')}`;
  const cue = transcript.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // One cue spans the measured clip. No word-level timing is inferred.
  return { transcript, vtt: `WEBVTT\n\n00:00:00.000 --> ${end}\n${cue}\n` };
}

async function boundedText(response: Response, maxBytes: number): Promise<string> {
  if (!response.body) throw new Error('報告內容暫時無法讀取。');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let received = 0;
  let result = '';
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      received += part.value.byteLength;
      if (received > maxBytes) throw new Error('報告內容超出顯示範圍，請聯絡管理者核對。');
      result += decoder.decode(part.value, { stream: true });
    }
    return result + decoder.decode();
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function staticSvg(source: string): Blob {
  if (/<!DOCTYPE|<!ENTITY/i.test(source)) throw new Error('報告圖像格式無法核對。');
  const document = new DOMParser().parseFromString(source, 'image/svg+xml');
  const root = document.documentElement;
  const elements = [root, ...Array.from(root.querySelectorAll('*'))];
  const tags = new Set(['svg', 'g', 'rect', 'text', 'circle', 'path', 'line', 'polyline', 'polygon', 'ellipse']);
  const attributes = new Set(['xmlns', 'width', 'height', 'viewBox', 'x', 'y', 'rx', 'ry', 'cx', 'cy', 'r', 'fill', 'stroke', 'stroke-width', 'font-family', 'font-size', 'font-weight', 'text-anchor', 'opacity', 'transform', 'd', 'points', 'x1', 'x2', 'y1', 'y2']);
  if (root.localName !== 'svg' || root.namespaceURI !== 'http://www.w3.org/2000/svg' || document.querySelector('parsererror') || elements.length > 10000) throw new Error('報告圖像格式無法核對。');
  for (const element of elements) {
    if (!tags.has(element.localName) || element.namespaceURI !== root.namespaceURI) throw new Error('報告圖像包含不支援的內容。');
    for (const attribute of Array.from(element.attributes)) {
      if (!attributes.has(attribute.name) || (attribute.name !== 'xmlns' && /url\s*\(|javascript:|https?:|data:/i.test(attribute.value)) || attribute.value.length > 4000) throw new Error('報告圖像包含不支援的內容。');
    }
  }
  return new Blob([source], { type: 'image/svg+xml' });
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat('zh-Hant-HK', { timeZone: TIMEZONE, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export function AgentTeamReportView({ workday, kind, version }: Selection) {
  const { status, user, getToken } = useAuth();
  const [reload, setReload] = useState(0);
  const [load, setLoad] = useState<LoadState | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [evidencePage, setEvidencePage] = useState(0);
  const [speech, setSpeech] = useState<'unavailable' | 'idle' | 'starting' | 'playing' | 'error'>('unavailable');
  const [speechMessage, setSpeechMessage] = useState('');
  const [audio, setAudio] = useState<AudioState | null>(null);
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);
  const audioElement = useRef<HTMLAudioElement | null>(null);
  const audioRequest = useRef<AudioRequest | null>(null);
  const userId = user?.id ?? '';
  const key = `${userId}:${workday}:${kind}:${version}:${reload}`;
  const ready = status === 'signed-in' && load?.key === key && load.state === 'ready' ? load : null;
  const audioKey = `${status}:${key}:${ready?.report.fingerprint ?? ''}`;
  const currentAudioKey = useRef(audioKey);
  currentAudioKey.current = audioKey;
  const visibleAudio = audio?.key === audioKey ? audio : null;

  useEffect(() => {
    if (status !== 'signed-in' || !userId) return;
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 20000);
    let imageUrl: string | null = null;
    let disposed = false;
    setLoad({ key, state: 'loading' });
    setImageFailed(false);
    setEvidencePage(0);
    async function fetchReport() {
      try {
        const token = await getToken();
        if (disposed || abort.signal.aborted) return;
        if (!token) throw new Error('登入已失效，請重新登入後查看報告。');
        const headers = { Authorization: `Bearer ${token}` };
        const init: RequestInit = {
          signal: abort.signal, cache: 'no-store',
          credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer'
        };
        const base = `/api/internal/james-agent-team/reports/${workday}/${kind}`;
        const jsonResponse = await fetch(`${base}/json?version=${version}`, { ...init, headers: { ...headers, Accept: 'application/json' } });
        if (!jsonResponse.ok) throw new Error(jsonResponse.status === 401 || jsonResponse.status === 403 ? '目前登入的帳戶無法查看這份報告。' : jsonResponse.status === 404 ? '指定版本的報告尚未提供，請核對原本的報告連結。' : '報告服務暫時無法使用，請稍後重試。');
        responseIdentity(jsonResponse, version);
        if (!/^application\/json(?:\s*;|$)/i.test(jsonResponse.headers.get('Content-Type') ?? '')) throw new Error(INVALID_REPORT);
        const report = parseAgentTeamReport(JSON.parse(await boundedText(jsonResponse, 4 * 1024 * 1024)), { workday, kind, version });
        responseIdentity(jsonResponse, version, report.fingerprint);
        const svgResponse = await fetch(`${base}/svg?version=${version}`, { ...init, headers: { ...headers, Accept: 'image/svg+xml' } });
        if (!svgResponse.ok) throw new Error('指定版本的報告圖像暫時無法取得。');
        responseIdentity(svgResponse, version, report.fingerprint);
        if (!/^image\/svg\+xml(?:\s*;|$)/i.test(svgResponse.headers.get('Content-Type') ?? '')) throw new Error('報告圖像格式無法核對。');
        const blob = staticSvg(await boundedText(svgResponse, 1024 * 1024));
        if (disposed || abort.signal.aborted) return;
        imageUrl = URL.createObjectURL(blob);
        setLoad({ key, state: 'ready', report, imageUrl });
      } catch (error) {
        if (disposed) return;
        const message = abort.signal.aborted ? '報告讀取逾時，請重試。' : error instanceof Error && !(error instanceof SyntaxError) && !(error instanceof TypeError) ? error.message : '報告未能讀取或核對，請重試。';
        setLoad({ key, state: 'error', message });
      } finally { clearTimeout(timeout); }
    }
    void fetchReport();
    return () => { disposed = true; abort.abort(); clearTimeout(timeout); if (imageUrl) URL.revokeObjectURL(imageUrl); };
  }, [status, userId, getToken, key, workday, kind, version]);

  const releaseAudio = useCallback(() => {
    const request = audioRequest.current;
    audioRequest.current = null;
    if (audioElement.current) {
      audioElement.current.pause();
      audioElement.current.removeAttribute('src');
    }
    if (request) {
      request.abort.abort();
      if (request.timeout !== null) clearTimeout(request.timeout);
      if (request.url) URL.revokeObjectURL(request.url);
      if (request.captionsUrl) URL.revokeObjectURL(request.captionsUrl);
    }
  }, []);

  useEffect(() => {
    setAudio(null);
    return releaseAudio;
  }, [audioKey, releaseAudio]);

  async function loadAudio() {
    if (!ready || kind !== 'whole_day' || (audioRequest.current?.key === audioKey && audioRequest.current.timeout !== null)) return;
    releaseAudio();
    const request: AudioRequest = { key: audioKey, abort: new AbortController(), timeout: null, url: null, captionsUrl: null };
    audioRequest.current = request;
    setAudio({ key: audioKey, state: 'loading' });
    request.timeout = setTimeout(() => {
      request.timeout = null;
      request.abort.abort();
      if (audioRequest.current === request && currentAudioKey.current === request.key) setAudio({ key: request.key, state: 'error', message: '音訊檔讀取逾時，請重試。' });
    }, 20000);
    try {
      const ownedGetToken = async () => {
        const token = await getToken();
        if (audioRequest.current !== request || currentAudioKey.current !== request.key) request.abort.abort();
        return token;
      };
      const result = await fetchAgentTeamAudio({ workday, kind, version }, ready.report.fingerprint, ownedGetToken, request.abort.signal);
      if (audioRequest.current !== request || currentAudioKey.current !== request.key || request.abort.signal.aborted) return;
      const captions = await verifiedAgentTeamAudioCaptions(ready.report.summary, result.pcm.durationSeconds, result.narrationSha256);
      if (audioRequest.current !== request || currentAudioKey.current !== request.key || request.abort.signal.aborted) return;
      request.url = URL.createObjectURL(new Blob([result.bytes], { type: 'audio/wav' }));
      request.captionsUrl = URL.createObjectURL(new Blob([captions.vtt], { type: 'text/vtt' }));
      setAudio({ key: request.key, state: 'ready', url: request.url, captionsUrl: request.captionsUrl, transcript: captions.transcript, sha256: result.sha256, pcm: result.pcm });
    } catch (error) {
      if (audioRequest.current !== request || currentAudioKey.current !== request.key) return;
      const message = request.abort.signal.aborted ? '音訊檔讀取逾時，請重試。' : error instanceof Error && !(error instanceof TypeError) ? error.message : '音訊檔未能讀取或核對，請重試。';
      releaseAudio();
      setAudio({ key: request.key, state: 'error', message });
    } finally {
      if (request.timeout !== null) clearTimeout(request.timeout);
      request.timeout = null;
    }
  }

  function cancelAudio() {
    releaseAudio();
    setAudio({ key: audioKey, state: 'error', message: '已取消取得音訊檔。' });
  }

  useEffect(() => {
    const available = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
    setSpeech(available ? 'idle' : 'unavailable');
    setSpeechMessage('');
    return () => {
      if (utterance.current && available) {
        utterance.current = null;
        window.speechSynthesis.cancel();
      }
    };
  }, [ready?.report.fingerprint, userId]);

  function stopSpeech() {
    if (!utterance.current) return;
    utterance.current = null;
    window.speechSynthesis.cancel();
    setSpeech('idle');
    setSpeechMessage('已停止裝置語音。');
  }
  function playSpeech() {
    if (!ready || speech === 'unavailable' || utterance.current) return;
    const engine = window.speechSynthesis;
    if (engine.speaking || engine.pending) {
      setSpeech('error'); setSpeechMessage('裝置正在播放其他語音，請待播放結束後重試。'); return;
    }
    const voices = engine.getVoices().filter((voice) => voice.localService);
    const voice = voices.find((item) => /^zh(?:-|_)/i.test(item.lang)) ?? voices[0];
    if (!voice) { setSpeech('error'); setSpeechMessage('裝置尚未提供本機語音，請稍後重試。'); return; }
    audioElement.current?.pause();
    const current = new SpeechSynthesisUtterance(ready.report.summary);
    current.voice = voice;
    current.lang = voice.lang;
    current.onstart = () => { if (utterance.current === current) setSpeech('playing'); };
    current.onend = () => { if (utterance.current === current) { utterance.current = null; setSpeech('idle'); setSpeechMessage('裝置語音已播放完畢。'); } };
    current.onerror = () => { if (utterance.current === current) { utterance.current = null; setSpeech('error'); setSpeechMessage('裝置語音未能播放，請重試。'); } };
    utterance.current = current;
    setSpeech('starting'); setSpeechMessage('');
    try { engine.speak(current); }
    catch { utterance.current = null; setSpeech('error'); setSpeechMessage('裝置語音未能播放，請重試。'); }
  }

  const report = ready?.report;
  const evidenceStart = evidencePage * 40;
  const shownEvidence = report?.evidence.slice(evidenceStart, evidenceStart + 40) ?? [];
  const missionComplete = report?.coverage.find((source) => source.source === 'mission')?.complete === true;
  const metrics = report ? [
    { label: '已驗證完成', value: report.counts.completed },
    { label: '自主解決事件', value: report.counts.autonomouslyResolved },
    { label: '仍在進行', value: missionComplete ? report.counts.running : null },
    { label: '需要你處理', value: missionComplete ? report.counts.needsHuman : null }
  ] : [];

  return (
    <PageContainer width='reading' pageTitle='James Agent Team' pageEyebrow='私人報告' pageDescription={`${workday} · ${kind === 'whole_day' ? '全日報告' : '半日報告'} · 固定版本 ${version}`}>
      <div lang='zh-Hant' className='flex min-w-0 flex-col gap-5'>
        {status === 'loading' && <p role='status' className='text-muted-foreground'>正在核對登入狀態…</p>}
        {status !== 'loading' && status !== 'signed-in' && <Surface><p role='status'>{status === 'mfa-required' ? '請完成目前帳戶的登入驗證，再查看這份私人報告。' : '請登入有權查看報告的 Rafii 帳戶。'}</p></Surface>}
        {status === 'signed-in' && (!load || load.key !== key || load.state === 'loading') && <Surface><p role='status' aria-live='polite'>正在讀取指定版本的報告與圖像…</p></Surface>}
        {status === 'signed-in' && load?.key === key && load.state === 'error' && <Surface className='space-y-4'><p role='alert'>{load.message}</p><Button variant='glass' size='control' onClick={() => setReload((value) => value + 1)}>重試此版本</Button></Surface>}
        {report && ready && <>
          <Surface as='section' aria-labelledby='agent-team-version' material='quiet' className='space-y-3'>
            <h2 id='agent-team-version' className='font-medium'>不可變更的報告版本 {report.version}</h2>
            <p className='text-muted-foreground text-sm'>資料截至 <time dateTime={report.asOf}>{dateLabel(report.asOf)}</time> · Indianapolis</p>
            <p className='text-muted-foreground text-sm'>生成於 <time dateTime={report.generatedAt}>{dateLabel(report.generatedAt)}</time></p>
            <p className='text-muted-foreground break-all text-xs'>報告識別：{report.fingerprint}</p>
          </Surface>
          <figure className='rafii-quiet overflow-hidden rounded-[var(--rafii-radius-card)]'>
            {imageFailed ? <p role='alert' className='p-5'>報告圖像未能顯示，摘要與來源資料如下。</p> : <Image unoptimized src={ready.imageUrl} alt={`${report.period.workday} ${kind === 'whole_day' ? '全日' : '半日'}報告，版本 ${report.version}；相同數字及來源缺口於下方提供文字。`} width={1080} height={1420} className='h-auto w-full' onError={() => setImageFailed(true)} />}
            <figcaption className='text-muted-foreground px-5 py-3 text-xs'>圖像與摘要已核對為同一版本。報告生成與送達狀態分開記錄。</figcaption>
          </figure>
          <dl className='grid grid-cols-2 gap-3 sm:grid-cols-4' aria-label='任務與事件數量'>
            {metrics.map((metric) => <Surface key={metric.label} material='quiet' padding='sm'><dt className='text-muted-foreground text-xs leading-relaxed'>{metric.label}</dt><dd className='mt-2 text-2xl font-medium tabular-nums'>{metric.value === null ? <span className='text-base'>未知</span> : metric.value.toLocaleString('zh-Hant-HK')}</dd></Surface>)}
          </dl>
          {!missionComplete && <p className='text-muted-foreground text-sm'>任務來源尚未完整核對，仍在進行及需要你處理的總數保留為未知。</p>}
          <Surface as='section' aria-labelledby='agent-team-summary' className='space-y-4'>
            <h2 id='agent-team-summary' className='font-medium'>本版摘要</h2>
            <p className='whitespace-pre-line break-words text-sm leading-7'>{report.summary}</p>
            <div className='flex flex-wrap items-center gap-2'>
              <Button variant='glass' size='control' onClick={playSpeech} disabled={speech === 'unavailable' || speech === 'starting' || speech === 'playing'}>{speech === 'starting' ? '準備裝置語音…' : speech === 'playing' ? '裝置語音播放中' : '播放裝置語音'}</Button>
              <Button variant='quiet' size='control' onClick={stopSpeech} disabled={speech !== 'starting' && speech !== 'playing'}>停止</Button>
            </div>
            <p className='text-muted-foreground text-xs'>裝置語音只會在你按下播放後，使用可用的本機語音朗讀以上摘要。</p>
            <p role={speech === 'error' ? 'alert' : 'status'} aria-live='polite' className='text-muted-foreground text-sm'>{speech === 'unavailable' ? '這部裝置未提供語音朗讀。' : speechMessage}</p>
          </Surface>
          {kind === 'whole_day' && <Surface as='section' aria-labelledby='agent-team-audio' className='space-y-4'>
            <h2 id='agent-team-audio' className='font-medium'>報告音訊檔</h2>
            <p className='text-muted-foreground text-sm'>可用的報告音訊檔使用本機 macOS Sinji（zh_HK）語音朗讀本版摘要節錄。按下取得後才會下載音訊，播放由下方控制選擇。</p>
            {visibleAudio?.state !== 'ready' && <div className='flex flex-wrap gap-2'>
              <Button variant='glass' size='control' onClick={() => { void loadAudio(); }} disabled={visibleAudio?.state === 'loading'}>{visibleAudio?.state === 'loading' ? '正在核對音訊檔…' : visibleAudio?.state === 'error' ? '重試本版音訊檔' : '取得本版音訊檔'}</Button>
              {visibleAudio?.state === 'loading' && <Button variant='quiet' size='control' onClick={cancelAudio}>取消</Button>}
            </div>}
            {visibleAudio?.state === 'loading' && <p role='status' aria-live='polite' className='text-muted-foreground text-sm'>正在讀取與圖像相同版本的 WAV，核對指紋、格式及 SHA-256…</p>}
            {visibleAudio?.state === 'error' && <p role='alert' className='text-muted-foreground text-sm'>{visibleAudio.message} 圖像報告與摘要仍可查看。</p>}
            {visibleAudio?.state === 'ready' && <>
              <audio ref={audioElement} controls preload='none' src={visibleAudio.url} aria-label={`全日報告摘要節錄音訊，版本 ${report.version}`} aria-describedby='agent-team-audio-transcript' className='w-full' onPlay={stopSpeech} onError={() => { releaseAudio(); setAudio({ key: audioKey, state: 'error', message: '這部裝置未能播放 WAV，可重試取得音訊檔。' }); }}>
                <track kind='captions' src={visibleAudio.captionsUrl} srcLang='zh-HK' label='廣東話摘要節錄' default />
                這部裝置未提供音訊播放控制。
              </audio>
              <p id='agent-team-audio-transcript' className='whitespace-pre-line break-words text-sm leading-7'><span className='font-medium'>已核對的音訊逐字稿：</span>{visibleAudio.transcript}</p>
              <p role='status' aria-live='polite' className='text-muted-foreground text-xs'>已核對版本 {report.version} · RIFF PCM · 單聲道 · {visibleAudio.pcm.sampleRate.toLocaleString('zh-Hant-HK')} Hz · {visibleAudio.pcm.bitsPerSample}-bit · {visibleAudio.pcm.durationSeconds.toFixed(1)} 秒 · {(visibleAudio.pcm.byteCount / 1024).toFixed(1)} KiB</p>
              <p className='text-muted-foreground break-all text-xs'>音訊 SHA-256（已核對）：{visibleAudio.sha256}</p>
              <a href={visibleAudio.url} download={`james-agent-team-${workday}-whole-day-v${report.version}.wav`} className='rafii-focus inline-flex min-h-11 items-center text-sm underline underline-offset-4'>下載此版本 WAV</a>
            </>}
          </Surface>}
          <Surface as='section' aria-labelledby='agent-team-coverage' className='space-y-4'>
            <h2 id='agent-team-coverage' className='font-medium'>來源覆蓋與缺口</h2>
            <p className='text-muted-foreground text-sm'>未完整核對來源：{report.coverage.filter((source) => !source.complete).length}／{report.coverage.length} · 狀態未知來源：{report.coverage.filter((source) => source.status === 'unknown').length}</p>
            <ul className='divide-border/50 divide-y'>
              {report.coverage.map((source) => <li key={source.source} className='space-y-1 py-3 text-sm'><p className='flex flex-wrap justify-between gap-2'><span className='font-medium'>{source.source}</span><span>{source.complete ? '已完整核對' : '未完整核對'} · {source.status} · {source.count} 筆</span></p><p className='text-muted-foreground text-xs'>{source.freshAt ? `來源資料時間：${dateLabel(source.freshAt)}` : '來源資料時間未知'}</p>{source.gaps.length > 0 && <p className='text-muted-foreground break-words text-xs'>{source.gaps.join(' · ')}</p>}</li>)}
            </ul>
            {report.gaps.length > 0 ? <div className='space-y-2'><h3 className='text-sm font-medium'>報告缺口（{report.gaps.length}）</h3><ul className='list-inside list-disc space-y-2 break-words text-sm text-muted-foreground'>{report.gaps.map((gap, index) => <li key={`${index}:${gap}`}>{gap}</li>)}</ul></div> : <p className='text-muted-foreground text-sm'>本版沒有列出來源缺口。</p>}
          </Surface>
          <Surface as='section' aria-labelledby='agent-team-evidence' className='space-y-3'>
            <h2 id='agent-team-evidence' className='font-medium'>來源證據（{report.evidence.length}）</h2>
            <p className='text-muted-foreground text-xs'>來源記錄只證明曾觀察到活動；完成數仍須有驗收證據。</p>
            {report.evidence.length === 0 ? <p className='text-muted-foreground text-sm'>本版沒有可回查的來源記錄。</p> : <>
              <p role='status' className='text-muted-foreground text-xs'>顯示 {evidenceStart + 1}–{Math.min(evidenceStart + 40, report.evidence.length)}／{report.evidence.length} 筆</p>
              <ul className='divide-border/50 divide-y'>{shownEvidence.map((item, index) => <li key={`${item.id}:${index}`} className='py-3 text-sm'><p className='break-words'>{item.url ? <a href={item.url} target='_blank' rel='noopener noreferrer' referrerPolicy='no-referrer' className='rafii-focus inline-flex min-h-11 items-center underline underline-offset-4'>{item.source} · {item.id.slice(0, 12)}<span className='sr-only'>（在新分頁開啟 HTTPS 證據）</span></a> : <span>{item.source} · {item.id.slice(0, 12)} · 未提供可開啟的 HTTPS 證據連結</span>}</p><p className='text-muted-foreground text-xs'>來源記錄 <time dateTime={item.capturedAt}>{dateLabel(item.capturedAt)}</time> · 收到觀察 <time dateTime={item.observedAt}>{dateLabel(item.observedAt)}</time></p></li>)}</ul>
              {report.evidence.length > 40 && <div className='flex flex-wrap gap-2'><Button variant='quiet' size='control' disabled={evidencePage === 0} onClick={() => setEvidencePage((value) => Math.max(0, value - 1))}>上一頁證據</Button><Button variant='glass' size='control' disabled={evidenceStart + 40 >= report.evidence.length} onClick={() => setEvidencePage((value) => value + 1)}>下一頁證據</Button></div>}
            </>}
          </Surface>
          <p className='text-muted-foreground text-xs'>本頁供查看與朗讀報告。任務續行與恢復入口尚未接通。</p>
        </>}
      </div>
    </PageContainer>
  );
}
