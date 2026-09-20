'use client';

import { toBlob } from 'html-to-image';

/**
 * The phone as a PNG, with PostRiff's note under it so a shared image never passes for a screenshot of the app.
 * Drawn from the live phone (current slide, video frame, guides if showing); controls PostRiff adds for playing
 * and paging (`data-export="skip"`) are left out.
 */
export async function previewImage(phone: HTMLElement, { channelName, dark }: { channelName: string; dark: boolean }) {
  const width = phone.getBoundingClientRect().width || 1;
  // About 1,200 pixels wide whatever size the phone is drawn at.
  const pixelRatio = Math.min(Math.max(1200 / width, 2), 6);
  // The page's drop shadow would be cut into a box; the canvas draws its own.
  phone.dataset.exporting = '';
  let shot: Blob | null;
  try {
    shot = await toBlob(phone, {
      pixelRatio,
      filter: (node) => !(node instanceof HTMLElement && node.dataset.export === 'skip')
    });
  } finally {
    delete phone.dataset.exporting;
  }
  if (!shot) throw new Error('The phone could not be drawn.');
  const picture = await createImageBitmap(shot);
  const { width: pictureWidth, height: pictureHeight } = picture;

  const pad = Math.round(32 * pixelRatio);
  const size = Math.round(9 * pixelRatio);
  const leading = Math.round(size * 1.4);
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('The phone could not be drawn.');
  const font = `${size}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
  context.font = font;
  const lines = wrap(context, `${channelName} post preview drawn by PostRiff. Not a screenshot: the app has the final say on layout.`, pictureWidth);

  // Resizing the canvas resets its drawing state, so the font is set again below.
  canvas.width = pictureWidth + pad * 2;
  canvas.height = pictureHeight + pad * 2 + leading * (lines.length + 1);
  context.fillStyle = dark ? '#111113' : '#f5f5f4';
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.save();
  context.shadowColor = 'rgba(0, 0, 0, 0.35)';
  context.shadowBlur = 28 * pixelRatio;
  context.shadowOffsetY = 14 * pixelRatio;
  context.drawImage(picture, pad, pad);
  context.restore();
  picture.close();

  context.font = font;
  context.fillStyle = dark ? '#a1a1aa' : '#71717a';
  context.textAlign = 'center';
  context.textBaseline = 'top';
  lines.forEach((line, index) => context.fillText(line, canvas.width / 2, pad + pictureHeight + leading * (index + 0.75)));

  return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('The phone could not be drawn.'))), 'image/png'));
}

/** Words laid into lines no wider than `width` in the context's current font. */
function wrap(context: CanvasRenderingContext2D, text: string, width: number) {
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(' ')) {
    const next = line ? `${line} ${word}` : word;
    if (line && context.measureText(next).width > width) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

const pad = (value: number) => String(value).padStart(2, '0');

export function previewFileName(channel: string, at = new Date()) {
  return `postriff-preview-${channel}-${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}.png`;
}

export const canCopyImages = () => typeof ClipboardItem !== 'undefined' && typeof navigator !== 'undefined' && Boolean(navigator.clipboard?.write);
