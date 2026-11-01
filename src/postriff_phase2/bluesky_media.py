"""Bluesky image approvals, frozen into the existing publishing manifest."""
from postriff_alpha.domain import AlphaError, clean
from .asset_kinds import is_postable_image

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 2_000_000


def approved_images(assets, choices, rights_confirmed):
    # Official app.bsky.embed.images lexicon: four images, two million bytes each.
    if (not isinstance(choices, list) or not 1 <= len(choices) <= MAX_IMAGES
            or rights_confirmed is not True):
        raise AlphaError("Choose one to four Bluesky images and confirm their rights.", 409)
    result, seen = [], set()
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {'assetId', 'alt'}:
            raise AlphaError("Each Bluesky image needs an asset and its own alt text.", 400)
        asset_id = choice['assetId']
        if not isinstance(asset_id, str) or not asset_id or asset_id in seen:
            raise AlphaError("Choose each Bluesky image once.", 400)
        seen.add(asset_id)
        asset = next((item for item in assets if item.get('id') == asset_id), None)
        alt = clean(choice['alt'], 1000)
        if (not asset or not is_postable_image(asset) or not alt
                or type(asset.get('bytes')) is not int or not 0 < asset['bytes'] <= MAX_IMAGE_BYTES):
            raise AlphaError("Each Bluesky image needs decoded bytes of at most 2 MB and alt text.", 409)
        result.append({key: asset[key] for key in ('id', 'hash', 'sourceHash', 'mime', 'bytes', 'width', 'height', 'duration')}
                      | ({'objectName': asset['objectName']} if isinstance(asset.get('objectName'), str) else {})
                      | {'alt': alt, 'rightsConfirmed': True})
    return result
