'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import type { SnapshotSource } from '@/lib/api/types';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sources: SnapshotSource[];
  selected: string[];
  onApply: (ids: string[]) => void;
}

/** Selected context is distinct from permission to quote, learn or send to a provider. */
export function ContextPocket({open,onOpenChange,sources,selected,onApply}:Props) {
  const [staged,setStaged]=useState(selected);
  useEffect(()=>{if(open)setStaged(selected);},[open,selected]);
  const visible=sources.filter(source=>source.kind!=='voice_sample');
  const eligible=visible.filter(source=>source.active&&source.sourcePolicy!=='prohibited');
  function toggle(id:string){setStaged(current=>current.includes(id)?current.filter(value=>value!==id):current.length<20?[...current,id]:current);}
  return <RafiiDialog open={open} onOpenChange={onOpenChange}>
    <RafiiDialogContent size='md'>
      <RafiiDialogHeader title='Context' intro='Choose what this draft may draw from.' closeLabel='Close context' />
      <RafiiDialogBody className='flex flex-col gap-3'>
        {visible.length===0&&<p className='text-muted-foreground text-sm'>No sources yet. Your idea is enough to start.</p>}
        {visible.map(source=>{
          const allowed=eligible.some(item=>item.id===source.id);
          return <label key={source.id} className='rafii-quiet flex min-h-14 items-start gap-3 rounded-xl p-3'>
            <input type='checkbox' aria-label={source.title||'Untitled source'} checked={staged.includes(source.id)} disabled={!allowed||(!staged.includes(source.id)&&staged.length>=20)} onChange={()=>toggle(source.id)} className='mt-1' />
            <span className='flex min-w-0 flex-col gap-1'><span className='text-sm'>{source.title||'Untitled source'}</span>
              <span className='text-muted-foreground text-xs'>{!allowed?'Unavailable':source.sourcePolicy==='public_quote'?'Approved quotation rules apply':source.sourcePolicy==='internal_reference'?'Reference only':'Review required before public use'}</span>
            </span>
          </label>;
        })}
        <p className='text-muted-foreground text-xs'>Existing source and model permissions still apply. Selecting a source does not grant new access.</p>
        <Link href='/app/ideas' className='rafii-focus inline-flex min-h-11 items-center self-start rounded-lg text-sm underline'>Manage sources</Link>
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <Button variant='glass' onClick={()=>onOpenChange(false)}>Cancel</Button>
        <Button variant='action' onClick={()=>{onApply(staged.filter(id=>eligible.some(source=>source.id===id)));onOpenChange(false);}}>Use context · {staged.length}</Button>
      </RafiiDialogFooter>
    </RafiiDialogContent>
  </RafiiDialog>;
}
