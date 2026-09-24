'use client';

import { cloneElement, Suspense, lazy, useState, type ButtonHTMLAttributes, type ReactElement, type ReactNode } from 'react';

const PickerContent = lazy(() => import('./language-picker-content').then((module) => ({ default: module.LanguagePicker })));

export interface PickerAction {
  label: ReactNode;
  onClick: () => void;
  quiet?: boolean;
}

export interface LanguagePickerProps {
  /** The element that opens the list (a button); its own children stay as they are. */
  trigger: ReactElement;
  /** "Language for Xiaohongshu", "Add a language for Instagram". */
  title: string;
  /** Tags shown with a check. */
  selected: string[];
  onPick: (tag: string) => void;
  suggestions?: { tag: string; reason: string }[];
  actions?: PickerAction[];
  disabled?: boolean;
}

/** Keep the existing trigger available while the search/drawer code loads on first use. */
export function LanguagePicker(props: LanguagePickerProps) {
  const [activated, setActivated] = useState(false);
  const trigger = props.trigger as ReactElement<ButtonHTMLAttributes<HTMLButtonElement>>;
  const entry = cloneElement(trigger, {
    disabled: props.disabled,
    'aria-haspopup': 'dialog',
    'aria-expanded': false,
    'aria-busy': activated || undefined,
    onClick: (event) => {
      trigger.props.onClick?.(event);
      if (!event.defaultPrevented) setActivated(true);
    }
  });
  if (!activated) return entry;
  return <Suspense fallback={entry}><PickerContent {...props} defaultOpen /></Suspense>;
}
