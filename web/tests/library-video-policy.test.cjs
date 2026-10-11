const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const src = path.join(__dirname, '..', 'src');
const libraryFile = path.join(src, 'features', 'library', 'library-view.tsx');
const videoFile = path.join(src, 'features', 'agent', 'attachments', 'video-file.ts');
const librarySource = fs.readFileSync(libraryFile, 'utf8');
const libraryAst = ts.createSourceFile(libraryFile, librarySource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function load(source, fileName, bindings = {}) {
  const { outputText } = ts.transpileModule(source, {
    fileName,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', ...Object.keys(bindings), outputText)(
    require, mod, mod.exports, ...Object.values(bindings)
  );
  return mod.exports;
}

const V = load(fs.readFileSync(videoFile, 'utf8'), videoFile);

function findNode(predicate, root = libraryAst) {
  if (predicate(root)) return root;
  return ts.forEachChild(root, (node) => findNode(predicate, node));
}

function libraryFunction(name, bindings = {}) {
  const node = findNode((item) => ts.isFunctionDeclaration(item) && item.name?.text === name);
  assert.ok(node, `${name} is present in Library`);
  // Execute the actual pure Library gate, without mounting React or copying its decision logic into the test.
  return load(`${node.getText(libraryAst)}\nmodule.exports = ${name};`, `${name}.ts`, bindings);
}

const isLibraryVideo = libraryFunction('isLibraryVideo', {
  VIDEO_UPLOAD_MIMES: new Set(['video/mp4', 'video/quicktime']),
  VIDEO_UPLOAD_EXTENSIONS: new Set(['mp4', 'mov', 'm4v'])
});

function admission(videoPolicy, message = 'Video limits unavailable') {
  return libraryFunction('validateLibraryFile', {
    isLibraryVideo,
    videoPolicy,
    videoUnavailable: message,
    MAX_PICK_BYTES: 30 * 1024 * 1024,
    LIBRARY_FILE_MAX_BYTES: 50 * 1024 * 1024,
    videoSizeLimit: V.videoSizeLimit
  });
}

function file(size, name = 'clip.mp4', type = 'video/mp4') {
  const prefix = Buffer.alloc(24);
  prefix.writeUInt32BE(24);
  prefix.write('ftyp', 4);
  prefix.write('isom', 8);
  prefix.write('mp41', 16);
  prefix.write('isom', 20);
  // The check only reads the prefix. Model a large video without allocating its payload in a test worker.
  return { size, name, type, slice: (start, end) => new Blob([prefix.subarray(start, end)], { type }) };
}

test('Library accepts a video above 50 MB and 180 seconds only under enabled server limits', async () => {
  const policy = V.videoPolicyFromCatalog({ enabled: true, maxBytes: 500_000_000, maxSeconds: 7200 });
  assert.deepEqual(policy, { maxBytes: 500_000_000, maxSeconds: 7200 });
  const video = file(150_000_000);
  assert.equal(admission(policy)(video), null);
  assert.equal((await V.checkVideoFile(video, policy)).ok, true);
  assert.equal(V.checkDuration(600, policy), null);
  assert.equal(admission(policy)(file(policy.maxBytes)), null);
  assert.equal(V.checkDuration(policy.maxSeconds, policy), null);
  assert.equal(admission(policy)(file(policy.maxBytes + 1)).code, 'file-too-large');
  assert.equal((await V.checkVideoFile(file(policy.maxBytes + 1), policy)).ok, false);
  assert.equal(V.checkDuration(policy.maxSeconds + 1, policy), 'This video is longer than 2 hours.');
});

test('Library video admission fails closed while limits load, fail, are disabled or malformed', () => {
  for (const catalog of [
    undefined, null, {},
    { enabled: false, maxBytes: 500_000_000, maxSeconds: 7200 },
    { enabled: true, maxBytes: 0, maxSeconds: 7200 },
    { enabled: true, maxBytes: Infinity, maxSeconds: 7200 },
    { enabled: true, maxBytes: Number.MAX_SAFE_INTEGER + 1, maxSeconds: 7200 },
    { enabled: true, maxBytes: '500000000', maxSeconds: 7200 },
    { enabled: true, maxBytes: 500_000_000, maxSeconds: NaN },
    { enabled: true, maxBytes: 500_000_000, maxSeconds: 0 }
  ]) {
    const policy = V.videoPolicyFromCatalog(catalog);
    assert.equal(policy, null);
    assert.deepEqual(admission(policy)(file(100_000_000)), {
      code: 'video-unavailable', message: 'Video limits unavailable'
    });
    assert.equal(admission(policy)(file(1024, 'notes.pdf', 'application/pdf')), null);
  }
  assert.match(librarySource, /models\.isPending \|\| models\.isError/);
  assert.match(librarySource, /videoPolicyFromCatalog\(models\.data\?\.attachments\?\.video\)/);
});

test('larger video policy never increases document, audio, generic-file or image limits', () => {
  const allow = admission({ maxBytes: 2_000_000_000, maxSeconds: 43200 });
  assert.equal(allow(file(100_000_000, 'CLIP.MOV', '')), null);
  for (const [name, type] of [
    ['notes.pdf', 'application/pdf'], ['recording.wav', 'audio/wav'],
    ['recording.webm', 'audio/webm'], ['archive.zip', 'application/zip']
  ]) {
    assert.equal(allow(file(50 * 1024 * 1024, name, type)), null);
    assert.equal(allow(file(50 * 1024 * 1024 + 1, name, type)).code, 'file-too-large');
  }
  assert.equal(allow(file(30 * 1024 * 1024, 'photo.jpg', 'image/jpeg')), null);
  assert.equal(allow(file(30 * 1024 * 1024 + 1, 'photo.jpg', 'image/jpeg')).code, 'file-too-large');
  assert.equal(allow(file(0)).code, 'file-too-small');
});

test('dropzone delegates per-kind size checks instead of silently rejecting larger allowed videos', () => {
  const call = findNode((node) => ts.isCallExpression(node) && node.expression.getText(libraryAst) === 'useDropzone');
  assert.ok(call && ts.isObjectLiteralExpression(call.arguments[0]));
  const options = call.arguments[0].properties;
  assert.equal(options.some((item) => item.name?.getText(libraryAst) === 'maxSize'), false);
  const validator = options.find((item) => item.name?.getText(libraryAst) === 'validator');
  assert.equal(validator?.initializer?.getText(libraryAst), 'validateLibraryFile');
  const upload = findNode((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'uploadLibraryVideo');
  assert.match(upload.getText(libraryAst), /checkVideoFile\(file, policy\)/);
  assert.match(upload.getText(libraryAst), /checkDuration\(metadata\?\.duration \?\? null, policy\)/);
  assert.doesNotMatch(upload.getText(libraryAst), /50_000_000|maxSeconds:\s*180/);
  const videoSource = upload.getText(libraryAst);
  const begin = findNode((node) => ts.isCallExpression(node) && node.expression.getText(libraryAst) === 'api.beginVideoUpload', upload);
  assert.ok(begin && ts.isObjectLiteralExpression(begin.arguments[1]));
  const videoIntent = Object.fromEntries(begin.arguments[1].properties.map((item) => [
    item.name?.getText(libraryAst), item.initializer?.getText(libraryAst)
  ]));
  assert.deepEqual(videoIntent, {
    mime: 'checked.mime', bytes: 'blanked.blob.size', duration: 'metadata?.duration ?? null',
    width: 'metadata?.width ?? null', height: 'metadata?.height ?? null', transport: "'tus'"
  }, 'Video intent retains inspected MIME/metadata and explicitly selects signed resumable transport.');
  assert.match(videoSource, /blankLocation\(file\)/);
  assert.match(videoSource, /fingerprintVideo\(blanked\.blob/);
  assert.match(videoSource, /videoBlob:\s*blanked\.blob/);
  assert.match(videoSource, /pending\.ticket\.method !== 'TUS' \|\| !pending\.ticket\.resumable/);
  assert.match(videoSource, /uploadResumableVideo\(current\.ticket!, current\.videoBlob!/);
  assert.match(videoSource, /signal:\s*videoUploadAbort\.current\.signal/);
  assert.match(videoSource, /api\.resumeVideoUpload\(workspaceId, previous\.assetId, \{ mime: checked\.mime, bytes: blanked\.blob\.size \}\)/);
  assert.match(videoSource, /locationCleared:\s*blanked\.locationCleared/);
  assert.match(videoSource, /api\.commitVideoUpload\(workspaceId, pending\.assetId, pending\.video\)/);
  assert.ok(videoSource.indexOf('await uploadResumableVideo(') < videoSource.indexOf('await api.commitVideoUpload('),
    'Transport completion precedes server-authoritative inspection/commit.');
  assert.doesNotMatch(videoSource, /putSignedUpload\(|api\.(?:beginLibraryFile|beginUpload)\(/,
    'Video never falls back to whole-file PUT or the generic file upload path.');
  const generic = findNode((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'uploadLibraryFile');
  assert.match(generic.getText(libraryAst), /api\.beginLibraryFile\(/);
  assert.match(generic.getText(libraryAst), /putSignedUpload\(/,
    'Document/audio upload retains its separate signed PUT flow and limits.');
});

test('video policy copy communicates actual non-minute and large-file limits', () => {
  assert.equal(V.videoDurationLimit(90), '90 seconds');
  assert.equal(V.checkDuration(91, { maxBytes: 500_000_000, maxSeconds: 90 }), 'This video is longer than 90 seconds.');
  assert.equal(V.videoDurationLimit(43200), '12 hours');
  assert.match(V.videoSizeLimit(2_000_000_000), /2 GB/);
  assert.match(librarySource, /videoSizeLimit\(videoPolicy\.maxBytes\)/);
  assert.match(librarySource, /videoDurationLimit\(videoPolicy\.maxSeconds\)/);
});
