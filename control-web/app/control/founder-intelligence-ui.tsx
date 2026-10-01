'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Icon } from './founder-preview-ui';
import { href, label, money, scenarioKey, state, type Mode, type Row, type WorkspaceData } from './founder-preview-contracts';

type Mutate = (action:string,targetId:string,value?:string,keepOpen?:boolean)=>Promise<boolean|void>;
function rows(value:unknown):Row[] {return Array.isArray(value)?value as Row[]:[];}
function text(value:unknown):string{return typeof value==='string'?value:typeof value==='number'?String(value):'';}
function intelligence(data?:WorkspaceData):Record<string,unknown>{return data?.intelligence||{};}
function turnLinks(intel:Record<string,unknown>,message:Row){const turn=rows(intel.conversations).flatMap(c=>rows(c.turns)).find(t=>t.runId===message.id);return rows(turn?.links).filter(l=>['invoice','incident'].includes(text(l.kind)));}

export function LinkedRecords({linked,mode}:{linked:Record<string,Row[]>;mode:Mode}) {
 const [tab,setTab]=useState('overview');const groups=[['overview','Overview'],['invoices','Invoices'],['payments','Payments'],['members','Members'],['usage','Usage & credits'],['tickets','Support'],['activity','Timeline']];
 const records=tab==='overview'?[...(linked.workspaces||[]),...(linked.subscriptions||[])]:tab==='usage'?[...(linked.usage||[]),...(linked.credits||[])]:linked[tab]||[];
 return <section className="linked-details"><div className="tabs" aria-label="Customer detail tabs">{groups.map(([id,name])=><button key={id} className="quiet" aria-pressed={tab===id} onClick={()=>setTab(id)}>{name}</button>)}</div>{tab==='overview'&&<div className="detail-summary">{linked.members?.length||0} linked members · {linked.invoices?.length||0} invoices · {linked.tickets?.length||0} support cases</div>}{records.map(r=><article className="linked-record" key={r.id}><div><strong>{text(r.number)||label(r)}</strong><span className={'badge status-'+text(r.status)}>{state(r.status||r.kind||r.dimension)}</span></div>{typeof r.amountMinor==='number'&&<p>{money(r.amountMinor,r.currency)} · {text(r.billingCycle)||text(r.period)}</p>}{typeof r.creditsUsed==='number'&&<><p>{Number(r.creditsUsed).toLocaleString()} / {Number(r.creditsQuota).toLocaleString()} credits</p><progress max={Number(r.creditsQuota)||1} value={Number(r.creditsUsed)}/></>}{text(r.description)||text(r.body)?<p>{text(r.description)||text(r.body)}</p>:null}{text(r.label)&&<p>{text(r.label)}</p>}{['startedAt','renewsAt','issuedAt','paidAt','joinedAt','at'].filter(k=>text(r[k])).map(k=><p className="small" key={k}>{({startedAt:'Started',renewsAt:'Renews',issuedAt:'Issued',paidAt:'Paid',joinedAt:'Joined',at:'Recorded'} as Record<string,string>)[k]}: {new Date(text(r[k])).toLocaleString()}</p>)}{typeof r.balanceAfter==='number'&&<p>{Number(r.quantity).toLocaleString()} credits · balance after: {Number(r.balanceAfter).toLocaleString()} · {state(r.provenance)}</p>}{text(r.role)&&<p>{state(r.role)} · {text(r.email)}</p>}{text(r.cardLast4)&&<p>{state(r.method)} ending {text(r.cardLast4)} · {state(r.providerState)}</p>}{r.lineItems?rows(r.lineItems).map((item,i)=><p className="small" key={i}>{text(item.label)} · {money(item.amountMinor)}</p>):null}{tab==='overview'&&linked.workspaces?.some(w=>w.id===r.id)&&<Link href={href('workspaces',mode,r.id)}>Open workspace →</Link>}</article>)}{!records.length&&<p className="empty">No linked records in this view.</p>}</section>;
}

export function IncidentSurface({data,ask,mutate,busy}:{data:WorkspaceData;ask:(text:string)=>void;mutate:Mutate;busy:boolean}) {
 const intel=intelligence(data);
 const incident=(intel.incident||rows(intel.incidents).at(-1)) as Row|undefined;
 const notifications=rows(intel.notifications);
 const ref=useRef<HTMLDialogElement>(null);
 const [emailId,setEmailId]=useState<string|null>(null),[format,setFormat]=useState('html');
 const email=notifications.find(n=>n.id===emailId);
 const attempts=rows(intel.contactAttempts);
 const affected=rows(incident?.affectedRecords),timeline=rows(incident?.timeline);
 const [clock,setClock]=useState(()=>Date.now());
 useEffect(()=>{if(!notifications.some(n=>n.state==='failed'&&n.attemptId))return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[notifications.some(n=>n.state==='failed'&&n.attemptId)]);
 if(!incident&&!notifications.length)return null;
 function deliver(notification:Row,operation:string,outcome?:string){
  const payload={operation,channel:'email',sourceId:text(notification.sourceId),...(operation==='start'?{}:{attemptId:text(notification.attemptId)}),...(outcome?{outcome}:{})};
  return mutate('founder_delivery',notification.id,JSON.stringify(payload),true);
 }
 return <section id="scenario-incident" className={'panel incident-panel '+(incident?.state==='resolved'?'recovered':'warning')}>
  <div className="panel-heading"><div><p className="eyebrow">Scenario incident · simulated</p><h2>{text(incident?.title)||'Sandbox notifications'}</h2><p>{Array.isArray(incident?.known)?incident.known.map(text).join(' '):''}</p></div><span className="badge">{state(incident?.state||scenarioKey(data))}</span></div>
  {incident&&<>
   <div className="incident-stats"><span><strong>{Number(incident.affectedCount||0).toLocaleString()}</strong> affected accounts</span><span>{text(incident.severity)} severity</span><span>Observed: {text(incident.observedAt)}</span></div>
   <p className="small muted">{Array.isArray(incident.known)?incident.known.map(text).join(' '):''}</p>
   <p className="small muted">Unknown: {Array.isArray(incident.unknown)?incident.unknown.map(text).join(' '):'No further causal evidence recorded.'}</p>
   <div className="row"><button className="quiet" onClick={()=>ask('Explain this incident: who is affected, what is known, what is unknown, and what happens next?')}><Icon name="spark"/>Explain incident</button><button className="quiet" disabled={busy} onClick={()=>ask('Prepare a follow-up on '+text(incident.title)+'. Explain the incident so I can confirm a reminder.')}>Create sandbox follow-up</button></div>
   {affected.length>0&&<details><summary>View affected accounts ({affected.length} shown)</summary><div className="affected-users">{affected.slice(0,10).map((record,index)=><Link key={text(record.customerId)||index} href={href('customers',data.mode,text(record.customerId))}>{text(record.name)||text(record.customerId)} <small>{text(record.workspaceName)}</small><span>→</span></Link>)}</div></details>}
   {timeline.length>0&&<details><summary>Incident timeline</summary>{timeline.map((event,index)=><p className="small" key={event.id||index}>{text(event.at)} · {state(event.type)}</p>)}</details>}
  </>}
  {notifications.length>0&&<div className="notification-outbox"><h3>Founder notification outbox</h3><p className="small muted">Simulated / not actually sent. Provider acceptance, delivery and acknowledgment are separate saved states.</p>{notifications.map(notification=>{
   const attempt=attempts.find(a=>a.id===notification.attemptId);
   const retryAt=attempt?new Date(text(attempt.updatedAt)).getTime()+300000:0;
   const retryReady=!attempt||clock>=retryAt;
   const deliveryState=text(notification.state);
   return <div className="notification-row" key={notification.id}><div><strong>{text(notification.subject)}</strong><small>{text(notification.recipientLabel)} · {state(notification.kind)}</small>{attempt&&<small>Attempt {text(attempt.attemptNumber)} · {text(attempt.id)}</small>}{deliveryState==='failed'&&attempt&&!retryReady&&<small>Retry available after {new Date(retryAt).toLocaleTimeString()}</small>}</div><span className={'badge status-'+deliveryState}>{state(deliveryState)}</span>
    <button className="quiet" onClick={()=>{setEmailId(notification.id);setFormat('html');ref.current?.showModal();}}>Preview email</button>
    {!notification.attemptId&&<button className="quiet" disabled={busy} onClick={()=>deliver(notification,'start')}>{deliveryState==='failed'?'Simulate retry':'Start delivery simulation'}</button>}
    {!!notification.attemptId&&['queued','retrying'].includes(deliveryState)&&<button className="quiet" disabled={busy} onClick={()=>deliver(notification,'advance','provider_accepted')}>Simulate provider acceptance</button>}
    {!!notification.attemptId&&deliveryState==='provider_accepted'&&<button className="quiet" disabled={busy} onClick={()=>deliver(notification,'advance','delivered')}>Simulate delivered</button>}
    {!!notification.attemptId&&deliveryState==='failed'&&<button className="quiet" disabled={busy||!retryReady} onClick={()=>deliver(notification,'retry')}>Simulate retry</button>}
    {!!notification.attemptId&&deliveryState==='delivered'&&<button className="quiet" disabled={busy||notification.acknowledged===true} onClick={()=>deliver(notification,'acknowledge')}>{notification.acknowledged?'Acknowledged':'Acknowledge simulated email'}</button>}
    {!!notification.attemptId&&deliveryState==='ambiguous'&&<p className="small">Outcome unknown. Reconcile before retrying.</p>}
   </div>;
  })}</div>}
  <dialog ref={ref} className="email-dialog" onClose={()=>setEmailId(null)}><div className="panel-heading"><div><p className="eyebrow">Email template preview</p><h2>{text(email?.subject)||'Founder notification'}</h2></div><button className="quiet icon-action" aria-label="Close email preview" onClick={()=>ref.current?.close()}><Icon name="close"/></button></div><p className="demo-caption">Simulated / not actually sent · founder sandbox with no destination selected</p><div className="tabs"><button className="quiet" aria-pressed={format==='html'} onClick={()=>setFormat('html')}>HTML email</button><button className="quiet" aria-pressed={format==='text'} onClick={()=>setFormat('text')}>Plain text</button></div>{format==='html'&&text(email?.html)?<iframe title="Actual notification HTML template" sandbox="" srcDoc={text(email?.html)}/>:<pre>{text(email?.text)||'Template evidence is not available for this notification.'}</pre>}</dialog>
 </section>;
}

function SandboxCall({source,intel,mutate,busy}:{source:Row;intel:Record<string,unknown>;mutate:Mutate;busy:boolean}) {
 const attempt=rows(intel.contactAttempts).filter(a=>a.channel==='call'&&a.sourceId===source.id).at(-1);
 const [question,setQuestion]=useState(''),[error,setError]=useState('');
 const callState=text(attempt?.state),conversationId=text(source.conversationId);
 const report=Array.isArray(source.evidenceRows);
 const latest=rows(intel.messages).filter(message=>message.conversationId===conversationId&&message.role==='assistant').at(-1);
 const summary=rows(intel.summaries).filter(row=>row.conversationId===conversationId).at(-1);
 async function delivery(operation:string,outcome?:string){
  setError('');
  const payload={operation,channel:'call',sourceId:source.id,...(operation==='start'?{}:{attemptId:attempt?.id}),...(outcome?{outcome}:{})};
  const saved=await mutate('founder_delivery',source.id,JSON.stringify(payload),true);
  if(saved===false)setError('Call simulation could not be saved. Review the sandbox error and retry.');
 }
 async function followUp(){
  if(!attempt||!question.trim())return;
  const saved=await mutate('founder_follow_up',source.id,JSON.stringify({attemptId:attempt.id,message:question.trim()}),true);
  if(saved!==false)setQuestion('');
 }
 return <section className="sandbox-call" aria-label={'Sandbox call for '+source.id}>
  <p className="small muted">Call simulation · no phone provider, microphone recording or customer debit. {report?'Uses the stored report evidence.':'Questions during a call require a saved report from this conversation.'}</p>
  {Array.isArray(source.queryReceiptIds)&&<p className="small muted">Evidence: {source.queryReceiptIds.map(text).join(', ')}</p>}
  <div className="row"><span className="badge">{callState?state(callState):'No call requested'}</span>
   {!attempt&&<button className="quiet" disabled={busy} onClick={()=>void delivery('start')}>Start simulated call</button>}
   {callState==='requested'&&<button className="quiet" disabled={busy} onClick={()=>void delivery('advance','dialing')}>Simulate dialing</button>}
   {['dialing','ringing','answered'].includes(callState)&&<button className="quiet" disabled={busy} onClick={()=>void delivery('advance','live')}>Connect simulated call</button>}
   {callState==='live'&&<button className="quiet" disabled={busy} onClick={()=>void delivery('advance','ending')}>End simulated call</button>}
   {callState==='ending'&&<button className="quiet" disabled={busy} onClick={()=>void delivery('advance','completed')}>Complete simulated call</button>}
   {attempt&&['requested','dialing','ringing','answered','live'].includes(callState)&&<button className="quiet" disabled={busy} onClick={()=>void delivery('cancel')}>Cancel simulated call</button>}
   {callState==='completed'&&<><button className="quiet" disabled={busy||!conversationId} onClick={()=>mutate('founder_summary',source.id,JSON.stringify({conversationId}),true)}>Save call summary</button><button className="quiet" disabled={busy||attempt?.acknowledged===true} onClick={()=>void delivery('acknowledge')}>{attempt?.acknowledged?'Acknowledged':'Acknowledge simulated call'}</button></>}
  </div>
  {callState==='live'&&report&&<form onSubmit={event=>{event.preventDefault();void followUp();}}><label>Call follow-up question<input aria-label="Call follow-up question" value={question} onChange={event=>setQuestion(event.target.value)} maxLength={2000} placeholder="Ask about the stored report…" required/></label><button className="quiet" type="submit" disabled={busy||!question.trim()}>Ask during simulated call</button>{latest&&<p className="contact-call-answer">{text(latest.text)}</p>}</form>}
  {summary&&<details><summary>Saved call summary</summary><p>{text(summary.text)}</p><p className="small muted">Human acknowledgment: {summary.humanAcknowledged?'recorded':'not recorded'} · {Number(summary.turnCount||0)} conversation turns</p></details>}
  {error&&<p role="alert">{error}</p>}
 </section>;
}

export function SandboxRecords({data,kind,mutate,busy,ask}:{data:WorkspaceData;kind:string;mutate:Mutate;busy:boolean;ask:(text:string)=>void}) {
 const intel=intelligence(data),reports=rows(intel.reports);
 const items=kind==='followups'?rows(intel.followUps):reports;
 return <section className="panel"><div className="panel-heading"><div><h2>{kind==='followups'?'Your sandbox follow-ups':'Reports & schedules'}</h2><p className="small muted">Saved in this Demo. Real notifications and calls stay off.</p></div><button className="quiet" onClick={()=>ask(kind==='followups'?'Help me create a follow-up for tomorrow at 9 AM.':'Create a sandbox report schedule about subscriber plans.')}><Icon name="spark"/>Create with Rafii</button></div>
  {items.map(item=>{
   const source=kind==='followups'?reports.find(report=>report.conversationId===item.conversationId)||item:item;
   return <article key={item.id}><div className="attention-row"><div><strong>{text(item.title)||text(item.intent)||state(item.kind)+' briefing'}</strong><small>{text(item.dueAt)||text(item.createdAt)} · {state(item.state)}</small><small>{text(item.summary)||text(item.text)}</small></div></div><SandboxCall source={source} intel={intel} mutate={mutate} busy={busy}/></article>;
  })}
  {!items.length&&<div className="empty"><Icon name="bell" size={28}/><h3>No {kind==='followups'?'follow-ups':'reports'} yet</h3><p>Ask Rafii to save a contextual sandbox reminder or report schedule.</p></div>}
 </section>;
}

export function FounderAgentPanel({open,close,data,mode,initialPrompt,mutate,busy,section,selected,environment,actionError}:{open:boolean;close:()=>void;data?:WorkspaceData;mode:Mode;initialPrompt:string;mutate:Mutate;busy:boolean;section:string;selected:Row|null;environment:string;actionError:string}) {
 const ref=useRef<HTMLDialogElement>(null),bottom=useRef<HTMLDivElement>(null),opener=useRef<HTMLElement|null>(null);const [emailOpen,setEmailOpen]=useState(false),[prompt,setPrompt]=useState(''),[voice,setVoice]=useState(false),[voiceText,setVoiceText]=useState(''),[error,setError]=useState(''),[scheduleType,setScheduleType]=useState('reminder'),[intent,setIntent]=useState('Review Rafii subscriber plans'),[dueLocal,setDueLocal]=useState(()=>{const d=new Date();d.setDate(d.getDate()+1);return d.toLocaleDateString('en-CA')+'T09:00';});const intel=intelligence(data);const messages=rows(intel.messages||intel.conversation),notifications=rows(intel.notifications);const conversationId=rows(intel.conversations).at(-1)?.id||null;
 useEffect(()=>{
  const panel=ref.current;if(!panel)return;
  if(open&&!panel.open){
   opener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
   const anotherModal=!!document.querySelector('dialog[open]:not(.founder-agent)');
   if(window.matchMedia('(min-width:1280px)').matches&&!anotherModal)panel.show();else panel.showModal();
  }else if(!open&&panel.open)panel.close();
  function escape(event:KeyboardEvent){if(event.key==='Escape'&&panel?.open&&!panel.matches(':modal')&&!document.querySelector('dialog[open]:not(.founder-agent)')){event.preventDefault();panel.close();}}
  window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape);
 },[open]);
 useEffect(()=>{if(initialPrompt)setPrompt(initialPrompt);},[initialPrompt]);
 useEffect(()=>{bottom.current?.scrollIntoView({block:'nearest'});},[messages.length]);
 useEffect(()=>{setVoice(false);setEmailOpen(false);setError('');},[mode,scenarioKey(data)]);
 async function submit(){if(!data||!prompt.trim()||busy)return;const chartId=section==='product'?'usage-distribution':section==='support'?'support-distribution':/revenue|cash|收入|chart/i.test(prompt)?'revenue-trend':'plan-distribution';const selectedCollection=selected?.id.startsWith('customer-')?'customers':selected?.id.startsWith('workspace-')?'workspaces':selected?.id.startsWith('invoice-')?'invoices':null;const value=JSON.stringify({message:prompt.trim(),conversationId,chartContext:{chartId,viewVersion:1,queryReceiptId:data.receipt?.id,mode:'demo',environment,...(selected&&selectedCollection?{selectedEntity:{collection:selectedCollection,id:selected.id}}:{})},modality:voice?'voice':'text'});if(new TextEncoder().encode(value).length>4000){setError('This question is too long for the sandbox. Shorten it and retry.');return;}setError('');const saved=await mutate('founder_turn','founder',value,true);if(saved){if(/email|郵件|電郵/i.test(prompt))setEmailOpen(true);setPrompt('');}else setError('Your turn could not be saved. Review the error and retry.');}
 function stop(){window.speechSynthesis?.cancel();setVoice(false);}
 async function voiceAction(operation:string){if(!conversationId)return;await mutate('founder_voice','founder',JSON.stringify({conversationId,operation}),true);}
 async function schedule(){if(!conversationId)return;const payload={conversationId,dueLocal:dueLocal+':00',timeZone:'America/Indiana/Indianapolis',confirmed:true,...(scheduleType==='reminder'?{intent}:{kind:scheduleType})};await mutate(scheduleType==='reminder'?'founder_reminder':'founder_report_schedule','founder',JSON.stringify(payload),true);}
 function readAloud(){const latest=[...messages].reverse().find(m=>['assistant','rafii'].includes(text(m.role)));if(!latest||!('speechSynthesis'in window)){setError('Browser speech playback is unavailable. Use text.');return;}window.speechSynthesis.cancel();const speech=new SpeechSynthesisUtterance(text(latest.text||latest.content||latest.answer));speech.onend=()=>setVoice(false);speech.onerror=()=>{setVoice(false);setError('Playback stopped. Text remains available.');};setVoice(true);window.speechSynthesis.speak(speech);}
 return <dialog ref={ref} className="founder-agent" onClose={()=>{stop();close();if(opener.current?.isConnected)opener.current.focus({preventScroll:true});}}><header><div className="row"><span className="agent-symbol"><Icon name="spark" size={24}/></span><div><h2>Founder Rafii</h2><p className="small muted">{mode==='demo'?'Demo simulation · evidence-bound':'Existing Founder evidence route'}</p></div></div><button className="quiet icon-action" aria-label="Close Rafii" onClick={()=>ref.current?.close()}><Icon name="close"/></button></header><div className="agent-context"><span className="badge">{mode}</span><span>{section==='command'?'Home':section} · {data?scenarioKey(data):'Loading'} · revision {data?.revision||'—'}</span>{selected&&<p>Account context: {label(selected)} · {selected.id}</p>}<p>Responses use the same dataset and receipt as your charts. Simulation runs no model, email or phone provider.</p></div><div className="agent-messages" role="log" aria-label="Founder conversation">{!messages.length&&<div className="agent-welcome"><h3>What would help you decide?</h3><p>Ask about a chart, investigate an incident, preview your notification, or save a sandbox follow-up.</p>{['Which plan has the most subscribers?','呢個 bug 影響幾多人？','Show the founder email preview.','Remind me tomorrow at 9 AM to review this.'].map(q=><button className="quiet" key={q} onClick={()=>setPrompt(q)}>{q}<Icon name="arrow" size={15}/></button>)}</div>}{messages.map((m,i)=><article className={'agent-message '+(text(m.role)==='user'?'user':'assistant')} key={m.id||i}><span>{text(m.role)==='user'?'You':'Rafii · Demo simulation'}{text(m.scenario)&&text(m.scenario)!==scenarioKey(data)?' · previous scenario':''}</span><p>{text(m.text||m.content||m.answer||m.summary)}</p>{text(m.receiptId)&&<small>Evidence: {text(m.receiptId)}</small>}{turnLinks(intel,m).map(l=><Link key={l.id} className="inline-link" href={l.kind==='invoice'?href('billing',mode,l.id):href('command',mode)+'#scenario-incident'} onClick={()=>ref.current?.close()}>{l.kind==='invoice'?'View invoice '+l.id:'Open incident'} →</Link>)}{rows(m.actions).map(a=><button className="quiet" key={a.id} onClick={()=>setPrompt(text(a.prompt)||text(a.label))}>{label(a)}</button>)}</article>)}{busy&&<p role="status">Saving your sandbox turn…</p>}{emailOpen&&<article className="agent-message email-in-chat"><h3>Actual scenario email preview</h3>{notifications.length?notifications.map(n=><details key={n.id} open={notifications.length===1}><summary>{text(n.subject)}</summary><p>{text(n.recipientLabel)} · {state(n.state)} · simulated / not actually sent</p><iframe title={'Rafii email template '+n.id} sandbox="" srcDoc={text(n.html)}/><details><summary>Plain text</summary><pre>{text(n.text)}</pre></details></details>):<p>No incident email exists in this scenario. Choose Bug / outage or Payment failure to preview a notification.</p>}</article>}<div ref={bottom}/></div><div className="agent-voice">{notifications.length>0&&<button className="quiet" onClick={()=>setEmailOpen(v=>!v)}>Preview scenario email</button>}<span className="small muted">Voice simulation · no live call</span><button className="quiet icon-action" onClick={()=>{if(voice){stop();void voiceAction('stop');}else{setVoice(true);void voiceAction('start');}}} aria-label={voice?'Stop voice simulation':'Start voice simulation'}><Icon name={voice?'stop':'mic'}/></button><button className="quiet" onClick={readAloud} disabled={!messages.length}>Browser read aloud</button>{voice&&<div className="voice-simulation"><p>Simulated listening. Type a voice transcript to exercise the same turn flow. No microphone is recorded.</p><input aria-label="Simulated voice transcript" value={voiceText} onChange={e=>setVoiceText(e.target.value)} placeholder="Speak as text…"/><button className="quiet" onClick={()=>{setPrompt(voiceText);setVoiceText('');setVoice(false);}}>Use transcript</button><button className="quiet" onClick={()=>{stop();void voiceAction('stop');}}>Stop</button><button className="quiet" onClick={()=>{stop();void voiceAction('interrupt');}}>Interrupt</button></div>}</div>{(error||actionError)&&<p className="error" role="alert">{actionError||error}</p>}{mode==='demo'&&conversationId&&<details className="agent-followup"><summary>Save a sandbox follow-up or report</summary><label>What to save<select aria-label="Schedule type" value={scheduleType} onChange={e=>setScheduleType(e.target.value)}><option value="reminder">Reminder</option><option value="daily">Daily report</option><option value="weekly">Weekly report</option></select></label><label>Follow-up title<input aria-label="Follow-up title" value={intent} onChange={e=>setIntent(e.target.value)} maxLength={300}/></label><label>Local date & time<input aria-label="Sandbox reminder time" type="datetime-local" value={dueLocal} onChange={e=>setDueLocal(e.target.value)}/></label><p className="small muted">America/Indiana/Indianapolis · saved sandbox only · real scheduler and delivery off</p><button className="quiet" disabled={busy||!dueLocal} onClick={()=>void schedule()}>Confirm sandbox {scheduleType==='reminder'?'reminder':'report'}</button><button className="quiet" disabled={busy} onClick={()=>mutate('founder_summary','founder',JSON.stringify({conversationId}),true)}>Save conversation summary</button></details>}{mode==='live'?<p className="connection-note">Business conversation generation is not activated for Live. Open Advanced → Founder investigation for the existing evidence conversation.</p>:<form className="agent-composer" onSubmit={e=>{e.preventDefault();void submit();}}><label className="sr-only" htmlFor="rafii-question">Ask Founder Rafii</label><textarea id="rafii-question" value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="Ask Rafii about your business…" rows={3} maxLength={3000} required/><button type="submit" disabled={busy||!data||!prompt.trim()}><Icon name="arrow"/>Ask Rafii</button></form>}</dialog>;
}
