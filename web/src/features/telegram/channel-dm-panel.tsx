'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useWorkspaceAccess,checkAccess } from '@/lib/auth/access';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import type { TelegramDestination } from './types';

export function TelegramChannelDmPanel({destinations,onConnected}:{destinations:TelegramDestination[];onConnected:()=>Promise<unknown>}) {
  const {api,workspaceId}=useWorkspaceApi(),access=useWorkspaceAccess();
  const canManage=checkAccess(access,{permission:'manage_connections'});
  const inbox=useQuery({queryKey:[workspaceId,'telegram-channel-dm'],queryFn:()=>api.telegramChannelDm(workspaceId),enabled:canManage});
  const [parent,setParent]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [operation,setOperation]=useState<{parent:string;action:'authorize'|'select';body:Record<string,unknown>;preview:unknown}|null>(null);
  async function prepare(action:'authorize'|'select',parentId:string,body:Record<string,unknown>){setBusy(true);setError('');try{const v=await api.telegramChannelDmAction(workspaceId,parentId,action,body);setOperation({parent:parentId,action,body,preview:v.preview});}catch(e){setError(e instanceof Error?e.message:'Channel DM verification unavailable');}finally{setBusy(false);}}
  return <section aria-label='Channel Direct Messages' className='space-y-3 rounded-xl border p-4'>
    <h2 className='font-medium'>Channel Direct Messages</h2>
    <p className='text-muted-foreground text-xs'>Authorize conversation discovery separately from channel publishing. Rafii receives accessible incoming topics after consent. Unread state and ordinary deletion detection are unavailable through this Bot API path.</p>
    {error&&<p role='alert' className='text-sm'>{error}</p>}
    <Label>Parent channel<select aria-label='Channel DM parent' className='bg-background w-full rounded border p-2' value={parent} onChange={e=>{setParent(e.target.value);setOperation(null);}}><option value=''>Select a channel with Manage Direct Messages</option>{destinations.filter(d=>['public_channel','private_channel'].includes(d.destinationType)).map(d=><option key={d.connectionId} value={d.connectionId}>{d.title}</option>)}</select></Label>
    <div className='flex flex-wrap gap-2'><Button variant='glass' disabled={!canManage||busy||!parent} onClick={()=>void prepare('authorize',parent,{enabled:true})}>Preview conversation discovery</Button><Button variant='quiet' disabled={!canManage||busy||!parent} onClick={()=>void prepare('authorize',parent,{enabled:false})}>Stop discovering new conversations</Button></div>
    {inbox.data?.conversations.map(c=><div key={`${c.parentConnectionId}/${c.chatId}/${c.topicId}`} className='space-y-1 border-t pt-2 text-sm'><p>{c.title||'Channel conversation'} · Topic {c.topicId}</p><Button variant='glass' disabled={!canManage||busy} onClick={()=>void prepare('select',c.parentConnectionId,{chatId:Number(c.chatId),topicId:c.topicId})}>Preview this DM topic</Button></div>)}
    {operation&&<div className='space-y-2 rounded border p-3'><pre aria-label='Channel DM authorization preview' className='max-h-48 overflow-auto whitespace-pre-wrap text-xs'>{JSON.stringify(operation.preview,null,2)}</pre><Button variant='action' disabled={busy} onClick={()=>{const frozen=operation;setBusy(true);setError('');void api.telegramChannelDmAction(workspaceId,frozen.parent,frozen.action,{...frozen.body,confirmed:true}).then(async()=>{setOperation(null);await inbox.refetch();await onConnected();}).catch(e=>setError(e instanceof Error?e.message:'Channel DM authorization unavailable')).finally(()=>setBusy(false));}}>Confirm Channel DM authorization</Button><Button variant='quiet' disabled={busy} onClick={()=>setOperation(null)}>Cancel Channel DM authorization</Button></div>}
    <Button variant='quiet' disabled={busy||!canManage} onClick={()=>void inbox.refetch()}>Refresh observed conversations</Button>
  </section>;
}
