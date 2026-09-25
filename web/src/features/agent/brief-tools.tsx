'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';

interface Props {
  text: string;
  onChange: (text: string) => void;
  onSave: () => void;
  onClear: () => void;
  saved: string | null;
  busy: boolean;
}

/** The expanded editor shares the same input. Save is explicitly session-only. */
export function BriefTools({text,onChange,onSave,onClear,saved,busy}:Props) {
  const [expanded,setExpanded]=useState(false);
  return <>
    <div className='flex flex-wrap items-center justify-between gap-2 px-2 pb-2'>
      <span role='status' className='text-muted-foreground text-xs'>{saved===null?'New brief':saved===text?'Saved for this session':'Unsaved changes'}</span>
      <div className='flex gap-1'>
        <Button variant='quiet' size='sm' disabled={busy} onClick={()=>setExpanded(true)}>Expand</Button>
        <Button variant='quiet' size='sm' disabled={busy||!text.trim()||text===saved} onClick={onSave}>Save brief</Button>
        {saved!==null&&<Button variant='quiet' size='sm' disabled={busy} onClick={onClear}>Clear saved brief</Button>}
      </div>
    </div>
    <RafiiDialog open={expanded} onOpenChange={setExpanded}>
      <RafiiDialogContent size='lg'>
        <RafiiDialogHeader title='Writing space' closeLabel='Close writing space' />
        <RafiiDialogBody>
          <Textarea aria-label='Expanded message' value={text} onChange={event=>onChange(event.target.value)} maxLength={20000} rows={14} disabled={busy} className='rafii-field min-h-[40dvh] text-base leading-relaxed' />
          <p className='text-muted-foreground mt-3 text-xs'>{text.length.toLocaleString()} / 20,000 characters</p>
        </RafiiDialogBody>
        <RafiiDialogFooter><Button variant='action' onClick={()=>setExpanded(false)}>Done writing</Button></RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  </>;
}
