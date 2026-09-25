'use client';

/** The `/` command menu. Stub until the commands slice lands; keeps the exported name and props stable. */
import type { RefObject } from 'react';
import type { SlashCommand } from '@/lib/agent-runtime/commands';

export interface SlashCommandMenuProps {
  value: string;
  caret: number;
  anchorRef: RefObject<HTMLElement | null>;
  onPick: (command: SlashCommand, args: string) => void;
  onDismiss: () => void;
}

export function SlashCommandMenu(_props: SlashCommandMenuProps) {
  return null;
}
