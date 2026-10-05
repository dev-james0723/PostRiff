'use client';

/**
 * One composer's chips (chat-context SPEC §4, §11.2–§11.5): uploads, reads, the `@` list, persistence and the exact
 * request fields. Pure transitions live in `state.ts`; this hook only runs the side effects around them.
 *
 * - Photos: `fitForUpload` → `p2_media_upload`, one at a time; the new asset id is the snapshot diff; a 409 refetches
 *   and retries once (the Library queue pattern).
 * - Videos: check → metadata → blank location tags → frames → begin → signed PUT with progress and a Wake Lock →
 *   commit with backoff. After a successful PUT the upload is never aborted; a retry commits again.
 * - Text files: decode → fingerprint reuse or the `source` action; the "Use {file}" sheet reads `textFile`.
 * - Reads (reference media): automatic 800 ms after the role change when credit mode is off and the chip is eligible;
 *   in credit mode only `read(key)` (the person's tap) runs, after an estimate and a quote. `settleReads` waits at most
 *   20 s at send.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type SyntheticEvent
} from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { keys, useAct } from '@/lib/api/hooks';
import type { AttachmentsCatalog, Asset, Snapshot } from '@/lib/api/types';
import { putSignedUpload, UPLOAD_FAILED, UploadError } from '@/lib/api/upload';
import { fitForUpload, SAFE_SEND_BYTES, UnreadableImage } from '@/lib/image/fit-for-upload';
import { createImeGuard } from '@/lib/ime';
import { kindOf } from '@/lib/media/asset-kinds';
import {
  decodeText,
  isTextFile,
  openedAsMessage,
  TextFileTooLarge,
  type TextEncodingName
} from '@/lib/media/text-file';
import { useWorkspaceApi } from '@/lib/workspace/provider';

import {
  briefStorageKey,
  decodeBriefState,
  encodeBrief,
  turnStorageKey,
  type SavedBrief
} from '../brief-recovery';
import { insertLabel, postRoleDefault, type Chip, type MediaRole, type PostRole } from './chips';
import { CLOSED, reduceMention, type MentionState } from './mention';
import { handleMentionKeyDown, MENTION_ROWS } from './mention-list';
import {
  allPickerItems,
  flatten,
  pickerItems,
  type ConnectorItemLike,
  type PickerItem
} from './picker-items';
import { usePickerSearch } from './use-picker-search';
import {
  blockerMessage,
  blockers as blockingChips,
  EMPTY,
  fields as requestFieldsOf,
  fromSaved,
  readingMessage,
  reduce,
  refusal,
  sentKeys,
  toSaved,
  UNDO_MS,
  UPLOAD_STOPPED
} from './state';
import {
  blankLocation,
  checkDuration,
  checkVideoFile,
  extractFrames,
  readVideoMetadata,
  VIDEO_MESSAGES,
  VideoProblem
} from './video-file';

export const READ_DELAY_MS = 800;
export const SEND_READ_WAIT_MS = 20_000;
const COMMIT_BACKOFF_MS = [0, 1_000, 2_000, 4_000];
const READ_POLL_MS = 2_000;
const READ_POLLS = 10;

export interface ComposerAttachmentsOptions {
  surface: 'home' | 'conversation';
  workspaceId: string;
  conversationId?: string;
  /** The signed-in person: template visibility and the session key. */
  owner?: string | null;
  /** The chosen writer is the free preview writer ("Templates (no AI model)"): nothing is read. */
  fixtureWriter?: boolean;
  creditMode: boolean;
  catalog: AttachmentsCatalog | null | undefined;
  snapshot: Snapshot | null | undefined;
  imageGeneration?: boolean;
  /** The message text, for the default post role. */
  text?: string;
  /** Picking an account or folder in the `@` list adds destinations, not chips. */
  onDestination?: (item: PickerItem) => void;
  /** Items the caller takes instead of a chip; return true when taken (Home: sources → Context Pocket, a template →
   *  this message's template). Text files that become sources go through it too. */
  route?: (item: PickerItem) => boolean;
  /** The composer's single polite live region. */
  announce?: (message: string) => void;
}

export interface TextFileResult {
  sourceId: string;
  name: string;
  encoding: TextEncodingName;
  reused: boolean;
}

interface Pending {
  file?: File;
  controller?: AbortController;
  /** Video: the server asset once begun, and whether the PUT finished (then only commit may run again). */
  assetId?: string;
  put?: boolean;
  commit?: { frames: { at: number; data: string }[]; locationCleared: boolean };
  /** What this browser could check before uploading (shown on the chip once the video is ready). */
  local?: { noPreview: boolean; lengthUnchecked: boolean };
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''), {
      once: true
    });
    reader.addEventListener('error', () => reject(reader.error), { once: true });
    reader.readAsDataURL(blob);
  });
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function isVideoFile(file: File): boolean {
  return file.type.startsWith('video/') || /\.(mp4|mov)$/i.test(file.name);
}

async function holdWakeLock(): Promise<(() => void) | null> {
  try {
    const lock = await (
      navigator as Navigator & {
        wakeLock?: { request(type: 'screen'): Promise<{ release(): Promise<void> }> };
      }
    ).wakeLock?.request('screen');
    return lock ? () => void lock.release().catch(() => undefined) : null;
  } catch {
    return null;
  }
}

/** Whether reference media can be read now (SPEC §4.6): a reader, current consent for it, a non-fixture writer. */
export function readEligible(
  catalog: AttachmentsCatalog | null | undefined,
  snapshot: Snapshot | null | undefined,
  fixtureWriter: boolean
): boolean {
  const processor = catalog?.notes.processor;
  if (!catalog?.notes.available || !processor || fixtureWriter) return false;
  const egress = (
    snapshot?.state as
      | { mediaEgress?: { cloud?: boolean; processors?: { id?: string }[] } }
      | undefined
  )?.mediaEgress;
  return (
    egress?.cloud === true && (egress.processors ?? []).some((item) => item?.id === processor.id)
  );
}

export function useComposerAttachments(options: ComposerAttachmentsOptions) {
  const {
    surface,
    workspaceId,
    conversationId,
    owner,
    creditMode,
    catalog,
    snapshot,
    announce,
    onDestination,
    route
  } = options;
  const imageGeneration = Boolean(options.imageGeneration);
  const { api } = useWorkspaceApi();
  const client = useQueryClient();
  const act = useAct();
  const [state, dispatch] = useReducer(reduce, EMPTY);
  const stateRef = useRef(state);
  stateRef.current = state;
  const pending = useRef(new Map<string, Pending>());
  const counter = useRef(0);
  const photoQueue = useRef<Promise<unknown>>(Promise.resolve());
  const readTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const [textFile, setTextFile] = useState<TextFileResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [connectorItems, setConnectorItems] = useState<ConnectorItemLike[]>([]);
  const eligible = readEligible(catalog, snapshot, Boolean(options.fixtureWriter));
  const eligibleRef = useRef(eligible);
  eligibleRef.current = eligible;

  const nextKey = useCallback(() => `chip-${++counter.current}`, []);
  const say = useCallback((message: string) => announce?.(message), [announce]);

  // --- workspace revision helpers (the Library queue pattern) -----------------------------------------------------------
  const currentSnapshot = useCallback(
    () => client.getQueryData<Snapshot>(keys.snapshot(workspaceId)) ?? snapshot ?? null,
    [client, workspaceId, snapshot]
  );
  const mutate = useCallback(
    async (action: string, payload: Record<string, unknown>) => {
      const attempt = async () => {
        const revision = currentSnapshot()?.revision;
        if (typeof revision !== 'number')
          throw new ApiError('The workspace is still loading. Try again in a moment.', 409);
        return act.mutateAsync({ revision, action, payload });
      };
      try {
        return await attempt();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        await client.refetchQueries({ queryKey: keys.snapshot(workspaceId), exact: true });
        return attempt();
      }
    },
    [act, client, currentSnapshot, workspaceId]
  );

  // --- reads ----------------------------------------------------------------------------------------------------------------
  const runRead = useCallback(
    async (key: string) => {
      const chip = stateRef.current.chips.find((item) => item.key === key);
      if (
        !chip ||
        (chip.kind !== 'image' && chip.kind !== 'video') ||
        chip.role !== 'reference' ||
        !eligibleRef.current
      )
        return;
      if (chip.upload && chip.upload.status !== 'ready') return;
      dispatch({ type: 'reading', key });
      try {
        let creditQuoteId: string | undefined;
        if (creditMode) {
          const request = { operation: 'media-notes' as const, request: { assetId: chip.id } };
          const estimate = await api.creditEstimate(workspaceId, request);
          if (!estimate.cached) {
            const quote = await api.creditQuote(workspaceId, {
              ...request,
              maxMilliCredits: estimate.ceilingMilliCredits,
              expectedRevision: estimate.stateRevision
            });
            creditQuoteId = quote.quoteId;
          }
        }
        const idempotencyKey = `${chip.id}:${Date.now().toString(36)}`;
        for (let poll = 0; poll <= READ_POLLS; poll += 1) {
          const result = await api.mediaNotes(workspaceId, {
            assetId: chip.id,
            idempotencyKey,
            ...(creditQuoteId ? { creditQuoteId } : {})
          });
          if (result.status === 'ready') {
            dispatch({
              type: 'read',
              key,
              note: result.note.text,
              milliCredits: result.usage?.milliCredits
            });
            say(`${chip.label} is ready.`);
            return;
          }
          if (result.status !== 'reading') break;
          await wait(READ_POLL_MS);
        }
        dispatch({ type: 'readFailed', key });
      } catch {
        dispatch({ type: 'readFailed', key });
      }
    },
    [api, creditMode, say, workspaceId]
  );

  const scheduleRead = useCallback(
    (key: string) => {
      if (creditMode) return; // credit mode reads only on the person's tap (read(key))
      clearTimeout(readTimers.current.get(key));
      readTimers.current.set(
        key,
        setTimeout(() => {
          readTimers.current.delete(key);
          void runRead(key);
        }, READ_DELAY_MS)
      );
    },
    [creditMode, runRead]
  );

  // --- uploads --------------------------------------------------------------------------------------------------------------
  const uploadPhoto = useCallback(
    (key: string, file: File) => {
      const job = photoQueue.current.then(async () => {
        if (!stateRef.current.chips.some((chip) => chip.key === key)) return;
        dispatch({ type: 'upload', key, status: 'preparing' });
        try {
          const fitted = await fitForUpload(file, SAFE_SEND_BYTES);
          if (!fitted) throw new UnreadableImage('unreadable');
          const data = await toBase64(fitted);
          dispatch({ type: 'upload', key, status: 'uploading' });
          const before = new Set(
            (currentSnapshot()?.state.phase2?.assets ?? []).map((asset) => asset.id)
          );
          const after = await mutate('p2_media_upload', { data });
          const added = (after.state.phase2?.assets ?? []).find(
            (asset) => !before.has(asset.id) && !asset.deleted
          );
          if (!added) throw new ApiError(UPLOAD_FAILED, 500);
          dispatch({
            type: 'uploaded',
            key,
            id: added.id,
            meta: { mime: added.mime, width: added.width, height: added.height }
          });
          pending.current.delete(key);
          const chip = stateRef.current.chips.find((item) => item.key === key);
          if (chip?.role === 'reference') scheduleRead(key);
        } catch (error) {
          const message =
            error instanceof UnreadableImage || error instanceof ApiError
              ? error.message
              : UPLOAD_FAILED;
          dispatch({
            type: 'failed',
            key,
            message: message === 'unreadable' ? UPLOAD_FAILED : message
          });
          say(UPLOAD_FAILED);
        }
      });
      photoQueue.current = job.catch(() => undefined);
      return job;
    },
    [currentSnapshot, mutate, say, scheduleRead]
  );

  const commitVideo = useCallback(
    async (key: string, entry: Pending) => {
      if (!entry.assetId || !entry.commit) return;
      dispatch({ type: 'upload', key, status: 'checking' });
      let lastError: unknown = null;
      for (const delay of COMMIT_BACKOFF_MS) {
        if (delay) await wait(delay);
        try {
          const result = await api.commitVideoUpload(workspaceId, entry.assetId, entry.commit);
          dispatch({
            type: 'uploaded',
            key,
            id: result.video.assetId,
            meta: {
              ...entry.local,
              mime: 'video/mp4',
              duration: result.video.duration ?? undefined,
              width: result.video.width ?? undefined,
              height: result.video.height ?? undefined
            }
          });
          pending.current.delete(key);
          await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId), exact: true });
          const chip = stateRef.current.chips.find((item) => item.key === key);
          if (chip?.role === 'reference') scheduleRead(key);
          return;
        } catch (error) {
          lastError = error;
          // A refusal (4xx other than a conflict) will not change on retry.
          if (
            error instanceof ApiError &&
            error.status >= 400 &&
            error.status < 500 &&
            error.status !== 409
          )
            break;
        }
      }
      dispatch({
        type: 'failed',
        key,
        message: lastError instanceof ApiError ? lastError.message : UPLOAD_FAILED
      });
      say(UPLOAD_FAILED);
    },
    [api, client, say, scheduleRead, workspaceId]
  );

  const uploadVideo = useCallback(
    async (key: string, file: File) => {
      const entry = pending.current.get(key) ?? { file };
      pending.current.set(key, entry);
      if (entry.put) return commitVideo(key, entry); // never re-upload after a successful PUT
      const policy = {
        maxBytes: catalog?.video.maxBytes ?? 100_000_000,
        maxSeconds: catalog?.video.maxSeconds ?? 180
      };
      dispatch({ type: 'upload', key, status: 'preparing' });
      try {
        const checked = await checkVideoFile(file, policy);
        if (!checked.ok || !checked.mime)
          throw new VideoProblem(checked.message ?? VIDEO_MESSAGES.format);
        const metadata = await readVideoMetadata(file);
        const tooLong = checkDuration(metadata?.duration ?? null, policy);
        if (tooLong) throw new VideoProblem(tooLong);
        const blanked = await blankLocation(file);
        const frames = await extractFrames(blanked.blob);
        const encoded = await Promise.all(
          frames.map(async (frame) => ({ at: frame.at, data: await toBase64(frame.blob) }))
        );
        const ticket = await api.beginVideoUpload(workspaceId, {
          mime: checked.mime,
          bytes: blanked.blob.size,
          duration: metadata?.duration ?? null,
          width: metadata?.width ?? null,
          height: metadata?.height ?? null
        });
        entry.assetId = ticket.upload.assetId;
        entry.commit = { frames: encoded, locationCleared: blanked.locationCleared };
        entry.local = { noPreview: encoded.length === 0, lengthUnchecked: !metadata };
        entry.controller = new AbortController();
        dispatch({ type: 'upload', key, status: 'uploading', progress: 0 });
        const release = await holdWakeLock();
        try {
          await putSignedUpload(
            ticket.upload.uploadUrl,
            blanked.blob,
            ticket.upload.headers,
            (fraction) =>
              dispatch({ type: 'upload', key, status: 'uploading', progress: fraction * 100 }),
            entry.controller.signal
          );
        } finally {
          release?.();
        }
        entry.put = true;
        await commitVideo(key, entry);
      } catch (error) {
        const message =
          error instanceof VideoProblem || error instanceof UploadError || error instanceof ApiError
            ? error.message
            : VIDEO_MESSAGES.prepare;
        dispatch({ type: 'failed', key, message });
        say(UPLOAD_FAILED);
      }
    },
    [api, catalog, commitVideo, say, workspaceId]
  );

  const addTextFile = useCallback(
    async (file: File) => {
      try {
        const decoded = decodeText(await file.arrayBuffer());
        const body = decoded.text.trim();
        const fingerprint = await sha256Hex(`document${body}`);
        const sources = currentSnapshot()?.state.sources ?? [];
        const existing = sources.find(
          (source) =>
            source.active && (source as { fingerprint?: string }).fingerprint === fingerprint
        );
        let sourceId = existing?.id ?? null;
        if (!sourceId) {
          const before = new Set(sources.map((source) => source.id));
          try {
            const after = await mutate('source', {
              kind: 'document',
              title: file.name,
              text: decoded.text
            });
            sourceId =
              (after.state.sources ?? []).find((source) => !before.has(source.id))?.id ?? null;
          } catch (error) {
            // "Already here": fall back to the best title match (SPEC §7.5).
            if (!(error instanceof ApiError) || error.status !== 400) throw error;
            sourceId =
              sources.find((source) => source.active && source.title === file.name)?.id ?? null;
            if (!sourceId) throw error;
          }
        }
        if (!sourceId) throw new ApiError(UPLOAD_FAILED, 500);
        const chip: Chip = {
          key: nextKey(),
          kind: 'source',
          id: sourceId,
          label: file.name.slice(0, 40)
        };
        const routed = route?.({ kind: 'source', id: sourceId, label: chip.label }) ?? false;
        const refused = routed ? null : refusal(stateRef.current.chips, chip);
        if (refused && refused !== 'duplicate') {
          setNotice(refused);
          return null;
        }
        if (!routed && !refused) dispatch({ type: 'add', chip });
        const result = {
          sourceId,
          name: file.name,
          encoding: decoded.encoding,
          reused: Boolean(existing)
        };
        setTextFile(result);
        say(existing ? 'This file is already in your sources.' : openedAsMessage(decoded.encoding));
        return result;
      } catch (error) {
        const message =
          error instanceof TextFileTooLarge || error instanceof ApiError
            ? error.message
            : UPLOAD_FAILED;
        setNotice(message);
        say(message);
        return null;
      }
    },
    [currentSnapshot, mutate, nextKey, route, say]
  );

  // --- actions --------------------------------------------------------------------------------------------------------------
  const add = useCallback(
    (chip: Chip): boolean => {
      const refused = refusal(stateRef.current.chips, chip);
      if (refused) {
        if (refused !== 'duplicate') {
          setNotice(refused);
          say(refused);
        }
        return false;
      }
      dispatch({ type: 'add', chip });
      say(`${chip.label} added.`);
      return true;
    },
    [say]
  );

  const addFiles = useCallback(
    (files: Iterable<File>, role: MediaRole = 'post') => {
      for (const file of Array.from(files)) {
        if (isTextFile(file)) {
          void addTextFile(file);
          continue;
        }
        const video = isVideoFile(file);
        if (video && !catalog?.video.enabled) {
          setNotice(VIDEO_MESSAGES.format);
          continue;
        }
        const key = nextKey();
        const kind = video ? 'video' : 'image';
        const chip: Chip = {
          key,
          kind,
          id: key,
          label: kind === 'video' ? 'Video' : 'Photo',
          role,
          upload: { status: 'preparing' }
        };
        if (!add(chip)) continue;
        pending.current.set(key, { file });
        if (video) void uploadVideo(key, file);
        else void uploadPhoto(key, file);
      }
    },
    [add, addTextFile, catalog, nextKey, uploadPhoto, uploadVideo]
  );

  const addLibrary = useCallback(
    (assets: readonly Asset[], role: MediaRole = 'post') => {
      for (const asset of assets) {
        const kind = kindOf(asset);
        if (!kind || kind === 'document') continue;
        const key = nextKey();
        if (
          add({
            key,
            kind,
            id: asset.id,
            label: kind === 'video' ? 'Video' : 'Photo',
            role,
            meta: {
              mime: asset.mime,
              duration: asset.duration,
              width: asset.width,
              height: asset.height
            }
          }) &&
          role === 'reference'
        )
          scheduleRead(key);
      }
    },
    [add, nextKey, scheduleRead]
  );

  /** A post, template or source from the picker. Accounts and folders are destinations (`onDestination`), not chips. */
  const addReference = useCallback(
    (item: PickerItem): boolean => {
      if (item.kind === 'account' || item.kind === 'folder') {
        onDestination?.(item);
        return true;
      }
      if (route?.(item)) {
        say(`${item.label} added.`);
        return true;
      }
      if (item.kind === 'image' || item.kind === 'video') {
        return add({
          key: nextKey(),
          kind: item.kind,
          id: item.id,
          label: item.label,
          role: 'post'
        });
      }
      const posts = stateRef.current.chips.filter((chip) => chip.kind === 'post').length;
      const role: PostRole | undefined =
        item.kind === 'post' ? postRoleDefault(options.text ?? '', posts + 1) : undefined;
      const hasRework = stateRef.current.chips.some(
        (chip) => chip.kind === 'post' && chip.role === 'rework'
      );
      return add({
        key: nextKey(),
        kind: item.kind,
        id: item.id,
        label: item.label,
        ...(role ? { role: role === 'rework' && hasRework ? 'inspire' : role } : {}),
        meta: { platform: item.platform }
      });
    },
    [add, nextKey, onDestination, options.text, route, say]
  );

  const setRole = useCallback(
    (key: string, role: PostRole | MediaRole) => {
      dispatch({ type: 'role', key, role });
      const chip = stateRef.current.chips.find((item) => item.key === key);
      if (role === 'reference' && chip && chip.read?.status !== 'read') scheduleRead(key);
    },
    [scheduleRead]
  );

  const remove = useCallback(
    (key: string) => {
      const chip = stateRef.current.chips.find((item) => item.key === key);
      if (!chip) return;
      clearTimeout(readTimers.current.get(key));
      dispatch({ type: 'remove', key, at: Date.now() });
      say(`${chip.label} removed.`);
      setTimeout(() => dispatch({ type: 'expire', at: Date.now() }), UNDO_MS + 50);
    },
    [say]
  );

  const undo = useCallback((key?: string) => dispatch({ type: 'undo', key, at: Date.now() }), []);

  // Only when the undo window passes (the chip left both `chips` and `removed`) is an in-flight upload aborted, and a
  // video that never finished its PUT released; a committed asset stays in the Library.
  useEffect(() => {
    const live = new Set([
      ...state.chips.map((chip) => chip.key),
      ...state.removed.map((item) => item.chip.key)
    ]);
    for (const [key, entry] of pending.current) {
      if (live.has(key)) continue;
      entry.controller?.abort();
      if (entry.assetId && !entry.put)
        void api.abortVideoUpload(workspaceId, entry.assetId).catch(() => undefined);
      pending.current.delete(key);
    }
  }, [api, state, workspaceId]);

  const retry = useCallback(
    (key: string) => {
      const chip = stateRef.current.chips.find((item) => item.key === key);
      if (!chip) return;
      if (chip.read?.status === 'failed') {
        void runRead(key);
        return;
      }
      const entry = pending.current.get(key);
      if (chip.upload?.status !== 'failed' || !entry?.file) return;
      dispatch({ type: 'retry', key });
      if (chip.kind === 'video') void uploadVideo(key, entry.file);
      else void uploadPhoto(key, entry.file);
    },
    [runRead, uploadPhoto, uploadVideo]
  );

  const read = useCallback((key: string) => runRead(key), [runRead]);

  /** At send: wait for running reads, at most 20 s; a reference still unread is reported `not_read_yet` by the server. */
  const settleReads = useCallback(async (timeoutMs = SEND_READ_WAIT_MS) => {
    const started = Date.now();
    while (
      stateRef.current.chips.some((chip) => chip.read?.status === 'reading') &&
      Date.now() - started < timeoutMs
    )
      await wait(250);
  }, []);

  const clearSent = useCallback(
    (sent: readonly string[]) => dispatch({ type: 'clearSent', keys: sent }),
    []
  );

  useEffect(
    () => () => {
      for (const timer of readTimers.current.values()) clearTimeout(timer);
    },
    []
  );

  // --- persistence (SPEC §11.5) ---------------------------------------------------------------------------------------------
  const storageKey = owner
    ? surface === 'conversation'
      ? conversationId
        ? turnStorageKey(owner, workspaceId, conversationId)
        : null
      : briefStorageKey(owner, workspaceId)
    : null;
  const [recovered, setRecovered] = useState<SavedBrief | null>(null);
  const restoredFor = useRef<string | null>(null);
  useEffect(() => {
    if (!storageKey || !owner || !snapshot || restoredFor.current === storageKey) return;
    restoredFor.current = storageKey;
    let saved: SavedBrief | null = null;
    try {
      saved = decodeBriefState(sessionStorage.getItem(storageKey), owner, workspaceId);
    } catch {
      saved = null;
    }
    if (!saved) return;
    setRecovered(saved);
    const available = new Set(
      allPickerItems(snapshot, owner, catalog?.skills ?? [], connectorItems).map(
        (item) => `${item.kind}:${item.id}`
      )
    );
    const { chips, dropped } = fromSaved(saved.chips, available, () => nextKey());
    dispatch({ type: 'restore', chips });
    if (dropped.length)
      say(
        dropped.length === 1 ? `${dropped[0].label} removed.` : `${dropped.length} items removed.`
      );
    if (chips.some((chip) => chip.upload?.message === UPLOAD_STOPPED)) say(UPLOAD_STOPPED);
  }, [catalog?.skills, connectorItems, nextKey, owner, say, snapshot, storageKey, workspaceId]);

  /** Save the text with the chips (session only); the caller calls this where it saved text before. */
  const persist = useCallback(
    (text: string) => {
      if (!storageKey || !owner) return;
      try {
        if (!text && !stateRef.current.chips.length) sessionStorage.removeItem(storageKey);
        else
          sessionStorage.setItem(
            storageKey,
            encodeBrief(owner, workspaceId, text, toSaved(stateRef.current.chips))
          );
      } catch {
        // Storage full or blocked: recovery is a convenience.
      }
    },
    [owner, storageKey, workspaceId]
  );

  // --- the `@` list ---------------------------------------------------------------------------------------------------------
  const ime = useMemo(() => createImeGuard(), []);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [mention, setMention] = useState<MentionState>(CLOSED);
  const [active, setActive] = useState(0);
  const queuedPick = useRef<PickerItem | null>(null);
  const listId = `mention-${surface}-${conversationId ?? 'home'}`;
  const open = mention.anchor !== null;
  const localItems = useMemo(
    () =>
      open
        ? flatten(
            pickerItems(
              snapshot,
              owner,
              mention.query,
              undefined,
              catalog?.skills ?? [],
              connectorItems
            )
          )
        : [],
    [catalog?.skills, connectorItems, open, snapshot, owner, mention.query]
  );
  // Typed queries also ask the server (debounced); its results win by id, local ones show until it answers.
  const items = usePickerSearch(mention.query, localItems, { enabled: open });

  const applyPick = useCallback(
    (item: PickerItem) => {
      const element = textareaRef.current;
      const anchor = mention.anchor;
      if (!element || anchor === null) return;
      const caret = element.selectionStart ?? element.value.length;
      // Accounts and folders insert only their name, so no platform word reaches the server's channel parsing.
      // (`search` starts with the account name for accounts; see picker-items.)
      const label =
        item.kind === 'account' ? item.search?.split('\n')[0] || item.label : item.label;
      const next = insertLabel(element.value, anchor, caret, label);
      element.focus();
      element.setSelectionRange(anchor, caret);
      const native =
        typeof document.execCommand === 'function' &&
        document.execCommand('insertText', false, next.inserted);
      if (!native) {
        element.setRangeText(next.inserted, anchor, caret, 'end');
        element.dispatchEvent(new Event('input', { bubbles: true }));
      }
      setMention((state) => reduceMention(state, { type: 'picked' }));
      setActive(0);
      addReference(item);
    },
    [addReference, mention.anchor]
  );

  const pick = useCallback(
    (item: PickerItem) => {
      if (ime.composing()) {
        queuedPick.current = item; // applied after compositionend; the value is never rewritten mid-composition
        return;
      }
      applyPick(item);
    },
    [applyPick, ime]
  );

  const close = useCallback(() => {
    setMention((state) => reduceMention(state, { type: 'dismiss' }));
    setActive(0);
  }, []);

  const textareaProps = {
    onInput(event: FormEvent<HTMLTextAreaElement>) {
      const native = event.nativeEvent as InputEvent;
      const target = event.currentTarget;
      setMention((state) =>
        reduceMention(state, {
          type: 'input',
          inputType: native.inputType ?? '',
          data: native.data ?? null,
          value: target.value,
          caret: target.selectionStart ?? target.value.length
        })
      );
      setActive(0);
    },
    onSelect(event: SyntheticEvent<HTMLTextAreaElement>) {
      const target = event.currentTarget;
      setMention((state) =>
        reduceMention(state, {
          type: 'selection',
          value: target.value,
          caret: target.selectionStart ?? target.value.length
        })
      );
    },
    onCompositionStart() {
      ime.onCompositionStart();
    },
    onCompositionEnd() {
      ime.onCompositionEnd();
      const queued = queuedPick.current;
      if (queued) {
        queuedPick.current = null;
        setTimeout(() => applyPick(queued), 0);
      }
    },
    /** The list's part of `onKeyDown`, run first; returns true when it handled the key (the caller then skips its own). */
    onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
      const count =
        Math.min(items.length, MENTION_ROWS) + 1 + (items.length > MENTION_ROWS ? 1 : 0);
      return handleMentionKeyDown(event, {
        open: open && items.length > 0,
        active,
        count,
        composing: ime.composing(event),
        onMove: setActive,
        onChoose: (index) => {
          const item = index <= MENTION_ROWS ? items[index - 1] : undefined;
          if (item) pick(item);
          else close(); // "More…" opens the full picker; the ＋ sheet (S26) listens for it
        },
        onClose: close
      });
    }
  };

  const fields = useMemo(
    () => requestFieldsOf(state, { imageGeneration }),
    [state, imageGeneration]
  );
  const blockers = useMemo(() => blockingChips(state), [state]);

  return {
    chips: state.chips,
    removed: state.removed,
    fields,
    /** Keys that `fields` carries: pass to `clearSent` after a successful send. */
    sentKeys: sentKeys(state, { imageGeneration }),
    blockers,
    blockerMessage: blockerMessage(state),
    readingMessage: readingMessage(state),
    imageGenerationNotice:
      imageGeneration && state.chips.length
        ? "Attachments aren't used when generating an image."
        : null,
    readEligible: eligible,
    notice,
    dismissNotice: () => setNotice(null),
    textFile,
    dismissTextFile: () => setTextFile(null),
    recovered,
    persist,
    textareaRef,
    textareaProps,
    ime,
    mention: {
      open: open && items.length > 0,
      listId,
      query: mention.query,
      items,
      active,
      setActive,
      pick,
      close
    },
    addFiles,
    addLibrary,
    addReference,
    connectorItems,
    rememberConnectorItems: (items: readonly ConnectorItemLike[]) =>
      setConnectorItems((current) => {
        const byId = new Map(current.map((item) => [item.referenceId, item]));
        for (const item of items) byId.set(item.referenceId, item);
        return [...byId.values()];
      }),
    setRole,
    remove,
    undo,
    read,
    retry,
    settleReads,
    clearSent
  };
}

export type ComposerAttachments = ReturnType<typeof useComposerAttachments>;
