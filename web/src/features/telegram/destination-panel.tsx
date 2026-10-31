'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useWorkspaceAccess, checkAccess } from '@/lib/auth/access';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { TelegramOperation } from './types';

const labels: Record<string,string> = { publish: 'Publishing', comments_read: 'Read observed comments/replies', schedule: 'Rafii scheduling', detailed_analytics: 'Native statistics', story_publish: 'Stories', story_analytics: 'Story analytics', telegraph: 'Telegraph articles', business_stories: 'Business stories' };
const human = (s:string) => labels[s] || s.replaceAll('_',' ');
export function TelegramDestinationPanel({ connectionId }: { connectionId: string }) {
  const { api, workspaceId } = useWorkspaceApi(), access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission:'manage_connections' });
  const live = useQuery({ queryKey:[workspaceId,'telegram',connectionId], queryFn:()=>api.telegramInspect(workspaceId,connectionId) });
  const inbox = useQuery({ queryKey:[workspaceId,'telegram-inbox',connectionId], queryFn:()=>api.telegramInbox(workspaceId,connectionId) });
  const analytics = useQuery({ queryKey:[workspaceId,'telegram-analytics',connectionId], queryFn:()=>api.telegramAnalytics(workspaceId,connectionId) });
  const targets = useQuery({queryKey:[workspaceId,'telegram-destinations'],queryFn:()=>api.telegramDestinations(workspaceId)});
  const [action,setAction] = useState('reply'), [mid,setMid] = useState(''), [text,setText] = useState(''), [mode,setMode] = useState('plain');
  const [target,setTarget] = useState(''), [sendDate,setSendDate] = useState('');
  const [operation,setOperation] = useState<TelegramOperation | null>(null), [busy,setBusy] = useState(false);
  const selected = inbox.data?.messages.find(m => String(m.message.message_id)===mid);
  const cap = action==='reply'?'reply':action.startsWith('edit_')?'edit_own':action==='delete'?'delete_own':action==='pin'||action==='unpin'?'pin':action==='stop_poll'?'poll':action==='approve_suggestion'?'approve_suggested_post':action==='decline_suggestion'?'decline_suggested_post':action;
  const allowed = Boolean(live.data?.capabilities[cap]?.enabled && checkAccess(access,{permission:action==='reply'?'reply':action==='decline_suggestion'?'moderate':'approve'}));
  async function prepare() {
    setBusy(true);
    try { setOperation(await api.telegramPrepare(workspaceId,connectionId,{action,messageId:Number(mid),...(['reply','edit_text','edit_caption'].includes(action)?{text,parseMode:mode}:{}),...(action==='forward'||action==='copy'?{destinationConnectionId:target}:{}),...(action==='approve_suggestion'&&sendDate?{sendDate:Math.floor(new Date(sendDate).getTime()/1000)}:{}),...(action==='decline_suggestion'&&text?{comment:text}:{})})); }
    catch(e) { toast.error(e instanceof Error?e.message:'Could not prepare Telegram operation'); }
    finally { setBusy(false); }
  }
  async function execute() {
    if (!operation) return;
    setBusy(true);
    try { const result=await api.telegramExecute(workspaceId,connectionId,{operationId:operation.operationId,digest:operation.digest,confirmed:true}); toast[result.state==='confirmed'?'success':'error'](`Telegram: ${result.state}`,{description:result.reason}); setOperation(null); await inbox.refetch(); await analytics.refetch(); }
    catch(e) { toast.error(e instanceof Error?e.message:'Telegram operation unavailable'); }
    finally { setBusy(false); }
  }
  const clear = () => setOperation(null);
  return <section aria-label='Telegram destination details' className='space-y-4 rounded-xl border p-4'>
    <div className='flex flex-wrap items-center justify-between gap-2'><h2 className='font-medium'>Telegram destination</h2><Button variant='quiet' disabled={!canManage||busy} onClick={async()=>{setBusy(true);try{await api.telegramInspect(workspaceId,connectionId,true);await live.refetch();toast.success('Telegram rights reverified');}catch(e){toast.error(e instanceof Error?e.message:'Verification failed');}finally{setBusy(false);}}}>Reverify permissions</Button></div>
    {live.isPending?<p role='status'>Verifying Telegram…</p>:live.isError?<p role='alert'>{live.error instanceof Error?live.error.message:'Telegram verification unavailable'}</p>:live.data&&<>
      <p>{live.data.title} {live.data.username&&`(@${live.data.username})`}</p><p className='text-muted-foreground text-xs'>ID {live.data.chatId} · {human(live.data.destinationType)} · {live.data.connectionType==='business'?'Business connection':'Bot connection'} · membership {live.data.membership}</p>
      <p className='text-sm'>{live.data.availableCapabilities}/{live.data.totalCapabilities} capabilities available · Scheduling: Rafii-managed</p><p className='text-muted-foreground text-xs'>Last verified {new Date(live.data.lastVerifiedAt*1000).toLocaleString()}</p>
      {live.data.readiness==='candidate'&&<p role='status' className='text-xs'>Private Preview test destination. Actions still require your approval and current Telegram rights. Real acceptance is in progress.</p>}
      <details><summary className='cursor-pointer text-sm'>Actual rights and capabilities</summary><dl className='mt-2 grid gap-2 text-xs'>{Object.entries(live.data.administratorRights).map(([right,granted])=><div key={right} className='flex justify-between gap-3'><dt>{human(right)}</dt><dd>{granted?'Granted':'Missing'}</dd></div>)}{Object.entries(live.data.businessState?.rights??{}).map(([right,granted])=><div key={right}><dt>{human(right)}</dt><dd>{granted?'Granted':'Missing'}</dd></div>)}</dl><table className='mt-3 w-full text-left text-xs'><thead><tr><th scope='col'>Capability</th><th scope='col'>State</th></tr></thead><tbody>{Object.entries(live.data.capabilities).map(([name,c])=><tr key={name} className='border-t'><td className='py-2 pr-2'>{human(name)}{c.limitation&&<p className='text-muted-foreground'>{c.limitation}</p>}</td><td>{human(c.state)}{c.missingRights.length>0&&<p>{c.missingRights.join(', ')}</p>}</td></tr>)}</tbody></table></details>
      {live.data.linkedDiscussionChatId&&<p className='text-xs'>Linked discussion chat: {live.data.linkedDiscussionChatId}. Connect that group separately to observe comments.</p>}
    </>}
    <div className='space-y-2'><h3 className='text-sm font-medium'>Observed engagement</h3><p className='text-muted-foreground text-xs'>Coverage begins when Rafii receives updates. Native Telegram channel view statistics are unavailable through this connection.</p>{analytics.data&&<dl className='grid gap-2 text-xs'><div>Delivery receipts: {analytics.data.deliveryReceipts.value} · Rafii-derived</div><div>Observed replies: {analytics.data.observedReplies.value} · Bot-observed</div><div>Native views: unavailable</div>{analytics.data.metrics.filter(m=>m.metric==='reactions'||m.metric==='poll_results').map((m,i)=><div key={i}>#{m.messageId} · {human(m.metric)} · {JSON.stringify(m.value)} · Bot-observed</div>)}</dl>}</div>
    <div className='space-y-2'><h3 className='text-sm font-medium'>Inbox and published messages</h3><p className='text-muted-foreground text-xs'>Bot-observed messages only. Ordinary Telegram deletions are not reported by the Bot API.</p>{inbox.data?.messages.slice(0,25).map(({message:m,deleted,rafiiJobId})=><article key={m.message_id} className='rounded-md border p-2 text-xs'><p>#{m.message_id} · {new Date(m.date*1000).toLocaleString()}{m.message_thread_id&&` · Topic ${m.message_thread_id}`}{m.direct_messages_topic&&` · DM topic ${m.direct_messages_topic.topic_id}`}{m.reply_to_message&&` · Reply to #${m.reply_to_message.message_id}`}{rafiiJobId&&' · Rafii receipt'}{deleted&&' · Deleted'}</p><p className='mt-1 whitespace-pre-wrap'>{m.text||m.caption||m.poll?.question||'Media message'}</p>{!deleted&&<Button variant='quiet' size='sm' onClick={()=>{setMid(String(m.message_id));setText('');clear();}}>Select #{m.message_id}</Button>}</article>)}</div>
    <fieldset className='space-y-2 rounded-lg border p-3'><legend className='px-1 text-sm'>Reply or manage a recorded message</legend><Label>Message<select aria-label='Telegram operation message' className='bg-background mt-1 w-full rounded border p-2' value={mid} onChange={e=>{setMid(e.target.value);clear();}}><option value=''>Choose an observed message</option>{inbox.data?.messages.filter(m=>!m.deleted).map(({message:m})=><option key={m.message_id} value={m.message_id}>#{m.message_id} · {(m.text||m.caption||m.poll?.question||'Media').slice(0,60)}</option>)}</select></Label>
      <Label>Action<select aria-label='Telegram operation action' className='bg-background mt-1 w-full rounded border p-2' value={action} onChange={e=>{setAction(e.target.value);clear();}}>{['reply',...(selected?.rafiiJobId?[...(selected.message.text?['edit_text']:['edit_caption']),'delete','pin','unpin',...(selected.message.poll?['stop_poll']:[])]:[]),'forward','copy',...(selected?.message.suggested_post_info?['approve_suggestion','decline_suggestion']:[])].map(a=><option key={a} value={a}>{human(a)}</option>)}</select></Label>
      {['reply','edit_text','edit_caption','decline_suggestion'].includes(action)&&<><Label>Message text<textarea aria-label='Telegram operation text' className='bg-background mt-1 min-h-24 w-full rounded border p-2' value={text} onChange={e=>{setText(e.target.value);clear();}} /></Label><select aria-label='Telegram operation formatting' value={mode} onChange={e=>{setMode(e.target.value);clear();}}><option value='plain'>Plain text</option><option value='HTML'>Telegram HTML</option><option value='MarkdownV2'>MarkdownV2</option></select></>}
      {['forward','copy'].includes(action)&&<Label>Receiving destination<select aria-label='Telegram receiving destination' className='bg-background w-full rounded border p-2' value={target} onChange={e=>{setTarget(e.target.value);clear();}}><option value=''>Choose destination</option>{targets.data?.destinations.map(d=><option key={d.connectionId} value={d.connectionId}>{d.title}</option>)}</select></Label>}
      {action==='approve_suggestion'&&<><Input aria-label='Suggested post publish time' type='datetime-local' value={sendDate} onChange={e=>{setSendDate(e.target.value);clear();}}/><p className='text-xs'>Unpaid suggestions only. Leave time empty to approve for immediate publishing.</p></>}
      {!allowed&&<p role='status' className='text-muted-foreground text-xs'>This action is unavailable for your workspace role, current Telegram rights or acceptance state.</p>}
      <Button variant='glass' disabled={!allowed||!mid||busy} onClick={()=>void prepare()}>Prepare Telegram action</Button>
      {operation&&<div className='space-y-2 rounded border p-3' aria-label='Telegram action preview'><p className='text-sm'>Review {human(action)} · #{mid} · {live.data?.title}</p>{text&&<p className='whitespace-pre-wrap text-sm'>{text}</p>}{['forward','copy'].includes(action)&&<p className='text-sm'>Send to {targets.data?.destinations.find(d=>d.connectionId===target)?.title}</p>}<p className='text-xs'>This confirmation performs the displayed action in Telegram.</p><Button variant='action' disabled={busy} onClick={()=>void execute()}>Confirm {human(action)}</Button><Button variant='quiet' disabled={busy} onClick={clear}>Cancel action</Button></div>}
    </fieldset>
  </section>;
}
