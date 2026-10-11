'use client';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { Asset } from '@/lib/api/types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import type { TelegramFile } from './types';

const formats = ['text', 'photo', 'album', 'video', 'animation', 'live_photo', 'audio', 'voice', 'video_note', 'document', 'poll'];
const label = (s: string) => s.replaceAll('_', ' ');
export function TelegramComposerFields({ channelId, assets, selectedIds, onSelect, text, onChange }: {
  channelId: string; assets: Asset[]; selectedIds: string[]; onSelect: (ids: string[]) => void;
  text: string; onChange: (v: Record<string, unknown> | null) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const target = useQuery({ queryKey: [workspaceId, 'telegram', channelId], queryFn: () => api.telegramInspect(workspaceId, channelId) });
  const inbox = useQuery({ queryKey: [workspaceId, 'telegram-inbox', channelId], queryFn: () => api.telegramInbox(workspaceId, channelId) });
  const files = useQuery({ queryKey: [workspaceId, 'telegram-files', channelId], queryFn: () => api.telegramFiles(workspaceId, channelId) });
  const [format, setFormat] = useState('text');
  const [parseMode, setMode] = useState('plain');
  const [silent, setSilent] = useState(false), [protect, setProtect] = useState(false), [spoiler, setSpoiler] = useState(false);
  const [omit, setOmit] = useState(false), [thumbnail, setThumbnail] = useState(false), [stream, setStream] = useState(false);
  const [preview, setPreview] = useState(true), [above, setAbove] = useState(false), [previewUrl, setPreviewUrl] = useState(''), [size, setSize] = useState('default');
  const [topic, setTopic] = useState(''), [reply, setReply] = useState('');
  const [buttonText, setButtonText] = useState(''), [buttonUrl, setButtonUrl] = useState(''), [buttonKind, setButtonKind] = useState('url');
  const [pollOptions, setPollOptions] = useState(''), [quiz, setQuiz] = useState(false), [correct, setCorrect] = useState('1'), [multi, setMulti] = useState(false), [anonymous, setAnonymous] = useState(true);
  const [revote, setRevote] = useState(false), [shuffle, setShuffle] = useState(false), [dynamic, setDynamic] = useState(false), [hide, setHide] = useState(false), [explanation, setExplanation] = useState(''), [closePeriod, setClosePeriod] = useState('');
  const [chosenFiles, setFiles] = useState<TelegramFile[]>([]), [fileChoice, setFileChoice] = useState('');
  const [title, setTitle] = useState(''), [performer, setPerformer] = useState(''), [start, setStart] = useState('');
  const cap = target.data?.capabilities[format];
  const topics = inbox.data?.topics.filter(t => !t.closed) ?? [];
  const needsTopic = target.data?.destinationType === 'forum_supergroup' || target.data?.destinationType === 'channel_dm';
  const approvedTopic = topic || String(target.data?.messageThreadId ?? target.data?.directMessagesTopicId ?? '');
  const optionLines = useMemo(() => pollOptions.split('\n').map(s => s.trim()).filter(Boolean), [pollOptions]);
  const count = selectedIds.length + chosenFiles.length;
  const mediaFormat = !['text', 'poll'].includes(format);
  const albumKinds = new Set([...selectedIds.map(id => assets.find(a=>a.id===id)?.mime.startsWith('video/')?'video':'photo'),...chosenFiles.map(f=>f.kind)]);
  const albumCapability = albumKinds.has('live_photo')?'live_photo_album':albumKinds.size===1?`${Array.from(albumKinds)[0]}_album`:'mixed_album';
  const complete = Boolean(cap?.enabled && target.data?.capabilities.publish?.enabled && (!needsTopic || approvedTopic)
    && (target.data?.destinationType!=='channel_dm'||target.data.capabilities.channel_dm?.enabled)
    && (target.data?.destinationType!=='forum_supergroup'||target.data.capabilities.topics?.enabled)
    && (parseMode==='plain' || target.data?.capabilities.text_formatting?.enabled)
    && (format!=='album' || target.data?.capabilities[albumCapability]?.enabled)
    && (!mediaFormat || (format === 'album' ? count >= 2 && count <= 10 : format === 'live_photo' ? count === 2 : count === 1))
    && (mediaFormat || count === 0) && (format !== 'video_note' || omit || !text)
    && (format !== 'poll' || optionLines.length >= 1 && optionLines.length <= 12)
    && (!buttonText || buttonUrl) && (!buttonText || format !== 'album'));
  useEffect(() => {
    if (!complete) { onChange(null); return; }
    const t: Record<string, unknown> = { format, parseMode, silent, protectContent: protect };
    if (format === 'video_note' && omit) t.omitCaption = true;
    if (chosenFiles.length) t.fileIds = chosenFiles.map(({fileId, kind, recordId}) => ({fileId,kind,recordId}));
    if (approvedTopic) t[target.data?.destinationType === 'channel_dm' ? 'directMessagesTopicId' : 'messageThreadId'] = Number(approvedTopic);
    if (reply) t.replyToMessageId = Number(reply);
    if (format === 'text') t.linkPreview = { is_disabled: !preview, ...(previewUrl ? { url: previewUrl } : {}), show_above_text: above, ...(size === 'small' ? { prefer_small_media: true } : size === 'large' ? { prefer_large_media: true } : {}) };
    if (buttonText) t.buttons = [[{ text: buttonText, ...(buttonKind === 'copy' ? { copy_text: { text: buttonUrl } } : buttonKind === 'web_app' ? { web_app: { url: buttonUrl } } : { url: buttonUrl }) }]];
    const mo: Record<string, unknown> = {};
    if (['photo','album','video','animation','live_photo'].includes(format)) mo.has_spoiler = spoiler;
    if (format === 'video') { mo.supports_streaming = stream; if (start) mo.start_timestamp = Number(start); }
    if (['video','animation','video_note'].includes(format) && thumbnail) mo.useThumbnail = true;
    if (format === 'audio') { if (title) mo.title = title; if (performer) mo.performer = performer; }
    if (Object.keys(mo).length) t.mediaOptions = mo;
    if (format === 'poll') t.poll = { question: text, options: optionLines.map(s => ({ text: s })), type: quiz ? 'quiz' : 'regular', is_anonymous: anonymous, allows_multiple_answers: multi, allows_revoting: revote, shuffle_options: shuffle, allow_adding_options: dynamic, hide_results_until_closes: hide, ...(quiz ? { correct_option_ids: correct.split(',').map(s => Number(s.trim()) - 1).toSorted((a,b) => a-b), ...(explanation ? { explanation } : {}) } : {}), ...(closePeriod ? { open_period: Number(closePeriod) } : {}) };
    onChange({ telegram: t });
  }, [complete, format, parseMode, silent, protect, omit, chosenFiles, approvedTopic, target.data?.destinationType, reply, preview, previewUrl, above, size, buttonText, buttonUrl, buttonKind, spoiler, stream, start, thumbnail, title, performer, optionLines, quiz, anonymous, multi, revote, shuffle, dynamic, hide, correct, explanation, closePeriod, text, onChange]);
  return <fieldset className='space-y-3 rounded-xl border p-3' aria-label='Telegram post controls'>
    <legend className='px-1 text-sm font-medium'>Telegram</legend>
    <p className='text-muted-foreground text-xs'>Scheduling: Rafii-managed. Telegram controls its own link preview.</p>
    {target.isPending ? <p role='status'>Checking destination permissions…</p> : target.isError ? <p role='alert'>Destination verification unavailable. Reconnect in Channels.</p> : <p className='text-xs'>{target.data?.title} · {target.data?.destinationType.replaceAll('_',' ')} · {target.data?.availableCapabilities}/{target.data?.totalCapabilities} capabilities available</p>}
    <Label>Telegram format<select aria-label='Telegram format' className='bg-background mt-1 w-full rounded-md border p-2' value={format} onChange={e => { setFormat(e.target.value); setFiles([]); onSelect([]); }}>
      {formats.map(f => <option key={f} value={f}>{label(f)}{target.data?.capabilities[f]?.enabled ? '' : ' — unavailable'}</option>)}
    </select></Label>
    {!cap?.enabled && <p role='status' className='text-muted-foreground text-xs'>{cap?.state === 'requires_e2e' ? 'Disabled until this destination passes real Telegram acceptance tests.' : label(cap?.state ?? 'verification required')} {cap?.missingRights?.join(', ')}</p>}
    <Label>Telegram formatting<select aria-label='Telegram formatting' className='bg-background mt-1 w-full rounded-md border p-2' value={parseMode} onChange={e => setMode(e.target.value)}><option value='plain'>Plain text</option><option value='HTML'>Telegram HTML</option><option value='MarkdownV2'>MarkdownV2 (strict subset)</option></select></Label>
    {mediaFormat && <div className='space-y-2'>
      <p className='text-xs'>Select library files in publication order. Albums stay one Telegram media group. Live Photo: select a video and its still image.</p>
      {assets.map(a => <Label key={a.id} className='flex items-center gap-2 text-xs'><Checkbox checked={selectedIds.includes(a.id)} onCheckedChange={v => onSelect(v === true ? [...selectedIds,a.id] : selectedIds.filter(id => id !== a.id))} />{a.id} · {a.mime}</Label>)}
      <Label>Reuse a recorded Telegram file<select aria-label='Recorded Telegram file' className='bg-background w-full rounded-md border p-2' value={fileChoice} onChange={e => setFileChoice(e.target.value)}><option value=''>Choose a file</option>{files.data?.files.map(f => <option value={f.recordId} key={f.recordId}>{f.kind} · {f.descriptor.file_name || f.descriptor.title || f.recordId}</option>)}</select></Label>
      <Button type='button' variant='quiet' disabled={!fileChoice} onClick={() => { const f = files.data?.files.find(f => f.recordId === fileChoice); if (f && !chosenFiles.some(c => c.recordId === f.recordId)) setFiles([...chosenFiles,f]); }}>Add recorded file</Button>
      {chosenFiles.map(f => <Button type='button' variant='quiet' key={f.recordId} onClick={() => setFiles(chosenFiles.filter(c => c.recordId !== f.recordId))}>{f.kind} · Remove</Button>)}
    </div>}
    {needsTopic && <Label>Telegram topic<select aria-label='Telegram topic' className='bg-background mt-1 w-full rounded-md border p-2' value={approvedTopic} onChange={e => setTopic(e.target.value)}><option value=''>Select an observed topic</option>{topics.map(t => <option key={t.id} value={t.id}>{t.title || `Topic ${t.id}`}</option>)}</select></Label>}
    <Label>Reply to an observed message<select aria-label='Telegram reply target' className='bg-background mt-1 w-full rounded-md border p-2' value={reply} onChange={e => setReply(e.target.value)}><option value=''>New post</option>{inbox.data?.messages.filter(m => !m.deleted).map(({message:m}) => <option key={m.message_id} value={m.message_id}>#{m.message_id} · {(m.text || m.caption || m.poll?.question || 'Media').slice(0,60)}</option>)}</select></Label>
    {format === 'text' && <div className='space-y-2'>
      <Label className='flex items-center gap-2'><Checkbox checked={preview} onCheckedChange={v=>setPreview(v===true)} />Enable link preview</Label>
      {preview && <><Input aria-label='Telegram preview URL' placeholder='Preview URL (optional)' value={previewUrl} onChange={e=>setPreviewUrl(e.target.value)} /><Label className='flex items-center gap-2'><Checkbox checked={above} onCheckedChange={v=>setAbove(v===true)} />Preview above text</Label><select aria-label='Telegram preview size' value={size} onChange={e=>setSize(e.target.value)}><option value='default'>Telegram preview size</option><option value='small'>Prefer small</option><option value='large'>Prefer large</option></select></>}
    </div>}
    {format === 'poll' && <div className='space-y-2'>
      <Label>Poll options (one per line)<textarea aria-label='Telegram poll options' className='bg-background mt-1 w-full rounded-md border p-2' value={pollOptions} onChange={e=>setPollOptions(e.target.value)} /></Label>
      {[['Quiz',quiz,setQuiz],['Anonymous',anonymous,setAnonymous],['Multiple answers',multi,setMulti],['Allow revoting',revote,setRevote],['Shuffle options',shuffle,setShuffle],['Allow voters to add options',dynamic,setDynamic],['Hide results until closed',hide,setHide]].map(([name,value,setter])=><Label key={String(name)} className='flex items-center gap-2 text-xs'><Checkbox checked={Boolean(value)} onCheckedChange={v=>(setter as (v:boolean)=>void)(v===true)} />{String(name)}</Label>)}
      {quiz && <><Input aria-label='Quiz correct options' placeholder='Correct option numbers, e.g. 1,3' value={correct} onChange={e=>setCorrect(e.target.value)} /><Input aria-label='Quiz explanation' placeholder='Quiz explanation' value={explanation} onChange={e=>setExplanation(e.target.value)} maxLength={200} /></>}
      <Input aria-label='Poll open period' type='number' placeholder='Open period in seconds (optional)' value={closePeriod} onChange={e=>setClosePeriod(e.target.value)} />
    </div>}
    {format !== 'album' && <div className='grid gap-2'><Input aria-label='Telegram button label' placeholder='CTA button label (optional)' value={buttonText} onChange={e=>setButtonText(e.target.value)} />{buttonText && <><select aria-label='Telegram button action' value={buttonKind} onChange={e=>setButtonKind(e.target.value)}><option value='url'>Open URL</option><option value='copy'>Copy text</option>{target.data?.destinationType==='user_dm' && target.data.connectionType==='bot' && <option value='web_app'>Mini App</option>}</select><Input aria-label='Telegram button destination' placeholder={buttonKind==='copy'?'Text to copy':'https://…'} value={buttonUrl} onChange={e=>setButtonUrl(e.target.value)} /></>}</div>}
    {format === 'video_note' && <Label className='flex items-center gap-2 text-xs'><Checkbox checked={omit} onCheckedChange={v=>setOmit(v===true)} />Omit the draft text: Video Notes cannot carry captions.</Label>}
    {['photo','album','video','animation','live_photo'].includes(format) && <Label className='flex items-center gap-2 text-xs'><Checkbox checked={spoiler} onCheckedChange={v=>setSpoiler(v===true)} />Media spoiler</Label>}
    {['video','animation','video_note'].includes(format) && <Label className='flex items-center gap-2 text-xs'><Checkbox checked={thumbnail} onCheckedChange={v=>setThumbnail(v===true)} />Use the verified video poster as a thumbnail</Label>}
    {format==='video' && <><Label className='flex items-center gap-2 text-xs'><Checkbox checked={stream} onCheckedChange={v=>setStream(v===true)} />Supports streaming</Label><Input aria-label='Video start timestamp' type='number' placeholder='Start timestamp (seconds)' value={start} onChange={e=>setStart(e.target.value)} /></>}
    {format==='audio' && <><Input aria-label='Audio title' placeholder='Audio title' value={title} onChange={e=>setTitle(e.target.value)} /><Input aria-label='Audio performer' placeholder='Performer' value={performer} onChange={e=>setPerformer(e.target.value)} /></>}
    <Label className='flex items-center gap-2 text-xs'><Checkbox checked={silent} onCheckedChange={v=>setSilent(v===true)} />Silent notification</Label>
    <Label className='flex items-center gap-2 text-xs'><Checkbox checked={protect} onCheckedChange={v=>setProtect(v===true)} />Protect content from forwarding and saving</Label>
    <div aria-label='Telegram preview' className='bg-muted rounded-lg p-3 text-sm whitespace-pre-wrap'><p className='text-xs font-medium'>{target.data?.title || 'Telegram destination'} · {label(format)}</p>{parseMode!=='plain'&&<p className='text-muted-foreground text-xs'>Formatting source: Rafii parses and validates these entities when preparing the exact review.</p>}<p>{format==='video_note' && omit ? 'Circular video · caption omitted by your choice' : text}</p>{format==='poll' && optionLines.map((s,i)=><p key={i}>○ {s}</p>)}{count>0 && <p className='text-muted-foreground text-xs'>{count} media dependencies</p>}{buttonText && <p className='mt-2 rounded border p-2 text-center'>{buttonText}</p>}</div>
  </fieldset>;
}
