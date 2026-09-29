"""Make the supplied Meshy Rafii GLB practical for mobile without changing its mesh.

Usage: python3 scripts/optimize_rafii_meshy_glb.py source.glb web/public/raffi/raffi-live-meshy-20260928.glb
Requires macOS sips. The source must contain the two embedded PNG textures exported by Meshy/Blender.
"""

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def pad(data: bytes, value: bytes) -> bytes:
    return data + value * (-len(data) % 4)


def main(source: Path, target: Path) -> None:
    raw = source.read_bytes()
    magic, version, total = struct.unpack_from('<4sII', raw)
    if (magic, version, total) != (b'glTF', 2, len(raw)):
        raise ValueError('Expected a complete GLB v2 file')
    json_len, json_type = struct.unpack_from('<II', raw, 12)
    bin_at = 20 + json_len
    bin_len, bin_type = struct.unpack_from('<II', raw, bin_at)
    if (json_type, bin_type) != (0x4E4F534A, 0x004E4942):
        raise ValueError('Expected JSON and BIN chunks')
    document = json.loads(raw[20:bin_at])
    binary = raw[bin_at + 8:bin_at + 8 + bin_len]
    if len(document['images']) != 2 or any(image['mimeType'] != 'image/png' for image in document['images']):
        raise ValueError('Expected the supplied Meshy GLB with two embedded PNG textures')

    replacements = {}
    with tempfile.TemporaryDirectory(prefix='rafii-meshy-') as directory:
        for index, dimension in enumerate((4096, 2048)):
            view_index = document['images'][index]['bufferView']
            view = document['bufferViews'][view_index]
            png = Path(directory) / f'texture-{index}.png'
            jpeg = Path(directory) / f'texture-{index}.jpg'
            png.write_bytes(binary[view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']])
            subprocess.run(['sips', '-Z', str(dimension), '-s', 'format', 'jpeg', '-s', 'formatOptions', '88', str(png), '--out', str(jpeg)], check=True, stdout=subprocess.DEVNULL)
            replacements[view_index] = jpeg.read_bytes()
            document['images'][index]['mimeType'] = 'image/jpeg'

    pieces = []
    offset = 0
    for index, view in enumerate(document['bufferViews']):
        chunk = replacements.get(index)
        if chunk is None:
            chunk = binary[view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']]
        view['byteOffset'] = offset
        view['byteLength'] = len(chunk)
        piece = pad(chunk, b'\0')
        pieces.append(piece)
        offset += len(piece)
    document['buffers'][0]['byteLength'] = offset
    json_chunk = pad(json.dumps(document, separators=(',', ':')).encode(), b' ')
    bin_chunk = b''.join(pieces)
    output = struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(json_chunk) + 8 + len(bin_chunk))
    output += struct.pack('<II', len(json_chunk), 0x4E4F534A) + json_chunk
    output += struct.pack('<II', len(bin_chunk), 0x004E4942) + bin_chunk
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(output)
    print(f'{source.name}: {len(raw):,} bytes -> {target}: {len(output):,} bytes')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
