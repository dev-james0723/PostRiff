const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ASSET = path.resolve(__dirname, '../public/raffi/raffi-live-v1.glb');
const MAX_BYTES = 5 * 1024 * 1024;
const REQUIRED_NODES = [
  'RafiiRoot',
  'Body',
  'Head',
  'EarL',
  'EarR',
  'EyeL',
  'EyeR',
  'Mouth',
  'ArmL',
  'ArmR',
  'Tail01',
  'Tail02',
  'Tail03',
  'Tail04'
];
const REQUIRED_MORPHS = ['Open', 'Wide', 'Round', 'Smile'];

function parseGlb(file) {
  assert.ok(fs.existsSync(file), `canonical GLB does not exist: ${file}`);
  const bytes = fs.readFileSync(file);
  assert.ok(bytes.length <= MAX_BYTES, `GLB is ${bytes.length} bytes; limit is ${MAX_BYTES}`);
  assert.ok(bytes.length >= 20, 'GLB is too small to contain a header and JSON chunk');
  assert.equal(bytes.toString('ascii', 0, 4), 'glTF', 'GLB magic must be glTF');
  assert.equal(bytes.readUInt32LE(4), 2, 'GLB version must be 2');
  assert.equal(bytes.readUInt32LE(8), bytes.length, 'GLB declared length must match file length');

  let offset = 12;
  let document = null;
  while (offset < bytes.length) {
    const chunkLength = bytes.readUInt32LE(offset);
    const chunkType = bytes.readUInt32LE(offset + 4);
    const start = offset + 8;
    const end = start + chunkLength;
    assert.ok(end <= bytes.length, 'GLB chunk extends beyond file length');
    if (chunkType === 0x4e4f534a) {
      document = JSON.parse(bytes.toString('utf8', start, end).trimEnd());
    }
    offset = end;
  }
  assert.ok(document, 'GLB must contain a JSON chunk');
  return { bytes, document };
}

const { bytes, document } = parseGlb(ASSET);
const nodeNames = new Set((document.nodes ?? []).map((node) => node.name));
for (const name of REQUIRED_NODES) assert.ok(nodeNames.has(name), `missing required node: ${name}`);

const morphMeshes = (document.meshes ?? []).filter((mesh) => mesh.primitives?.some((primitive) => (primitive.targets?.length ?? 0) > 0));
assert.ok(morphMeshes.length > 0, 'at least one mesh must expose morph targets');
const morphNames = new Set(morphMeshes.flatMap((mesh) => mesh.extras?.targetNames ?? []));
for (const name of REQUIRED_MORPHS) assert.ok(morphNames.has(name), `missing required mouth morph target: ${name}`);

for (const [index, image] of (document.images ?? []).entries()) {
  if (Number.isInteger(image.bufferView)) {
    const payload = document.bufferViews?.[image.bufferView]?.byteLength ?? 0;
    assert.ok(payload <= MAX_BYTES, `image ${index} payload is ${payload} bytes; limit is ${MAX_BYTES}`);
  }
}

process.stdout.write(`PASS Rafii GLB contract (${bytes.length} bytes, ${nodeNames.size} named nodes, morphs: ${[...morphNames].join(', ')})\n`);
