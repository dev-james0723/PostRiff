/**
 * Text files (.txt, .md) turned into sources, decoded in the browser (chat-context SPEC §7.5).
 *
 * Order: strict UTF-8, then Big5 (Hong Kong and Taiwan files), then GB18030, which accepts any byte sequence, so a
 * file always opens. A leading BOM is removed. The `source` command takes at most 20,000 UTF-8 bytes of text.
 */

export const TEXT_FILE_MAX_BYTES = 20_000;
export const TEXT_FILE_TOO_LARGE =
  'Text files can be up to 20 KB (about 6,600 Chinese characters).';

export type TextEncodingName = 'UTF-8' | 'Big5' | 'GB18030';

export class TextFileTooLarge extends Error {
  constructor() {
    super(TEXT_FILE_TOO_LARGE);
  }
}

export interface DecodedText {
  text: string;
  encoding: TextEncodingName;
  bytes: number;
}

const ORDER: readonly (readonly [TextEncodingName, string, boolean])[] = [
  ['UTF-8', 'utf-8', true],
  ['Big5', 'big5', true],
  ['GB18030', 'gb18030', false]
];

export function isTextFile(file: { name?: string; type?: string }): boolean {
  return (
    /\.(txt|md|markdown)$/i.test(file.name ?? '') ||
    /^text\/(plain|markdown)$/i.test(file.type ?? '')
  );
}

export function decodeText(input: ArrayBuffer | Uint8Array): DecodedText {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  for (const [name, label, fatal] of ORDER) {
    let text: string;
    try {
      // ignoreBOM: false strips a matching BOM; the explicit check below also covers a UTF-8 BOM seen by Big5/GB18030.
      text = new TextDecoder(label, { fatal, ignoreBOM: false }).decode(bytes);
    } catch {
      continue;
    }
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const size = new TextEncoder().encode(text).length;
    if (size > TEXT_FILE_MAX_BYTES) throw new TextFileTooLarge();
    return { text, encoding: name, bytes: size };
  }
  throw new TextFileTooLarge(); // unreachable: GB18030 without `fatal` decodes every byte sequence
}

/** "Opened as Big5 text." — shown when the file wasn't UTF-8 (SPEC §13). */
export function openedAsMessage(encoding: TextEncodingName): string {
  return `Opened as ${encoding} text.`;
}
