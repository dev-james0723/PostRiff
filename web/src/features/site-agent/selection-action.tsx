'use client';

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { panelStore } from './store';
import { readSelectedText, selectionQuestion } from './text-selection';

/** A visible, explicit handoff to the existing composer; no new conversation and no automatic turn. */
export function SelectionAction() {
  const pathname = usePathname();
  const { workspaceId } = useWorkspaceApi();
  const [selected, setSelected] = useState<{ text: string; workspaceId: string; pathname: string } | null>(null);
  useEffect(() => {
    let frame = 0;
    const read = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const text = readSelectedText(document);
        setSelected(text && workspaceId ? { text, workspaceId, pathname } : null);
      });
    };
    document.addEventListener('selectionchange', read);
    return () => { document.removeEventListener('selectionchange', read); cancelAnimationFrame(frame); };
  }, [workspaceId, pathname]);
  if (!selected || selected.workspaceId !== workspaceId || selected.pathname !== pathname) return null;
  // The header's backdrop filter establishes a fixed-position containing block. Escape it so the action
  // stays in the viewport on phones and remains above the bottom navigation.
  return createPortal(<div data-rafii-selection-action className='fixed bottom-24 left-1/2 z-40 max-w-[calc(100vw-2rem)] -translate-x-1/2 md:bottom-5'>
    <Button variant='glass' className='min-h-11 shadow-lg' onPointerDown={(event) => event.preventDefault()} onClick={() => {
      const current = readSelectedText(document);
      if (current && workspaceId) panelStore.ask(selectionQuestion(current, pathname), workspaceId);
      setSelected(null);
    }}>Ask Rafii about selection</Button>
  </div>, document.body);
}
