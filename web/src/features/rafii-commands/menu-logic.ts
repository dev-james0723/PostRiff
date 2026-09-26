/**
 * Pure rules behind the `/` command menu (no React; tested by `web/tests/rafii-commands.test.cjs`): when it opens,
 * which commands it lists and in what order, and what choosing one does to the text.
 */
import { COMMAND_GROUPS, COMMANDS, commandKey, type CommandGroup, type SlashCommand } from '@/lib/agent-runtime/commands';

export interface SlashRange {
  start: number;
  end: number;
}

/** The `/word` being typed: where it sits in the text and what follows the slash. */
export interface SlashToken extends SlashRange {
  query: string;
}

/** The person closed the menu with Esc on this word; it stays closed while they keep typing the same word. */
export interface SlashDismissal {
  start: number;
  query: string;
}

export interface SlashMenuState {
  open: boolean;
  query: string;
  range: SlashRange | null;
  /** What the menu lists, in display order (grouped). */
  commands: SlashCommand[];
}

/**
 * What choosing a command does. `run`: put `value` in the input and run the client command's `execute(args)` now;
 * nothing goes to Rafii. `insert`: put `value` in the input (the command first, then whatever else was typed) so the
 * person types what the command needs and sends it. Either way the caret goes to `caret`.
 */
export interface SlashPick {
  action: 'run' | 'insert';
  value: string;
  caret: number;
  args: string;
}

const SLASH = new Set(['/', '／']);

/**
 * The `/word` the caret is at the end of: a word that starts with `/` or `／`, at the start of the text or after
 * whitespace, with no space typed in it yet. Null elsewhere, including `and/or`, `/app/queue` and mid-word carets.
 */
export function slashToken(value: string, caret: number): SlashToken | null {
  const end = Math.max(0, Math.min(caret, value.length));
  if (end < value.length && !/\s/.test(value[end])) return null;
  let start = end;
  while (start > 0 && !/\s/.test(value[start - 1])) start--;
  if (start === end || !SLASH.has(value[start])) return null;
  const query = value.slice(start + 1, end);
  if ([...query].some((char) => SLASH.has(char))) return null;
  return { start, end, query };
}

const HAN = /\p{Script=Han}/u;

function rankOf(command: SlashCommand, query: string): number | null {
  if (!query) return 3;
  const keys = [command.name, ...command.aliases].map(commandKey);
  if (keys.includes(query)) return 0;
  if (keys.some((key) => key.startsWith(query))) return 1;
  // Contains: how Chinese aliases match ("寫" finds 改寫), and a fallback for English from two letters on (a single
  // letter inside a word is noise).
  if ((HAN.test(query) || query.length >= 2) && keys.some((key) => key.includes(query))) return 2;
  return null;
}

const GROUP_ORDER = new Map<CommandGroup, number>(COMMAND_GROUPS.map((group, index) => [group.id, index]));

/**
 * Commands whose name or alias matches what follows the slash: exact first, then those it starts, then those containing
 * it. Groups stay together; a group with a better match moves up, so the first row is always a best match.
 */
export function filterCommands(query: string, commands: SlashCommand[] = COMMANDS): SlashCommand[] {
  const key = commandKey(query);
  const ranked = commands.flatMap((command, index) => {
    const rank = rankOf(command, key);
    return rank === null ? [] : [{ command, index, rank }];
  });
  const groupRank = new Map<CommandGroup, number>();
  for (const row of ranked) groupRank.set(row.command.group, Math.min(groupRank.get(row.command.group) ?? Infinity, row.rank));
  const group = (row: (typeof ranked)[number]) => [groupRank.get(row.command.group) ?? 0, GROUP_ORDER.get(row.command.group) ?? 0];
  return ranked
    .toSorted((a, b) => {
      const [aRank, aOrder] = group(a);
      const [bRank, bOrder] = group(b);
      return aRank - bRank || aOrder - bOrder || a.rank - b.rank || a.index - b.index;
    })
    .map((row) => row.command);
}

/** Consecutive commands of the same group under that group's heading (the order given is kept). */
export function groupCommands(commands: SlashCommand[]): { id: CommandGroup; label: string; commands: SlashCommand[] }[] {
  const groups: { id: CommandGroup; label: string; commands: SlashCommand[] }[] = [];
  for (const command of commands) {
    const last = groups[groups.length - 1];
    if (last && last.id === command.group) last.commands.push(command);
    else groups.push({ id: command.group, label: COMMAND_GROUPS.find((g) => g.id === command.group)?.label ?? command.group, commands: [command] });
  }
  return groups;
}

/** Whether a dismissal still applies: same slash, and the person has only typed further since pressing Esc. */
export function stillDismissed(token: SlashToken | null, dismissed: SlashDismissal | null | undefined): boolean {
  return Boolean(token && dismissed && token.start === dismissed.start && token.query.startsWith(dismissed.query));
}

/** Open only on a `/word` with at least one matching command, never during IME composition or after Esc on that word. */
export function slashMenuState(value: string, caret: number, options: { isComposing?: boolean; dismissed?: SlashDismissal | null; commands?: SlashCommand[] } = {}): SlashMenuState {
  const token = slashToken(value, caret);
  const closed = !token || Boolean(options.isComposing) || stillDismissed(token, options.dismissed);
  const commands = token && !closed ? filterCommands(token.query, options.commands) : [];
  return { open: commands.length > 0, query: token?.query ?? '', range: token ? { start: token.start, end: token.end } : null, commands };
}

/**
 * What choosing `command` for the `/word` at `range` does to `value`:
 * - `help` becomes a bare `/`, which lists every command;
 * - a client command that needs no words runs now, and the rest of the text stays in the input;
 * - a client command whose words are already typed after it (`/op| channels`) runs with them;
 * - anything else is inserted: `/name ` first, then whatever else was typed, for the person to finish and send.
 *   A command is the first word of a message, so one picked mid-sentence moves to the front.
 */
export function applyPick(value: string, range: SlashRange, command: SlashCommand): SlashPick {
  const before = value.slice(0, range.start);
  const after = value.slice(range.end);
  const atStart = before.trim() === '';
  const rest = after.trim();
  if (command.name === 'help') return { action: 'insert', value: `${before}/${after}`, caret: range.start + 1, args: '' };
  if (command.kind === 'client') {
    if (atStart && rest && command.takes !== 'none') return { action: 'run', value: '', caret: 0, args: rest };
    if (command.takes !== 'required') {
      // The word before the slash already ends in whitespace, so one space at the join is enough.
      const kept = (atStart ? '' : before) + after.replace(/^[^\S\n]+/, '');
      return { action: 'run', value: kept, caret: atStart ? 0 : before.length, args: '' };
    }
  }
  const words = atStart ? rest : [before.trim(), rest].filter(Boolean).join(' ');
  const text = `/${command.name} ${words}`;
  return { action: 'insert', value: text, caret: text.length, args: words };
}

/** A key press that belongs to an IME composition (Chinese, Japanese, Korean input): never a menu key. */
export function isImeEvent(event: { isComposing?: boolean; keyCode?: number; nativeEvent?: { isComposing?: boolean; keyCode?: number } }): boolean {
  return Boolean(event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229 || event.nativeEvent?.keyCode === 229);
}
