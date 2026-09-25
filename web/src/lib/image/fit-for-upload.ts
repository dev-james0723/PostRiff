'use client';

/**
 * Scale and re-encode an image in the browser until it fits within `maxBytes`. Used before any upload that goes
 * to a Vercel Function as base64 JSON: base64 adds about a third, and Vercel caps request bodies at 4.5 MB
 * (https://vercel.com/docs/functions/limitations#request-body-size), so `maxBytes` must stay well under that.
 */

export class UnreadableImage extends Error {}

/** Base64 + a small JSON envelope adds roughly a third; this stays comfortably under Vercel's 4.5 MB body cap. */
export const SAFE_SEND_BYTES = 3 * 1024 * 1024;

const DEFAULT_EDGES = [2048, 1600, 1200];

export async function fitForUpload(file: File | Blob, maxBytes: number, edges: readonly number[] = DEFAULT_EDGES): Promise<Blob | null> {
  if (file.size <= maxBytes) return file;
  let bitmap: ImageBitmap;
  try {
    // Decoded upright (camera photos carry their rotation in EXIF).
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => createImageBitmap(file));
  } catch {
    throw new UnreadableImage('This image could not be read here. Try a PNG or JPEG exported from your photos app.');
  }
  try {
    for (const edge of edges) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new UnreadableImage('This browser couldn’t scale the image down. Try a smaller one.');
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      // The original format first (a PNG keeps its transparency), then JPEG.
      for (const [type, quality] of [[file.type, 0.9], ['image/jpeg', 0.85]] as const) {
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, quality));
        if (blob && blob.size <= maxBytes) return blob;
      }
    }
    return null;
  } finally {
    bitmap.close();
  }
}
