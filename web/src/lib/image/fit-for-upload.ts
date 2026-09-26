'use client';

/**
 * Scale and re-encode an image in the browser until it fits within `maxBytes`. Used before any upload that goes
 * to a Vercel Function as base64 JSON: base64 adds about a third, and Vercel caps request bodies at 4.5 MB
 * (https://vercel.com/docs/functions/limitations#request-body-size), so `maxBytes` must stay well under that.
 *
 * JPEG and PNG within the limit go through untouched. Any other image the browser can decode (HEIC on Safari, WebP,
 * GIF…) is always re-encoded to JPEG, because the server accepts only JPEG and PNG (chat-context SPEC §7.1).
 */

export type ImageProblem = 'heic' | 'unreadable' | 'no_canvas';

/** Copy from chat-context SPEC §13. */
export const IMAGE_MESSAGES: Record<ImageProblem, string> = {
  heic: 'This photo is HEIC. Save it as JPEG and try again.',
  unreadable: "This photo couldn't be read here. Try a JPEG or PNG.",
  no_canvas: "This photo couldn't be read here. Try a JPEG or PNG."
};

export class UnreadableImage extends Error {
  readonly code: ImageProblem;

  constructor(code: ImageProblem) {
    super(IMAGE_MESSAGES[code]);
    this.code = code;
  }
}

/** Base64 + a small JSON envelope adds roughly a third; this stays comfortably under Vercel's 4.5 MB body cap. */
export const SAFE_SEND_BYTES = 3 * 1024 * 1024;

/** The largest photo a person may pick before it is fitted (SPEC §7.1). */
export const MAX_PICK_BYTES = 30 * 1024 * 1024;

const DEFAULT_EDGES = [2048, 1600, 1200];
const SERVER_TYPES = new Set(['image/jpeg', 'image/png']);

export function isHeic(file: { type?: string; name?: string }): boolean {
  return (
    /^image\/hei[cf](-sequence)?$/i.test(file.type ?? '') || /\.(heic|heif)$/i.test(file.name ?? '')
  );
}

/** True when the server takes this file's format as is (only its size may still need fitting). */
export function isServerImage(file: { type?: string; name?: string }): boolean {
  return SERVER_TYPES.has((file.type ?? '').toLowerCase()) && !isHeic(file);
}

export async function fitForUpload(
  file: File | Blob,
  maxBytes: number,
  edges: readonly number[] = DEFAULT_EDGES
): Promise<Blob | null> {
  const keepFormat = isServerImage(file as File);
  if (keepFormat && file.size <= maxBytes) return file;
  let bitmap: ImageBitmap;
  try {
    // Decoded upright (camera photos carry their rotation in EXIF).
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() =>
      createImageBitmap(file)
    );
  } catch {
    throw new UnreadableImage(isHeic(file as File) ? 'heic' : 'unreadable');
  }
  try {
    // A format the server can't take is re-encoded even when small: first at full size (capped by the first edge).
    for (const edge of edges) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new UnreadableImage('no_canvas');
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      // The original format first (a PNG keeps its transparency), then JPEG. Other formats go straight to JPEG.
      const attempts = keepFormat
        ? ([
            [file.type, 0.9],
            ['image/jpeg', 0.85]
          ] as const)
        : ([
            ['image/jpeg', 0.9],
            ['image/jpeg', 0.85]
          ] as const);
      for (const [type, quality] of attempts) {
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, type, quality)
        );
        if (blob && blob.size <= maxBytes) return blob;
      }
    }
    return null;
  } finally {
    bitmap.close();
  }
}
