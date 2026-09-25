/** Rafii's slash commands. Stub until the commands slice lands; keeps the exported shape stable. */

export type CommandGroup = 'write' | 'look_up' | 'images' | 'plan' | 'rafii';

export interface SlashCommand {
  name: string;
  aliases: string[];
  group: CommandGroup;
  description: string;
  argsHint?: string;
  kind: 'client' | 'agent';
  /** Client commands only: runs in the browser through the panel actions; resolves to a short confirmation or null. */
  execute?: (args: string) => Promise<string | null> | string | null;
}

export const COMMANDS: SlashCommand[] = [];

/** `/name args` at the start of a message → the command and its arguments, or null for plain text. */
export function parseSlash(text: string): { command: SlashCommand; args: string } | null {
  const match = /^[/／](\S+)\s*([\s\S]*)$/.exec(text.trim());
  if (!match) return null;
  const key = match[1].toLowerCase();
  const command = COMMANDS.find((c) => c.name === key || c.aliases.includes(key));
  return command ? { command, args: match[2].trim() } : null;
}
