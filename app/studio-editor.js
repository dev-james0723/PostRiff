// The editor owns edit decisions and temporary file handles. Rafii's media
// worker measures the reference and produces the same MP4 for preview/export.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const MAX_FILE = 16 * 1024 * 1024;
  const SESSION_KEY = 'rafii.local-video-edit.v1';
  const FORMAT = 'rafii-local-edit-v1';
  const aspects = ['9:16', '16:9', '1:1'];
  const uploadId = /^upload-[a-f0-9]{64}$/;
  const seconds = ms => String(Number((ms / 1000).toFixed(3)));
  const fileStem = name => name.replace(/[^\p{L}\p{N} _-]+/gu, '').trim() || 'Rafii cut';
  const total = scenes => scenes.reduce((sum, scene) => sum + scene.durationMs, 0);
  const clipFor = id => project.clips.find(c => c.clipId === id);
  const scene = () => project.scenes[selected];
  const uploads = new Map();
  const bundled = new Map();
  const audioFiles = new Map();
  const undoStack = [];
  let project = blank();
  let selected = 0;
  let referenceFile = null;
  let authorizedReference = null;
  let sheet = null;
  let frameIndex = 0;
  let rendered = null;
  let currentView = '';
  let sceneDirty = false;
  let briefDirty = false;
  let relinkId = null;
  let busy = false;

  function blank() {
    return { format: FORMAT, name: 'Untitled cut', aspectRatio: '9:16', revision: 1,
      brief: '', brand: '', subject: '', audience: '', clips: [], scenes: [], reference: null, soundtrack: null };
  }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function notice(message, error = false) {
    $('notice').textContent = message;
    $('notice').classList.toggle('error', error);
  }
  async function api(action, payload = {}) {
    const response = await fetch('/studio-api/' + action, {
      method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.message || detail.error?.message || 'Studio could not complete this action.');
    }
    if (action === 'render') {
      if (!response.headers.get('Content-Type')?.startsWith('video/mp4')) throw new Error('Studio returned an unreadable export.');
      const blob = await response.blob();
      if (!blob.size) throw new Error('Studio returned an empty export.');
      return blob;
    }
    return response.json();
  }
  function asBase64(file) {
    if (!file || !file.size || file.size > MAX_FILE) throw new Error('Choose a video under 16 MiB.');
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('This file could not be read. Select it again.'));
      reader.onload = () => resolve(reader.result.split(',', 2)[1]);
      reader.readAsDataURL(file);
    });
  }
  function listen(id, type, work) {
    $(id).addEventListener(type, async event => {
      event.preventDefault();
      if (busy) return;
      try { await work(event); } catch (error) { notice(error.message || 'The action could not be completed.', true); }
    });
  }
  async function working(message, fn) {
    busy = true;
    const regions = [$('project-actions'), document.querySelector('.desk'), document.querySelector('footer')];
    regions.forEach(n => { n.inert = true; });
    notice(message);
    try { await fn(); } finally { regions.forEach(n => { n.inert = false; }); busy = false; }
  }
  function saveSession() {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(project)); } catch {
      notice('Browser session saving is unavailable. Use Save project to keep a copy.');
    }
  }
  function clearRender() {
    if (rendered) {
      URL.revokeObjectURL(rendered.url);
      if (rendered.captions) URL.revokeObjectURL(rendered.captions);
    }
    rendered = null;
    document.dispatchEvent(new CustomEvent('rafii:cut-invalidated'));
  }
  function change(next) {
    undoStack.push(project);
    if (undoStack.length > 20) undoStack.shift();
    project = { ...next, revision: project.revision + 1 };
    clearRender();
    saveSession();
  }
  function dropFiles() {
    for (const { url } of uploads.values()) URL.revokeObjectURL(url);
    uploads.clear();
    audioFiles.clear();
    currentView = '';
    $('audio-form').reset();
    referenceFile = null;
    authorizedReference = null;
    sheet = null;
    $('frames-coverage').value = 'scenes';
    clearRender();
    setRelink(null);
    $('reference-form').reset();
    selectReference();
    $('import-form').reset();
  }
  function openProject(next, initial = false) {
    dropFiles();
    undoStack.length = 0;
    project = next;
    selected = 0;
    sceneDirty = briefDirty = false;
    refresh();
    if (!initial) saveSession();
  }

  function validString(value, max, needed = false) {
    return typeof value === 'string' && value.length <= max && (!needed || value.trim().length > 0);
  }
  function integer(value, min, max) {
    return Number.isSafeInteger(value) && value >= min && value <= max;
  }
  function validateProject(value) {
    const bad = () => { throw new Error('Choose a valid Rafii local project file.'); };
    if (!value || value.format !== FORMAT || !validString(value.name, 120, true) || !aspects.includes(value.aspectRatio)
        || !integer(value.revision, 1, Number.MAX_SAFE_INTEGER - 1)
        || !Array.isArray(value.clips) || value.clips.length > 128
        || !Array.isArray(value.scenes) || value.scenes.length > 32) bad();
    const result = { ...blank(), name: value.name, aspectRatio: value.aspectRatio, revision: value.revision };
    for (const [key, max] of Object.entries({ brief: 1200, brand: 120, audience: 160, subject: 120 })) {
      if (!validString(value[key], max)) bad();
      result[key] = value[key];
    }
    const clips = new Set();
    for (const item of value.clips) {
      if (!item || !validString(item.clipId, 100, true) || clips.has(item.clipId)) bad();
      if (bundled.has(item.clipId)) result.clips.push(bundled.get(item.clipId));
      else {
        if (!uploadId.test(item.clipId) || !validString(item.name, 240, true) || !integer(item.durationMs, 1, 90000)) bad();
        result.clips.push({ clipId: item.clipId, name: item.name, durationMs: item.durationMs });
      }
      clips.add(item.clipId);
    }
    const ids = new Set();
    for (const item of value.scenes) {
      if (!item || !validString(item.sceneId, 128, true) || ids.has(item.sceneId)
          || !validString(item.name, 90, true) || !validString(item.caption, 120)
          || !validString(item.direction, 600) || !integer(item.trimStartMs, 0, 89999)
          || !integer(item.durationMs, 42, 8000) || !(item.clipId === null || clips.has(item.clipId))) bad();
      ids.add(item.sceneId);
      const span = item.referenceSpan;
      if (span != null && (!/^[a-f0-9]{64}$/.test(span.sha256) || !integer(span.startMs, 0, 89999)
          || !integer(span.endMs, span.startMs + 1, 90000))) bad();
      result.scenes.push({ sceneId: item.sceneId, name: item.name, direction: item.direction, caption: item.caption,
        trimStartMs: item.trimStartMs, durationMs: item.durationMs, clipId: item.clipId,
        ...(span ? { referenceSpan: { sha256: span.sha256, startMs: span.startMs, endMs: span.endMs } } : {}) });
    }
    if (total(result.scenes) > 90000) bad();
    if (value.soundtrack != null) {
      const a = value.soundtrack;
      if (!a || typeof a.audioId !== 'string' || !/^audio-[0-9a-f]{64}$/.test(a.audioId)
          || !validString(a.name, 240, true) || !integer(a.durationMs, 1, 90000)) bad();
      result.soundtrack = { audioId: a.audioId, name: a.name, durationMs: a.durationMs };
    }
    if (value.reference != null) {
      const r = value.reference;
      if (!r || !['file', 'sample'].includes(r.kind) || !validString(r.name, 240, true)
          || !/^[0-9a-f]{64}$/.test(r.sha256) || !integer(r.durationMs, 1, 90000)
          || !integer(r.width, 1, 32768) || !integer(r.height, 1, 32768) || !Array.isArray(r.shots)
          || r.shots.length > 720 || !r.shots.every(s => s && integer(s.startMs, 0, r.durationMs)
            && integer(s.endMs, s.startMs + 1, r.durationMs) && validString(s.note, 600))) bad();
      const observations = r.observations ?? [];
      if (!Array.isArray(observations) || observations.length > 12 || !observations.every(note => validString(note, 600))) bad();
      result.reference = { kind: r.kind, name: r.name, sha256: r.sha256, durationMs: r.durationMs,
        width: r.width, height: r.height, observations, shots: r.shots.map(s => ({startMs: s.startMs, endMs: s.endMs, note: s.note})) };
    }
    return result;
  }
  function newScene(item = {}) {
    return { sceneId: item.sceneId || crypto.randomUUID(), name: (item.name || item.purpose || 'New scene').slice(0, 90),
      direction: item.direction || '', caption: item.caption || '', trimStartMs: item.trimStartMs || 0,
      durationMs: item.durationMs ?? 2000, clipId: item.clipId || null };
  }
  function panel(id) {
    document.querySelectorAll('[data-panel]').forEach(button => {
      const active = button.dataset.panel === id;
      button.setAttribute('aria-pressed', String(active));
      $(button.getAttribute('aria-controls')).hidden = !active;
    });
  }
  function setPlayer(url, key, mode, detail, poster) {
    const player = $('player');
    if (currentView !== key) {
      player.pause();
      player.replaceChildren();
      player.removeAttribute('poster');
      if (poster) player.poster = poster;
      if (url) player.src = url;
      else player.removeAttribute('src');
      currentView = key;
      player.load();
    }
    player.hidden = !url;
    $('empty-preview').hidden = !!url;
    $('monitor-mode').textContent = mode;
    $('monitor-detail').textContent = detail;
  }
  function previewScene() {
    const shot = scene();
    if (!shot) {
      setPlayer(null, 'empty', 'No scenes', 'Add a scene or build a shot plan.');
      return;
    }
    const clip = clipFor(shot.clipId);
    const url = bundled.has(shot.clipId) ? '/studio-clips/' + encodeURIComponent(shot.clipId) : uploads.get(shot.clipId)?.url;
    setPlayer(url, 'source/' + project.revision + '/' + shot.sceneId, 'Source footage',
      clip ? clip.name + ' · ' + seconds(shot.trimStartMs) + '–' + seconds(shot.trimStartMs + shot.durationMs) + ' s'
        : 'Choose a production clip for this scene.');
    $('empty-preview').textContent = clip ? 'Relink this clip in Media to preview the scene.' : 'Assign production footage to preview this scene.';
  }
  $('player').addEventListener('loadedmetadata', () => {
    if (currentView.startsWith('source/') && scene()) $('player').currentTime = scene().trimStartMs / 1000;
  });
  $('player').addEventListener('play', () => {
    if (!currentView.startsWith('source/') || !scene()) return;
    const start = scene().trimStartMs / 1000;
    if ($('player').currentTime < start || $('player').currentTime >= start + scene().durationMs / 1000 - 0.01) $('player').currentTime = start;
  });
  $('player').addEventListener('timeupdate', () => {
    if (currentView.startsWith('source/') && scene() && !$('player').paused
        && $('player').currentTime >= (scene().trimStartMs + scene().durationMs) / 1000) $('player').pause();
  });
  function available(clipId) { return bundled.has(clipId) || uploads.has(clipId); }
  function refresh() {
    selected = Math.max(0, Math.min(selected, project.scenes.length - 1));
    $('heading').textContent = project.name;
    $('project-kind').textContent = 'Local project';
    const duration = seconds(total(project.scenes)) + ' s';
    $('project-meta').textContent = [project.aspectRatio, project.scenes.length + (project.scenes.length === 1 ? ' scene' : ' scenes'), duration,
      'Revision ' + project.revision].join(' · ');
    $('duration').textContent = duration;
    $('undo').disabled = !undoStack.length;
    $('add').disabled = project.scenes.length >= 32 || total(project.scenes) + 42 > 90000;
    const ready = project.scenes.length > 0 && project.scenes.every(s => available(s.clipId))
      && (!project.soundtrack || audioFiles.has(project.soundtrack.audioId));
    $('preview').disabled = $('export').disabled = !ready;
    $('export').title = ready ? 'Download the current cut' : 'Assign and relink every scene’s footage before export';
    $('timeline').replaceChildren();
    let start = 0;
    project.scenes.forEach((s, i) => {
      const li = element('li');
      const button = element('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(i === selected));
      button.append(element('span', String(i + 1).padStart(2, '0'), 'scene-index'),
        element('strong', s.name), element('span', seconds(start) + '–' + seconds(start + s.durationMs) + ' s', 'timecode'),
        element('small', available(s.clipId) ? (s.caption || clipFor(s.clipId).name) : s.clipId ? 'Relink footage in Media' : 'Footage needed'));
      button.addEventListener('click', () => { if (!applyDrafts()) return; selected = i; refresh(); panel('scene'); });
      li.append(button);
      $('timeline').append(li);
      start += s.durationMs;
    });
    $('empty-timeline').hidden = !!project.scenes.length;
    const s = scene();
    $('no-scene').hidden = !!s;
    $('scene-form').hidden = !s;
    $('scene-kicker').textContent = s ? 'Scene ' + String(selected + 1).padStart(2, '0') : 'Timeline';
    $('scene-error').hidden = true;
    const select = $('scene-clip');
    select.replaceChildren(new Option('Choose footage…', ''));
    for (const clip of project.clips) select.add(new Option(clip.name + ' · ' + seconds(clip.durationMs) + ' s', clip.clipId));
    if (s) {
      $('scene-name').value = s.name; select.value = s.clipId || '';
      $('trim').value = seconds(s.trimStartMs); $('length').value = seconds(s.durationMs);
      $('caption').value = s.caption; $('direction').value = s.direction;
    }
    $('earlier').disabled = !selected;
    $('later').disabled = selected >= project.scenes.length - 1;
    $('project-name').value = project.name; $('aspect').value = project.aspectRatio;
    for (const key of ['brief', 'brand', 'subject', 'audience']) $(key).value = project[key];
    showMedia();
    previewScene();
  }
  function setRelink(id) {
    relinkId = id;
    $('import').textContent = id ? 'Relink selected footage' : 'Import footage';
    $('relink-note').hidden = !id;
    $('relink-target').textContent = id ? clipFor(id)?.name || '' : '';
  }
  function showMedia() {
    $('library').replaceChildren();
    for (const clip of project.clips) {
      const li = element('li');
      li.append(element('span', clip.name), element('small', seconds(clip.durationMs) + ' s'));
      if (!available(clip.clipId)) {
        const link = element('button', 'Relink', 'quiet');
        link.type = 'button';
        link.addEventListener('click', () => { setRelink(clip.clipId); $('production-file').click(); });
        li.append(link);
      }
      $('library').append(li);
    }
    const soundtrack = project.soundtrack;
    const needsAudio = soundtrack && !audioFiles.has(soundtrack.audioId);
    $('audio-status').textContent = soundtrack ? soundtrack.name + ' · ' + seconds(soundtrack.durationMs)
      + (needsAudio ? ' s · Relink the original audio file' : ' s') : 'Using production audio';
    $('audio-add').textContent = needsAudio ? 'Relink audio' : soundtrack ? 'Replace audio' : 'Use audio';
    $('audio-remove').hidden = !soundtrack;
    const r = project.reference;
    const signals = $('signals');
    signals.replaceChildren();
    signals.hidden = !r;
    if (r) {
      signals.append(element('h3', 'Reference timing'), element('p', r.name + ' · ' + r.width + ' × ' + r.height + ' · ' + seconds(r.durationMs) + ' s'),
        element('p', r.shots.length + ' estimated shot' + (r.shots.length === 1 ? '' : 's')));
      const list = element('ol');
      for (const shot of r.shots) list.append(element('li', seconds(shot.startMs) + '–' + seconds(shot.endMs) + ' s · ' + shot.note));
      signals.append(list);
      if (r.observations?.length) {
        const details = element('details');
        const measurements = element('ul');
        for (const observation of r.observations) measurements.append(element('li', observation));
        details.append(element('summary', 'Audio, captions and visual cues'), measurements);
        signals.append(details);
      }
    }
    const linked = hasAuthorizedReference();
    drawSheet();
    $('blueprint').disabled = !linked;
    $('blueprint-help').textContent = linked ? 'Use the measured timing and your brief to plan original footage.'
      : r ? 'Select and analyze your reference again to generate another blueprint.' : 'Analyze a reference in Media to plan your shots.';
  }
  function applyDrafts() {
    if (!sceneDirty && !briefDirty) return true;
    let next = { ...project };
    if (sceneDirty && scene()) {
      panel('scene');
      if (!$('scene-form').reportValidity()) return false;
      const clip = clipFor($('scene-clip').value);
      const trim = Math.round($('trim').valueAsNumber * 1000);
      const length = Math.round($('length').valueAsNumber * 1000);
      let error = '';
      if (!$('scene-name').value.trim()) error = 'Give this scene a name.';
      else if (clip && trim + length > clip.durationMs) error = 'This trim extends beyond the production clip.';
      else if (total(project.scenes) - scene().durationMs + length > 90000) error = 'Keep the complete cut within 90 seconds.';
      if (error) { $('scene-error').textContent = error; $('scene-error').hidden = false; return false; }
      next.scenes = project.scenes.map((s, i) => i !== selected ? s : { ...s, name: $('scene-name').value.trim(),
        clipId: clip?.clipId || null, trimStartMs: trim, durationMs: length, caption: $('caption').value, direction: $('direction').value });
    }
    if (briefDirty) {
      panel('blueprint');
      if (!$('brief-form').reportValidity()) return false;
      next.name = $('project-name').value.trim();
      if (!next.name) { notice('Give the project a name.', true); return false; }
      next.aspectRatio = $('aspect').value;
      for (const key of ['brief', 'brand', 'subject', 'audience']) next[key] = $(key).value.trim();
    }
    sceneDirty = briefDirty = false;
    change(next);
    refresh();
    return true;
  }
  $('scene-form').addEventListener('input', () => { sceneDirty = true; clearRender(); });
  $('brief-form').addEventListener('input', () => { briefDirty = true; clearRender(); });
  listen('scene-form', 'submit', () => { if (applyDrafts()) notice('Scene changes applied.'); });
  listen('brief-form', 'submit', () => { if (applyDrafts()) notice('Project details saved in this tab.'); });
  document.querySelectorAll('[data-panel]').forEach(b => b.addEventListener('click', () => { if (applyDrafts()) panel(b.dataset.panel); }));
  listen('new', 'click', () => {
    if (!confirm('Start a new project in this tab? Save the current project first to keep a separate copy.')) return;
    openProject(blank()); panel('media'); notice('Import production footage or analyze a reference to begin.');
  });
  listen('add', 'click', () => {
    if (!applyDrafts()) return;
    const durationMs = Math.min(2000, 90000 - total(project.scenes));
    if (durationMs < 42 || project.scenes.length >= 32) return;
    selected = project.scenes.length;
    change({ ...project, scenes: [...project.scenes, newScene({ name: 'Scene ' + (selected + 1), durationMs })] });
    refresh(); panel('scene'); $('scene-name').focus();
  });
  for (const [id, delta] of [['earlier', -1], ['later', 1]]) {
    listen(id, 'click', () => {
      if (!applyDrafts()) return;
      const scenes = project.scenes.slice();
      const [item] = scenes.splice(selected, 1);
      selected += delta; scenes.splice(selected, 0, item);
      change({ ...project, scenes }); refresh(); notice('Scene order updated.');
    });
  }
  listen('remove', 'click', () => {
    if (!applyDrafts()) return;
    change({ ...project, scenes: project.scenes.filter((_, i) => i !== selected) }); refresh(); notice('Scene removed. Undo restores it.');
  });
  listen('undo', 'click', () => {
    if (!applyDrafts()) return;
    const prev = undoStack.pop();
    if (!prev) return;
    if (prev.reference?.sha256 !== project.reference?.sha256) { referenceFile = null; authorizedReference = null; }
    project = { ...prev, revision: project.revision + 1 };
    clearRender(); setRelink(null); saveSession(); refresh(); notice('Previous edit restored.');
  });
  function download(url, name) {
    const a = element('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
  }
  listen('save', 'click', () => {
    if (!applyDrafts()) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' }));
    download(url, fileStem(project.name) + '.rafii.json'); setTimeout(() => URL.revokeObjectURL(url), 30000);
    notice('Project file exported. Keep your production files to relink them when reopening.');
  });
  listen('open', 'click', () => $('open-file').click());
  listen('open-file', 'change', async () => {
    const file = $('open-file').files[0]; $('open-file').value = '';
    if (!file) return;
    if (file.size > 1024 * 1024) throw new Error('Choose a Rafii project file under 1 MiB.');
    await working('Opening project…', async () => {
      const next = validateProject(JSON.parse(await file.text()));
      if (!confirm('Open this project in the current tab? Save your current edit first to keep a separate copy.')) { notice('Kept the current edit.'); return; }
      openProject(next); panel(next.clips.some(c => !available(c.clipId)) ? 'media' : 'scene');
      notice('Opened ' + next.name + '.');
    });
  });
  listen('clear', 'click', () => {
    if (!confirm('Clear the project and imported media from this tab? Downloaded files are kept.')) return;
    openProject(blank(), true);
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* Storage may be disabled. */ }
    panel('media'); notice('Session cleared.');
  });
  listen('relink-cancel', 'click', () => { setRelink(null); $('import-form').reset(); });
  listen('import-form', 'submit', async () => {
    if (!applyDrafts()) return;
    if (!$('production-rights').checked) throw new Error('Confirm your permission to edit this footage.');
    const file = $('production-file').files[0];
    await working('Checking production footage…', async () => {
      const data = await api('inspect', { rightsConfirmed: true, file: await asBase64(file) });
      if (!uploadId.test(data.clipId) || !integer(data.durationMs, 1, 90000)) throw new Error('Could not identify the production clip.');
      if (relinkId && relinkId !== data.clipId) throw new Error('This file differs from the saved clip. Select the original file to relink it.');
      const existing = clipFor(data.clipId);
      if (!existing && project.clips.length >= 128) throw new Error('This project already has 128 clips.');
      const updated = { clipId: data.clipId, name: existing?.name || file.name.slice(0, 240), durationMs: data.durationMs };
      const previous = uploads.get(data.clipId);
      if (previous) URL.revokeObjectURL(previous.url);
      uploads.set(data.clipId, { file, url: URL.createObjectURL(file) });
      if (!existing || existing.durationMs !== data.durationMs) change({ ...project,
        clips: existing ? project.clips.map(c => c.clipId === data.clipId ? updated : c) : [...project.clips, updated] });
      setRelink(null); $('import-form').reset(); currentView = ''; refresh(); panel('media');
      notice(existing ? 'Original footage relinked.' : 'Footage imported. Assign it to a scene in the timeline.');
    });
  });
  listen('audio-form', 'submit', async () => {
    if (!applyDrafts()) return;
    if (!$('audio-rights').checked) throw new Error('Confirm your permission to export this audio.');
    const file = $('audio-file').files[0];
    await working('Checking soundtrack…', async () => {
      const info = await api('inspect-audio', { rightsConfirmed: true, file: await asBase64(file) });
      if (!/^audio-[a-f0-9]{64}$/.test(info.audioId) || !integer(info.durationMs, 1, 90000)) throw new Error('Could not identify the soundtrack.');
      const old = project.soundtrack;
      if (old && !audioFiles.has(old.audioId) && old.audioId !== info.audioId)
        throw new Error('This file differs from the saved audio. Select the original, or remove it before choosing a replacement.');
      audioFiles.clear();
      audioFiles.set(info.audioId, file);
      change({ ...project, soundtrack: { audioId: info.audioId, name: file.name.slice(0, 240), durationMs: info.durationMs } });
      $('audio-form').reset(); refresh(); panel('media'); notice('Soundtrack ready for the complete cut.');
    });
  });
  listen('audio-remove', 'click', () => {
    if (!applyDrafts()) return;
    change({ ...project, soundtrack: null }); $('audio-form').reset(); refresh(); panel('media'); notice('Using the original scene audio.');
  });
  function selectReference() {
    const file = $('reference-source').value === 'file';
    $('reference-file-label').hidden = !file; $('reference-file').required = file;
  }
  function hasAuthorizedReference() {
    const r = project.reference;
    return !!(r && $('reference-rights').checked && r.sha256 === authorizedReference
      && $('reference-source').value === r.kind
      && (r.kind === 'sample' || (referenceFile && $('reference-file').files[0] === referenceFile)));
  }
  function forgetReferenceSelection() {
    referenceFile = authorizedReference = sheet = null;
    $('reference-rights').checked = false;
    showMedia();
  }
  $('reference-source').addEventListener('change', () => { selectReference(); forgetReferenceSelection(); });
  $('reference-file').addEventListener('change', forgetReferenceSelection);
  $('reference-rights').addEventListener('change', () => {
    if (!$('reference-rights').checked) forgetReferenceSelection();
  });

  function drawSheet() {
    const linked = hasAuthorizedReference();
    if (!linked || sheet?.referenceSha256 !== project.reference?.sha256 || sheet?.coverage !== frameCoverage()) sheet = null;
    $('frames-coverage').disabled = !linked;
    $('contact-sheet').hidden = !project.reference;
    $('frames-toggle').disabled = !linked;
    $('frames-toggle').title = linked ? '' : 'Analyze the selected reference with permission to view its frames.';
    $('frames-toggle').textContent = sheet ? 'Hide frames' : 'Show frames';
    $('frames-toggle').setAttribute('aria-expanded', String(!!sheet));
    $('frames-content').hidden = !sheet;
    $('frame-options').replaceChildren();
    const image = $('frame-image');
    image.removeAttribute('src');
    image.hidden = true;
    if (!sheet) return;
    const frameLabel = f => sheet.coverage === 'intervals' ? 'Interval ' + (f.intervalIndex + 1) : 'Shot ' + (f.shotIndex + 1);
    sheet.frames.forEach((frame, i) => {
      const button = element('button', frameLabel(frame));
      button.type = 'button'; button.setAttribute('aria-pressed', String(i === frameIndex));
      if (frame.jpeg) {
        const thumb = element('img');
        thumb.alt = ''; thumb.src = 'data:image/jpeg;base64,' + frame.jpeg;
        button.append(thumb);
      }
      button.addEventListener('click', () => { frameIndex = i; drawSheet(); $('frame-options').children[i].focus(); });
      $('frame-options').append(button);
    });
    const f = sheet.frames[frameIndex];
    if (f.jpeg) {
      image.src = 'data:image/jpeg;base64,' + f.jpeg; image.hidden = false;
      image.alt = frameLabel(f) + ' of the reference at ' + seconds(f.timeMs) + ' seconds';
    }
    $('frame-caption').textContent = frameLabel(f) + ' · ' + seconds(f.startMs) + '–' + seconds(f.endMs) + ' s · '
      + (f.jpeg ? 'Decoded frame at ' + seconds(f.timeMs) + ' s' : 'No frame decoded within this interval');
    // A time interval may cross several cuts. Link the decoded picture's PTS
    // to a unique plan span from these same reference bytes.
    const proposals = !f.jpeg || !integer(f.timeMs, f.startMs, f.endMs - 1) ? [] : project.scenes.filter(s =>
      s.referenceSpan?.sha256 === sheet.referenceSha256 && s.referenceSpan.startMs <= f.timeMs && f.timeMs < s.referenceSpan.endMs);
    const direction = proposals.length === 1 ? proposals[0].direction : '';
    $('frame-direction').hidden = !direction;
    $('frame-direction').textContent = direction ? 'Proposed shot direction · ' + direction : '';
    $('frame-paging').hidden = sheet.pageCount < 2;
    $('frames-prev').disabled = sheet.page === 0;
    $('frames-next').disabled = sheet.page + 1 >= sheet.pageCount;
    $('frames-page').textContent = 'Page ' + (sheet.page + 1) + ' of ' + sheet.pageCount;
  }
  function frameCoverage() {
    return $('frames-coverage').value === 'intervals' ? 'intervals' : 'scenes';
  }
  listen('frames-coverage', 'change', async () => {
    if (!sheet) return;
    sheet = null;
    drawSheet();
    await loadSheet(0);
  });
  async function loadSheet(page) {
    if (!hasAuthorizedReference()) throw new Error('Select and analyze your reference with permission first.');
    const r = project.reference;
    const coverage = frameCoverage();
    await working('Reading reference frames…', async () => {
      const data = await api('reference-frames', { rightsConfirmed: true, referenceSha256: r.sha256, page, coverage,
        ...(r.kind === 'file' ? { file: await asBase64(referenceFile) } : {}) });
      if (!hasAuthorizedReference() || data.referenceSha256 !== authorizedReference || data.page !== page
          || coverage !== frameCoverage() || data.coverage !== coverage
          || !integer(data.pageCount, 1, 720) || page >= data.pageCount || !Array.isArray(data.frames)
          || !data.frames.length || data.frames.length > 4) throw new Error('No matching reference frame page was available.');
      sheet = data; frameIndex = 0; drawSheet(); notice('');
    });
  }
  listen('frames-toggle', 'click', async () => {
    if (sheet) { sheet = null; drawSheet(); return; }
    await loadSheet(0);
  });
  listen('frames-prev', 'click', () => sheet && sheet.page > 0 && loadSheet(sheet.page - 1));
  listen('frames-next', 'click', () => sheet && sheet.page + 1 < sheet.pageCount && loadSheet(sheet.page + 1));

  function observationsFrom(result) {
    const notes = [];
    const measurements = result.measured || {};
    if (measurements.sampleIntervalMs) notes.push('Shot timing is estimated from frames sampled every ' + measurements.sampleIntervalMs + ' ms.');
    const captions = measurements.embeddedCaptions;
    if (captions?.state === 'no_embedded_track') notes.push('No embedded caption track detected.');
    else if (Array.isArray(captions?.cues)) notes.push(captions.cues.length + ' embedded caption cues measured.');
    const rhythm = measurements.audioRhythm;
    if (rhythm?.state === 'measured') notes.push(rhythm.onsetMs.length + ' volume rises measured in the soundtrack.'
      + (rhythm.medianSpacingMs != null ? ' Median spacing ' + seconds(rhythm.medianSpacingMs) + ' s.' : ''));
    else notes.push(result.hasAudio ? 'Audio present. Rhythm measurements unavailable.' : 'No audio stream detected.');
    const overlay = result.overlaySignals;
    if (Array.isArray(overlay?.frames) && overlay.state !== 'unavailable') {
      const withText = overlay.frames.filter(f => f.wordCount > 0);
      notes.push('English text detected in ' + withText.length + ' of ' + overlay.frames.length + ' sampled frames.');
      const regions = [...new Set(withText.map(f => f.verticalRegion).filter(Boolean))];
      if (regions.length) notes.push('Observed text placement in the ' + regions.join(', ') + ' third of the frame.');
    } else notes.push('On-screen text recognition unavailable for this reference.');
    return notes;
  }
  listen('reference-form', 'submit', async () => {
    if (!applyDrafts()) return;
    if (!$('reference-rights').checked) throw new Error('Confirm your permission to analyze this reference.');
    const kind = $('reference-source').value;
    const file = kind === 'file' ? $('reference-file').files[0] : null;
    await working('Measuring reference timing…', async () => {
      const result = await api('analyze', { rightsConfirmed: true, ...(kind === 'file' ? { file: await asBase64(file) } : {}) });
      const reference = { kind, name: file?.name.slice(0, 240) || 'Bundled timer reference', sha256: result.sha256,
        durationMs: result.durationMs, width: result.width, height: result.height, observations: observationsFrom(result),
        shots: result.scenes.map(s => ({ startMs: s.startMs, endMs: s.endMs, note: s.interpretation || 'Estimated shot boundary' })) };
      sheet = null;
      referenceFile = file;
      authorizedReference = result.sha256;
      change({ ...project, reference }); refresh(); panel('media');
      notice('Reference timing is ready. Open Blueprint to plan an original cut.');
    });
  });
  listen('blueprint', 'click', async () => {
    if (!applyDrafts()) return;
    if (!project.brief) { $('brief').focus(); throw new Error('Add a creative brief before generating your shot plan.'); }
    if (project.scenes.length && !confirm('Replace the current timeline with a new shot plan? Your production clips will stay in Media.')) return;
    const r = project.reference;
    if (!hasAuthorizedReference()) throw new Error('Analyze your reference again to build a shot plan.');
    await working('Building the shot plan…', async () => {
      const plan = await api('blueprint', { rightsConfirmed: true, brief: project.brief, brand: project.brand, subject: project.subject,
        audience: project.audience, referenceSha256: r.sha256, ...(r.kind === 'file' ? { file: await asBase64(referenceFile) } : {}) });
      if (plan.referenceSha256 !== r.sha256 || !Array.isArray(plan.scenes) || !plan.scenes.length) throw new Error('The reference changed. Analyze it again.');
      selected = 0;
      change({ ...project, scenes: plan.scenes.map(shot => ({ ...newScene(shot),
        referenceSpan: { sha256: r.sha256, startMs: shot.sourceStartMs, endMs: shot.sourceEndMs } })) });
      refresh(); panel('scene');
      notice('Shot plan ready. Assign production footage to each scene before exporting.');
    });
  });
  // Browsers vary in their support for timed text inside MP4. Mirror the
  // native renderer's cumulative 24 fps frame boundaries for the web player.
  function captionTrack(scenes) {
    const cues = [];
    let elapsed = 0;
    function time(ms) {
      const frameMs = Math.round(Math.round(ms * 24 / 1000) * 1000 / 24);
      return new Date(frameMs).toISOString().slice(11, 23);
    }
    for (const shot of scenes) {
      const start = elapsed;
      elapsed += shot.durationMs;
      const text = shot.caption.trim().replace(/\s+/g, ' ')
        .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
      if (text) cues.push(time(start) + ' --> ' + time(elapsed) + '\n' + text);
    }
    return cues.length ? URL.createObjectURL(new Blob(['WEBVTT\n\n' + cues.join('\n\n') + '\n'], { type: 'text/vtt' })) : null;
  }
  async function cut(exportFile) {
    if (!applyDrafts()) return;
    await working('Rendering the current cut…', async () => {
      if (!rendered) {
        const files = {};
        const used = new Set(project.scenes.map(s => s.clipId));
        const audio = project.soundtrack ? audioFiles.get(project.soundtrack.audioId) : null;
        if (project.soundtrack && !audio) throw new Error('Relink your soundtrack in Media or remove it from the cut.');
        const uploadBytes = [...used].reduce((sum, id) => sum + (uploads.get(id)?.file.size || 0), audio?.size || 0);
        if (uploadBytes > 32 * 1024 * 1024) throw new Error('Trim your source files before importing. This local render accepts 32 MiB of uploads in total.');
        for (const id of used) {
          if (!available(id)) throw new Error('Every scene needs linked production footage.');
          if (uploads.has(id)) files[id] = await asBase64(uploads.get(id).file);
        }
        const soundtrack = audio ? { audioId: project.soundtrack.audioId, file: await asBase64(audio) } : undefined;
        const blob = await api('render', { aspectRatio: project.aspectRatio, scenes: project.scenes, uploads: files, soundtrack, rightsConfirmed: true });
        rendered = { blob, url: URL.createObjectURL(blob), captions: captionTrack(project.scenes) };
      }
      const key = 'cut/' + project.revision;
      const attachCaptions = rendered.captions && currentView !== key;
      setPlayer(rendered.url, key, 'Rendered cut', project.name + ' · Revision ' + project.revision);
      if (attachCaptions) {
        const track = element('track');
        track.kind = 'captions'; track.label = 'Timeline captions'; track.default = true; track.src = rendered.captions;
        $('player').append(track);
      }
      document.dispatchEvent(new CustomEvent('rafii:cut-ready', {detail: {blob: rendered.blob, title: project.name, aspectRatio: project.aspectRatio}}));
      if (exportFile) download(rendered.url, fileStem(project.name) + '-r' + project.revision + '.mp4');
      notice(exportFile ? 'MP4 exported.' : 'Rendered cut ready to play.');
    });
  }
  listen('preview', 'click', () => cut(false));
  listen('export', 'click', () => cut(true));
  async function start() {
    await working('Opening the local editor…', async () => {
      const sample = await api('sample');
      for (const clip of sample.clips) bundled.set(clip.clipId, clip);
      let saved;
      try { saved = sessionStorage.getItem(SESSION_KEY); } catch { /* A project file still works. */ }
      if (saved) {
        try {
          openProject(validateProject(JSON.parse(saved)), true); notice('Edit restored from this tab. Relink imported files in Media if needed.'); return;
        } catch { /* Keep an invalid saved copy until the user explicitly edits or clears. */ }
      }
      openProject({ ...blank(), name: sample.name || 'Timer study', aspectRatio: sample.aspectRatio,
        clips: sample.clips, scenes: sample.scenes.map(newScene) }, true);
      $('project-kind').textContent = 'Sample project';
      setPlayer('/rafii/studio-examples/original-cut.mp4', 'sample', 'Sample cut', 'Timer study · First cut', '/rafii/studio-examples/original-cut-500ms.png');
      const captions = element('track'); captions.kind = 'captions'; captions.label = 'English'; captions.srclang = 'en';
      captions.src = '/rafii/studio-examples/original-cut.vtt'; $('player').append(captions); notice('');
    });
  }
  async function boot() {
    const controls = [$('project-actions'), ...['.inspector', '.timeline', '.monitor-footer', 'footer'].map(s => document.querySelector(s))];
    controls.forEach(node => { node.inert = false; });
    $('retry-editor').hidden = true;
    try { await start(); } catch (error) {
      // Preserve the saved edit until the bundled media catalog can be checked.
      controls.forEach(node => { node.inert = true; });
      $('project-meta').textContent = 'Local media worker unavailable';
      $('retry-editor').hidden = false;
      notice('Could not load the editor. ' + error.message, true);
    }
  }
  listen('retry-editor', 'click', boot);
  boot();
})();
