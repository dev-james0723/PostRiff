import { createBrowserClient } from '@supabase/ssr';
import { ApiError, createApi } from '../web/src/lib/api/client';
import { allows } from '../web/src/lib/auth/permissions';
import {
  clearVideoResume, fingerprintVideo, loadVideoResume, saveVideoResume, uploadResumableVideo
} from '../web/src/lib/api/resumable-upload';
import {
  blankLocation, checkDuration, checkVideoFile, extractFrames, readVideoMetadata, videoPolicyFromCatalog
} from '../web/src/features/agent/attachments/video-file';

const PROJECT_URL = 'https://oxacvkhpfgytkepxcaqh.supabase.co';
const STORAGE_ENDPOINT = 'https://oxacvkhpfgytkepxcaqh.storage.supabase.co/storage/v1/upload/resumable';
const ASSET_ID = /^[a-f0-9]{32}$/;
const UNKNOWN_BEGIN = 'Rafii may have created a pending upload. Check the workspace Library before starting another transfer.';
const ACCOUNT_CHANGED = 'The signed-in account changed. Return to the account that approved this transfer.';
const WORKSPACE_CHANGED = 'The active workspace changed. Return to the workspace that approved this transfer.';

async function connect() {
  const response = await fetch('/api/auth/config', { cache: 'no-store', redirect: 'error' });
  if (!response.ok) throw new Error('Could not read the Rafii connection settings.');
  const config = await response.json();
  if (config.provider !== 'supabase' || config.projectUrl !== PROJECT_URL ||
      typeof config.publishableKey !== 'string' || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(config.publishableKey)) {
    throw new Error('Open the connected staging workspace to save a cut to Library.');
  }
  return createBrowserClient(PROJECT_URL, config.publishableKey, { auth: { experimental: { passkey: true } } }).auth;
}

function selectedWorkspace() {
  const stored = localStorage.getItem('postriff-workspace');
  const cookie = document.cookie.split(';').map(item => item.trim()).find(item => item.startsWith('postriff_workspace='));
  const remembered = cookie ? decodeURIComponent(cookie.slice('postriff_workspace='.length)) : null;
  if (stored && remembered && stored !== remembered) throw new Error('Reopen your workspace and confirm its active selection.');
  return stored || remembered;
}

async function session(auth, expectedUserId) {
  const { data, error } = await auth.getSession();
  if (error || !data?.session?.access_token || !data.session.user?.id) {
    throw new Error('Sign in to the Rafii workspace, then check the destination again.');
  }
  if (expectedUserId && expectedUserId !== data.session.user.id) throw new Error(ACCOUNT_CHANGED);
  return data.session;
}

// The local session supplies credentials. Supabase and the Rafii API independently verify identity.
async function access(auth, expectedUserId, expectedWorkspaceId) {
  const current = await session(auth, expectedUserId);
  const token = current.access_token;
  const api = createApi(async () => token);
  const [identity, me, list] = await Promise.all([auth.getUser(token), api.me(), api.workspaces()]);
  const userId = identity.data?.user?.id;
  if (identity.error || !userId || userId !== current.user.id || me.userId !== userId) throw new Error(ACCOUNT_CHANGED);
  if (me.mfa?.enforced && me.mfa.aal !== 'aal2') throw new Error('Complete two-factor sign-in in your Rafii workspace.');
  await session(auth, userId);
  const selected = selectedWorkspace();
  const workspace = selected ? list.workspaces.find(item => item.workspaceId === selected) : list.workspaces[0];
  if (!workspace?.workspaceId || !workspace.name) throw new Error('Open your Rafii workspace and select the Library destination.');
  if (expectedWorkspaceId && workspace.workspaceId !== expectedWorkspaceId) throw new Error(WORKSPACE_CHANGED);
  if (!workspace.membership || !allows(workspace.membership, 'edit')) throw new Error('This Library requires workspace editing permission.');
  return { token, userId, account: identity.data.user.email || me.displayName || userId, workspaceId: workspace.workspaceId, name: workspace.name };
}

export async function readDestination(auth, expectedUserId) {
  const { token, ...destination } = await access(auth, expectedUserId);
  const catalog = await createApi(async () => token).models();
  const policy = videoPolicyFromCatalog(catalog.attachments?.video);
  if (!policy) throw new Error('Video uploads are unavailable in this workspace.');
  return Object.freeze({ ...destination, policy });
}

function frameData(frame) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ at: frame.at, data: String(reader.result).split(',')[1] });
    reader.onerror = () => reject(new Error('Could not prepare a Library preview.'));
    reader.readAsDataURL(frame.blob);
  });
}

async function prepare(cut, policy) {
  const checked = await checkVideoFile(cut.blob, policy);
  if (!checked.ok || checked.mime !== 'video/mp4') throw new Error(checked.message || 'Export an MP4 from this editor.');
  const metadata = await readVideoMetadata(cut.blob);
  if (!(metadata?.duration > 0) || !(metadata.width > 0) || !(metadata.height > 0)) throw new Error('Could not read the exported video dimensions and duration.');
  const issue = checkDuration(metadata.duration, policy);
  if (issue) throw new Error(issue);
  const { blob, locationCleared } = await blankLocation(cut.blob);
  // Exported blobs have no filesystem timestamp. The same bytes must have the same recovery key after reopening the editor.
  const fingerprint = await fingerprintVideo(blob, { name: 'studio-cut.mp4', lastModified: 0 });
  const frames = await Promise.all((await extractFrames(blob)).map(frameData));
  return { blob, metadata, fingerprint, body: { frames, locationCleared } };
}

// pending belongs to one cut, user and workspace. Retry only the original server intent.
export async function transferCut(cut, destination, pending, { auth, signal, status }) {
  const { workspaceId, userId } = destination;
  const scope = workspaceId + ':' + userId;
  if (pending.scope && pending.scope !== scope) throw new Error('Return to the original account and workspace to resume this cut.');
  pending.scope = scope;
  let beforeRequest;
  async function guardedToken() {
    signal.throwIfAborted();
    const { token } = await access(auth, userId, workspaceId);
    signal.throwIfAborted();
    beforeRequest?.();
    return token;
  }
  const api = createApi(guardedToken);
  await guardedToken();
  status('Preparing MP4 and checking its fingerprint…');
  pending.prepared ??= await prepare(cut, destination.policy);
  const { blob, metadata, body, fingerprint } = pending.prepared;
  const key = 'rafii.studio.transfer.v1:' + scope + ':' + fingerprint;
  const marker = sessionStorage.getItem(key);
  if (marker === 'begin' || pending.unknownBegin) throw new Error(UNKNOWN_BEGIN);
  if (marker?.startsWith('done:') && ASSET_ID.test(marker.slice(5))) {
    return { assetId: marker.slice(5), duration: metadata.duration, previouslySaved: true };
  }
  // Only opaque asset IDs and fingerprints persist. The shared helper stores its signed-session URL separately.
  pending.record ??= loadVideoResume(scope, fingerprint);
  if (marker && !ASSET_ID.test(marker)) throw new Error('Check this transfer in the workspace Library.');
  if (marker && pending.record && marker !== pending.record.assetId) throw new Error('The saved upload references disagree. Check the workspace Library.');
  if (marker && !pending.record) pending.record = { version: 1, assetId: marker, fingerprint, createdAt: Date.now() / 1000 };
  const bytes = blob.size;
  const mime = 'video/mp4';
  let ticket;
  let complete = false;
  const checkpoint = record => { pending.record = record; saveVideoResume(scope, record); };
  if (pending.record) {
    const resumed = await api.resumeVideoUpload(workspaceId, pending.record.assetId, { mime, bytes });
    if (resumed.assetId !== pending.record.assetId) throw new Error('Rafii returned a different pending upload.');
    ticket = resumed.upload;
    complete = resumed.objectComplete === true;
  } else {
    // begin has no idempotency key. Persist uncertainty before the first possible POST.
    beforeRequest = () => { sessionStorage.setItem(key, 'begin'); pending.unknownBegin = true; };
    try {
      const { duration, width, height } = metadata;
      ticket = (await api.beginVideoUpload(workspaceId, { mime, bytes, duration, width, height, transport: 'tus' })).upload;
      if (!ASSET_ID.test(ticket?.assetId || '')) throw new Error(UNKNOWN_BEGIN);
      checkpoint({ version: 1, assetId: ticket.assetId, fingerprint, createdAt: Date.now() / 1000 });
      sessionStorage.setItem(key, ticket.assetId);
      pending.unknownBegin = false;
    } catch (error) {
      if (pending.unknownBegin && error instanceof ApiError && [400, 401, 403, 404, 409, 413, 429].includes(error.status)) {
        sessionStorage.removeItem(key);
        pending.unknownBegin = false;
      }
      if (pending.unknownBegin) throw new Error(UNKNOWN_BEGIN);
      throw error;
    } finally {
      beforeRequest = undefined;
    }
  }
  const assetId = pending.record.assetId;
  if (!complete) {
    const spec = ticket?.resumable;
    if (ticket?.assetId !== assetId || ticket.method !== 'TUS' || spec?.endpoint !== STORAGE_ENDPOINT ||
        spec.metadata?.objectName !== workspaceId + '/video/' + assetId + '.mp4' || spec.metadata.contentType !== mime) {
      throw new Error('Rafii did not return a signed staging upload for this cut.');
    }
    const storageAbort = new AbortController();
    let guardError;
    const stopStorage = error => { guardError = error; storageAbort.abort(); };
    const changedWorkspace = event => {
      if ((event.key === 'postriff-workspace' || event.key === null) && event.newValue !== workspaceId) {
        stopStorage(new Error(WORKSPACE_CHANGED));
      }
    };
    // A signed chunk is already authorized in storage. Stop its in-flight body when the native app switches identity.
    const listener = auth.onAuthStateChange?.((_event, next) => {
      if (next?.user.id !== userId) stopStorage(new Error(ACCOUNT_CHANGED));
    });
    globalThis.addEventListener?.('storage', changedWorkspace);
    try {
      await uploadResumableVideo(ticket, blob, {
        fingerprint, previous: pending.record, signal: AbortSignal.any([signal, storageAbort.signal]), onCheckpoint: checkpoint,
        onProgress: fraction => status('Sending MP4 · ' + Math.round(fraction * 100) + '%'),
        fetcher: async (url, init) => {
          try { await guardedToken(); } catch (error) { stopStorage(error); throw error; }
          return fetch(url, init); // Only the storage signature from the native uploader goes to TUS.
        }
      });
    } catch (error) {
      if (error.code === 'session_expired') checkpoint({ ...pending.record, url: undefined });
      throw guardError || error;
    } finally {
      listener?.data.subscription.unsubscribe();
      globalThis.removeEventListener?.('storage', changedWorkspace);
    }
  }
  status('Verifying the video in Library…');
  const receipt = await api.commitVideoUpload(workspaceId, assetId, body);
  if (receipt.video?.assetId !== assetId || receipt.video?.bytes !== bytes || receipt.video.verified?.container !== true) {
    throw new Error('Rafii could not verify the Library asset.');
  }
  const title = (String(cut.title || '').replace(/[\u0000-\u001f]/g, ' ').trim() || 'Studio cut').slice(0, 160);
  const label = await api.updateLibraryAsset(workspaceId, assetId, { title });
  if (label?.assetId !== assetId && label?.asset?.id !== assetId) throw new Error('Rafii has yet to confirm the saved video title.');
  sessionStorage.setItem(key, 'done:' + assetId);
  clearVideoResume(scope, fingerprint);
  return { assetId, duration: receipt.video.duration ?? metadata.duration };
}

function workspaceLink(label, href) {
  const link = document.createElement('a');
  link.className = 'workspace-link';
  link.textContent = label;
  link.href = href;
  link.target = '_blank';
  link.rel = 'noopener';
  return link;
}

function mount(panel) {
  let active;
  function invalidate() {
    active?.controller.abort();
    active = null;
    panel.replaceChildren();
  }
  document.addEventListener('rafii:cut-invalidated', invalidate);
  document.addEventListener('rafii:cut-ready', event => {
    const cut = event.detail;
    if (!(cut?.blob instanceof Blob) || !cut.blob.size || cut.blob.type !== 'video/mp4') { invalidate(); return; }
    if (active?.cut.blob === cut.blob && active.cut.title === cut.title) return;
    invalidate();
    const state = { cut, controller: new AbortController(), pending: {} };
    active = state;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Check Library destination';
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.append(button, workspaceLink('Open Rafii workspace', '/app/creative?workspace=1'));
    const message = document.createElement('p');
    message.className = 'muted';
    message.setAttribute('role', 'status');
    const status = text => { if (active === state) message.textContent = text; };
    panel.append(actions, message);
    button.addEventListener('click', async () => {
      if (button.disabled || active !== state) return;
      button.disabled = true;
      try {
        if (!state.destination) {
          status('Checking the active workspace…');
          state.auth ??= await connect();
          const destination = await readDestination(state.auth);
          if (active !== state) return;
          state.destination = destination;
          button.textContent = 'Save MP4 to ' + destination.name;
          status('Signed in as ' + destination.account + '. Saving will upload “' + (cut.title || 'Studio cut') +
            '” to the staging Library for ' + destination.name + ' (' + destination.workspaceId + ').');
        } else {
          const result = await transferCut(cut, state.destination, state.pending, {
            auth: state.auth, signal: state.controller.signal, status
          });
          if (active !== state) return;
          actions.replaceChildren(workspaceLink('Open Library', '/app/library'));
          if (result.duration <= 90) {
            actions.prepend(workspaceLink('Use as a Creative Studio reference', '/app/creative?reference=' + encodeURIComponent(result.assetId)));
          }
          const saved = result.previouslySaved ? 'This cut was previously saved to ' : 'Saved to ';
          status(saved + state.destination.name + ' Library.' + (result.duration > 90 ? ' Creative Studio references can be up to 90 seconds.' : ''));
        }
      } catch (error) {
        if (active !== state) return;
        status(error.message || 'Could not complete the Library transfer.');
        if (state.pending.unknownBegin || error.message === UNKNOWN_BEGIN) {
          actions.replaceChildren(workspaceLink('Check Library', '/app/library'));
        } else if (state.destination) {
          button.textContent = 'Retry save to ' + state.destination.name;
        }
      } finally {
        if (active === state) button.disabled = false;
      }
    });
  });
}

const panel = typeof document === 'object' && document.getElementById('workspace-transfer');
if (panel) mount(panel);
