'use client';

import { useId, useState } from 'react';
import { useTheme } from 'next-themes';
import type { DiscordCopy } from '../../lib/channels/discord-copy';
import { DISCORD_PREVIEW_PALETTE, type PreviewTheme } from '../../lib/channels/discord-preview-theme';
import type { SenderKind } from '../../lib/channels/discord-sender-name';

/**
 * Where the shown name comes from. `draft`: what the person is typing, not saved. `saved`: a custom name Rafii stored
 * for a webhook connection. `webhook_default`: the name saved on the webhook itself in Discord (no custom name).
 * `observed`: a bot nickname as Rafii last read it. `approved`: the bot nickname recorded in an approval.
 * `bot_username`: the bot has no nickname there, so Discord shows its own username. `unknown`: Rafii does not know the
 * name, so the preview says so instead of making one up.
 */
export type PreviewNameSource = 'draft' | 'saved' | 'webhook_default' | 'observed' | 'approved' | 'bot_username' | 'unknown';

export interface PreviewMediaItem {
  url: string;
  alt: string;
}

export interface DiscordMessagePreviewProps {
  kind: SenderKind;
  name: string | null;
  nameSource: PreviewNameSource;
  /** The message as written; absent shows the example text and says it is an example. */
  text?: string | null;
  /** When the post goes out (shown as Discord shows a message time); absent means now. */
  publishAt?: Date | null;
  timeZone?: string;
  media?: readonly PreviewMediaItem[];
  copy: DiscordCopy;
  locale: string;
  /** The tag Discord puts next to app and webhook authors, as the server reports it (`preview.badge`). */
  badge?: string;
  /** `preview.queuedPostsKeepApprovedName` (webhook); default true. */
  queuedKeepsName?: boolean;
  /**
   * Bot only, and only where it is known that an approval records the nickname and holds the post when Discord shows
   * another one (`preview.queuedBotPostsHoldIfNicknameChanges` with the nickname switch on, or an approval that carries
   * the recorded nickname). `pending`: before approval, `approved`: the approval already exists. Absent: no claim.
   */
  botHold?: 'pending' | 'approved';
  /** Heading text; the editor says "Sender preview", reviews say "How it will look in Discord". */
  heading: string;
  headingLevel?: 'h3' | 'h4';
  /** Offer a Dark / Light switch (the editor does; reviews follow the app's theme). */
  themeToggle?: boolean;
  /** Draw this theme instead of following the app (tests and documentation images); the switch still works. */
  theme?: PreviewTheme;
  /** Reviews and the schedule dialog: one short line instead of separate avatar and fidelity notes. */
  compact?: boolean;
  className?: string;
}

const join = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ');

/** "Today at 3:42 PM" when the time falls on today in `timeZone`, otherwise the date and time in the reader's locale. */
export function previewTimeLabel(copy: DiscordCopy, locale: string, at: Date, timeZone?: string, now: Date = new Date()): string {
  const zone = timeZone ? { timeZone } : {};
  try {
    const clock = new Intl.DateTimeFormat(locale || 'en', { hour: 'numeric', minute: '2-digit', ...zone }).format(at);
    const day = (date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', ...zone }).format(date);
    if (day(at) === day(now)) return copy.previewToday.replace('{time}', clock);
    const date = new Intl.DateTimeFormat(locale || 'en', { year: 'numeric', month: '2-digit', day: '2-digit', ...zone }).format(at);
    return `${date} ${clock}`;
  } catch {
    return copy.previewToday.replace('{time}', at.toISOString().slice(11, 16));
  }
}

/** The name line: the name itself, or an honest stand-in that is drawn muted so nobody reads it as a real name. */
export function previewAuthor(copy: DiscordCopy, kind: SenderKind, name: string | null, source: PreviewNameSource): { label: string; placeholder: boolean } {
  if (name && name.trim()) return { label: name, placeholder: false };
  if (source === 'draft') return { label: copy.previewEmptyName, placeholder: true };
  return { label: kind === 'bot' ? copy.previewBotNameUnknown : copy.previewWebhookNameDefault, placeholder: true };
}

function AvatarPlaceholder({ palette }: { palette: (typeof DISCORD_PREVIEW_PALETTE)[PreviewTheme] }) {
  return (
    <span
      aria-hidden
      data-preview-avatar
      className='flex size-10 shrink-0 items-center justify-center rounded-full border border-dashed'
      style={{ background: palette.avatarBackground, borderColor: palette.avatarForeground, color: palette.avatarForeground }}
    >
      <svg viewBox='0 0 24 24' width='22' height='22' fill='currentColor' focusable='false'>
        <circle cx='12' cy='9' r='4' />
        <path d='M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z' />
      </svg>
    </span>
  );
}

/**
 * A message as Discord lays it out: avatar, author name with the APP tag Discord puts on app and webhook authors, the
 * time, and the text with its line breaks. It is an imitation drawn from Discord's documented layout, not a screenshot
 * and not Discord rendering: the notes under it say what it cannot show.
 *
 * Webhook: the name is a per-send override, so it is the author of each post. Bot: the name is the bot's nickname in
 * the whole server; the preview never presents it as a name for one post.
 */
export function DiscordMessagePreview({
  kind,
  name,
  nameSource,
  text,
  publishAt,
  timeZone,
  media,
  copy,
  locale,
  badge,
  queuedKeepsName,
  botHold,
  heading,
  headingLevel = 'h3',
  themeToggle = false,
  theme: forcedTheme,
  compact = false,
  className
}: DiscordMessagePreviewProps) {
  const headingId = useId();
  const notesId = useId();
  const { resolvedTheme } = useTheme();
  const [choice, setChoice] = useState<PreviewTheme | null>(null);
  // Fixed for the life of the preview unless the person flips it, so a sample time never ticks.
  const [openedAt] = useState(() => new Date());
  const theme: PreviewTheme = choice ?? forcedTheme ?? (resolvedTheme === 'dark' ? 'dark' : 'light');
  const palette = DISCORD_PREVIEW_PALETTE[theme];
  const author = previewAuthor(copy, kind, name, nameSource);
  const at = publishAt ?? openedAt;
  const sample = text === undefined || text === null;
  const empty = !sample && text.trim() === '';
  const body = sample ? copy.senderExample : empty ? copy.previewEmptyText : text;
  const Heading = headingLevel;
  const when = previewTimeLabel(copy, locale, at, timeZone);

  const nameNotes: string[] =
    kind === 'bot'
      ? [copy.previewBotNote, ...(botHold === 'pending' ? [copy.previewBotQueuedNote] : botHold === 'approved' ? [copy.previewBotApprovedNote] : [])]
      : [copy.previewWebhookNote, ...((queuedKeepsName ?? true) ? [copy.previewWebhookQueuedNote] : [])];
  if (nameSource === 'unknown') nameNotes.push(kind === 'bot' ? copy.previewBotNameUnknownNote : copy.previewWebhookDefaultNote);
  if (nameSource === 'webhook_default') nameNotes.push(copy.previewWebhookDefaultNote);
  if (nameSource === 'observed') nameNotes.push(copy.previewBotNameAsOf);
  if (nameSource === 'bot_username') nameNotes.push(copy.previewBotUsernameNote);
  if (nameSource === 'draft') nameNotes.push(copy.senderPreviewUnsaved);

  return (
    <section
      aria-labelledby={headingId}
      className={join('flex min-w-0 flex-col gap-2', className)}
      data-discord-message-preview
      data-discord-sender-preview
      data-kind={kind}
      data-theme={theme}
      data-name-source={nameSource}
    >
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <Heading id={headingId} className='text-sm font-medium'>
          {heading}
        </Heading>
        {themeToggle && (
          <div role='group' aria-label={copy.previewThemeLabel} className='flex gap-1' data-preview-theme-toggle>
            {(['dark', 'light'] as const).map((option) => (
              <button
                key={option}
                type='button'
                aria-pressed={theme === option}
                data-theme-option={option}
                onClick={() => setChoice(option)}
                className='border-input text-foreground hover:bg-muted focus-visible:ring-ring/50 aria-pressed:bg-muted aria-pressed:border-foreground/40 min-h-11 min-w-11 rounded-lg border px-3 text-sm outline-none focus-visible:ring-3'
              >
                {option === 'dark' ? copy.previewThemeDark : copy.previewThemeLight}
              </button>
            ))}
          </div>
        )}
      </div>
      <div
        data-preview-message
        role='group'
        aria-label={copy.previewMessageLabel}
        aria-describedby={notesId}
        className='flex min-w-0 items-start gap-3 rounded-lg border p-3 text-[15px]'
        style={{ background: palette.surface, borderColor: palette.edge, color: palette.text }}
      >
        <AvatarPlaceholder palette={palette} />
        <div className='min-w-0 flex-1'>
          <p className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 leading-[22px]'>
            <span
              data-preview-author
              data-placeholder={author.placeholder ? 'true' : undefined}
              className={join('min-w-0 font-medium [overflow-wrap:anywhere]', author.placeholder && 'italic')}
              style={{ color: author.placeholder ? palette.muted : palette.name }}
            >
              {author.label}
            </span>
            <span
              data-preview-app-tag
              className='rounded px-1 text-[10px] leading-[15px] font-semibold tracking-wide'
              style={{ background: palette.appTagBackground, color: palette.appTagText }}
            >
              {badge || copy.previewAppTag}
            </span>
            <time data-preview-time dateTime={at.toISOString()} className='text-xs' style={{ color: palette.muted }}>
              {when}
            </time>
          </p>
          <p
            data-preview-body
            data-empty={empty ? 'true' : undefined}
            className={join('text-[15px] leading-[22px] whitespace-pre-wrap [overflow-wrap:anywhere]', empty && 'italic')}
            style={empty ? { color: palette.muted } : undefined}
          >
            {body}
          </p>
          {media?.map((item) => (
            // eslint-disable-next-line @next/next/no-img-element -- a private object URL of the person's own upload
            <img key={item.url} src={item.url} alt={item.alt} className='mt-2 max-h-64 max-w-full rounded-lg object-contain' />
          ))}
        </div>
      </div>
      <div id={notesId} className='text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed' data-preview-notes>
        {nameNotes.map((note) => (
          <p key={note} data-preview-name-note>
            {note}
          </p>
        ))}
        {sample && <p data-preview-sample-note>{copy.previewSampleNote}</p>}
        {compact ? (
          <p data-preview-compact-note>{copy.previewCompactNote}</p>
        ) : (
          <>
            <p data-preview-avatar-note>{kind === 'bot' ? copy.previewAvatarBot : copy.previewAvatarWebhook}</p>
            <p data-preview-fidelity-note>{copy.previewFidelity}</p>
          </>
        )}
      </div>
    </section>
  );
}
