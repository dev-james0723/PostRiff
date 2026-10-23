"""Decode a directory of images with this interpreter's Pillow through the customer upload and account-picture paths.

usage: python impact_pillow_probe.py <tree root> <image directory>   (prints JSON)

The candidate moves Pillow from 12.3.0 (live pin) to 13.0.0 while media.py and account_pictures.py stay unchanged, so
running this file under both Pillow versions on the same input files isolates what the dependency change does to the
two paths every customer uses: an uploaded image (media._decode_pillow) and a connected account's picture
(account_pictures.square_jpeg). Used by tests/test_customer_impact_dependencies.py.
"""
import hashlib
import io
import json
import os
import sys

tree, directory = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, 'src'))
import PIL  # noqa: E402
from PIL import Image  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import media  # noqa: E402
from postriff_phase2.account_pictures import square_jpeg  # noqa: E402


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert('RGB')
        return image.size, image.tobytes()


out = {'pillow': PIL.__version__, 'images': {}}
for name in sorted(os.listdir(directory)):
    with open(os.path.join(directory, name), 'rb') as handle:
        raw = handle.read()
    entry = {}
    try:
        rendition, width, height, decoder = media._decode_pillow(raw)
        size, data = pixels(rendition)
        entry['upload'] = {'ok': True, 'width': width, 'height': height, 'sha256': hashlib.sha256(rendition).hexdigest(),
                           'pixels': hashlib.sha256(data).hexdigest(), 'decodedSize': list(size)}
    except AlphaError as error:
        entry['upload'] = {'ok': False, 'message': str(error)}
    picture = square_jpeg(raw)
    if picture is None:
        entry['picture'] = {'ok': False}
    else:
        size, data = pixels(picture)
        entry['picture'] = {'ok': True, 'sha256': hashlib.sha256(picture).hexdigest(), 'pixels': hashlib.sha256(data).hexdigest(),
                            'decodedSize': list(size)}
    out['images'][name] = entry
print(json.dumps(out, sort_keys=True))
