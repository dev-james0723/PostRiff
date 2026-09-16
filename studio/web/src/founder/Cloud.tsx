import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import type {Access,AlphaState} from './types';
import {cloud,usd,type Analytics,type Audience,type ChannelView,type Conversation,type Message,type ProviderView,type Run,type Usage,type Variant} from './cloud-api';
import './cloud.css';

type Common={access:Access;state:AlphaState;revision:number;busy:boolean;onError:(m:string)=>void;onNotice:(m:string)=>void;reload:()=>Promise<void>};
const CAPS=['identity','publish','schedule','analytics','comments_read','reply','moderate'] as const;
const CAP_LABEL:Record<string,string>={identity:'Identity',publish:'Post',schedule:'Schedule',analytics:'Analytics',comments_read:'Comments',reply:'Reply',moderate:'Moderate'};
const DEST_LABEL=(v:{platform:string;language:string})=>`${v.platform} · ${v.language==='繁體中文'?'繁中':'EN'}`;

function Level({level}:{level:string}){return <span className={`cap-level level-${level.toLowerCase()}`}>{level}</span>;}
function Empty({title,children}:{title:string;children:ReactNode}){return <div className="cloud-empty"><span className="little-star" aria-hidden="true">✧</span><h3>{title}</h3>{children}</div>;}
function useAsync<T>(fn:()=>Promise<T>,deps:unknown[],onError:(m:string)=>void){
 const [data,setData]=useState<T|null>(null),[loading,setLoading]=useState(true);
 const run=async()=>{setLoading(true);try{setData(await fn());}catch(e){onError(e instanceof Error?e.message:'Could not load.');}finally{setLoading(false);}};
 // eslint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{void run();},deps);
 return {data,loading,refresh:run,setData};
}

/* ───────────────────────── Ideas ───────────────────────── */
export function IdeasCloud({access,state,revision,busy,onError,onNotice,reload,openSetup}:Common&{openSetup:()=>void}){
 const [conversationId,setConversationId]=useState<string|null>(null);
 const [pane,setPane]=useState<'chat'|'edit'|'preview'>('chat');
 const [run,setRun]=useState<Run|null>(null);
 const [text,setText]=useState('');
 const [own,setOwn]=useState(true),[confirm,setConfirm]=useState(false),[lang,setLang]=useState<'English'|'繁體中文'>('English');
 const [selected,setSelected]=useState(0);
 const [working,setWorking]=useState(false);
 const list=useAsync(()=>cloud.conversations(access),[access.workspaceId],onError);
 const thread=useAsync(()=>conversationId?cloud.messages(access,conversationId):Promise.resolve(null),[conversationId],onError);
 const composer=useRef<HTMLTextAreaElement>(null);
 const conversations=list.data?.conversations||[];
 const activeSources=state.sources.filter(s=>s.active);
 const lastRunId=useMemo(()=>{const m=(thread.data?.messages||[]).filter(x=>x.runId).slice(-1)[0];return m?.runId||null;},[thread.data]);
 useEffect(()=>{if(lastRunId&&run?.runId!==lastRunId)void cloud.events(access,lastRunId).then(setRun).catch(()=>{});},[lastRunId]);// eslint-disable-line react-hooks/exhaustive-deps
 async function guard<T>(task:()=>Promise<T>){setWorking(true);try{return await task();}catch(e){onError(e instanceof Error?e.message:'The idea could not be processed.');}finally{setWorking(false);}}
 async function quickStart(){
  const body=text.trim();if(!body||!confirm)return;
  const result=await guard(()=>cloud.quickStart(access,revision,{text:body,ownContent:own,confirmUse:true,destinations:[{platform:'LinkedIn',language:lang},{platform:'Instagram',language:lang==='English'?'繁體中文':'English'}]}));
  if(!result)return;
  setText('');setConfirm(false);setConversationId(result.conversationId);setRun(result);setPane('preview');await list.refresh();await reload();
  onNotice(`Drafted ${result.artifact?.variants.length||0} candidates from your ${result.sourcePolicy==='public_quote'?'own':'pasted'} source. Nothing is published.`);
 }
 async function sendTurn(){
  const body=text.trim();if(!conversationId||!body)return;
  const result=await guard(()=>cloud.turn(access,conversationId,{text:body,destinations:[{platform:'LinkedIn',language:lang},{platform:'Instagram',language:lang==='English'?'繁體中文':'English'}]}));
  if(!result)return;setText('');setRun(result);await thread.refresh();setPane('preview');
 }
 async function apply(){
  if(!run?.artifactHash)return;
  const result=await guard(()=>cloud.apply(access,run.runId,revision,run.artifactHash!));
  if(!result)return;await reload();onNotice(`${result.variants??''} candidate${result.variants===1?'':'s'} added to your drafts for review. Publishing still needs an exact approval.`);
 }
 const variants:Variant[]=run?.artifact?.variants||[];
 const composerBlock=(
  <div className="composer">
   {!conversationId&&<div className="quick-start-head"><span className="eyebrow">START FROM A SOURCE</span><p>Paste a thought, a paragraph, or a link. You get a preview before you connect anything.</p></div>}
   <label className="field"><span className="sr-only">Your idea or source</span><textarea ref={composer} value={text} onChange={e=>setText(e.target.value)} rows={conversationId?3:6} placeholder={conversationId?'Ask for another angle, a shorter version, or a different audience…':'e.g. The community garden hosts a free seed-swap on Saturday. Visitors can bring seeds or simply come to learn.'} maxLength={20000}/></label>
   {!conversationId&&<div className="quick-options">
    <label className="check"><input type="checkbox" checked={own} onChange={e=>setOwn(e.target.checked)}/>This is my own writing (may be quoted publicly)</label>
    <label className="check"><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>Use this content to draft with</label>
    <div className="seg" role="group" aria-label="Primary language">{(['English','繁體中文'] as const).map(l=><button key={l} type="button" className={lang===l?'on':''} onClick={()=>setLang(l)}>{l}</button>)}</div>
   </div>}
   <div className="button-row">
    {conversationId?<button className="button" disabled={busy||working||!text.trim()} onClick={()=>void sendTurn()}>Draft again ↗</button>:<button className="button" disabled={busy||working||!text.trim()||!confirm} onClick={()=>void quickStart()}>Draft two previews ↗</button>}
    <span className="helper">{working?'Drafting with the deterministic preview…':'Deterministic preview · no model request · $0'}</span>
   </div>
  </div>);
 const chat=(
  <section className="pane pane-chat" aria-label="Conversation">
   <header className="pane-head"><span className="eyebrow">IDEAS</span><h1 id="main-title" tabIndex={-1}>{conversationId?(conversations.find(c=>c.conversationId===conversationId)?.title||'Conversation'):'One idea. A few good riffs.'}</h1></header>
   {conversationId?<ol className="messages">{(thread.data?.messages||[]).map((m:Message)=><li key={m.messageId} className={`msg msg-${m.role}`}><span className="msg-role">{m.role==='user'?'You':'PostRiff'}</span><p>{String((m.body as {text?:string}).text||'')}</p>{Array.isArray((m.body as {excluded?:unknown[]}).excluded)&&((m.body as {excluded:{id:string;reason:string}[]}).excluded.length>0)&&<ul className="excluded">{(m.body as {excluded:{id:string;reason:string}[]}).excluded.map(x=><li key={x.id}>Source excluded — {x.reason.replace(/_/g,' ')}</li>)}</ul>}</li>)}</ol>
   :<div className="idea-intro">{activeSources.length>0&&<p className="helper">{activeSources.length} source{activeSources.length===1?'':'s'} already in this workspace will be considered where policy allows.</p>}<button className="text-button" onClick={openSetup}>Prefer the guided voice setup? →</button></div>}
   {composerBlock}
   {run&&<details className="run-log"><summary>Run log · {run.status} · {run.events.length} events</summary><ol>{run.events.map(e=><li key={e.id}><code>{e.type}</code>{e.message?` — ${e.message}`:e.stage?` — ${e.stage} ${e.percent}%`:e.policy?` — ${e.policy}`:''}</li>)}</ol></details>}
  </section>);
 const edit=(
  <section className="pane pane-edit" aria-label="Edit">
   <header className="pane-head"><span className="eyebrow">EDIT</span><h2>{variants.length?DEST_LABEL(variants[selected]||variants[0]):'No candidate yet'}</h2></header>
   {variants.length?<>
    <div className="seg" role="tablist" aria-label="Destination">{variants.map((v,i)=><button key={i} role="tab" aria-selected={selected===i} className={selected===i?'on':''} onClick={()=>setSelected(i)}>{DEST_LABEL(v)}</button>)}</div>
    <textarea className="candidate-text" readOnly value={variants[selected]?.text||''} rows={14} aria-label="Candidate text (read-only until applied)"/>
    {!!variants[selected]?.unknowns?.length&&<div className="unknowns"><strong>Unknowns kept out of the draft</strong><ul>{variants[selected].unknowns.map((u,i)=><li key={i}>{u}</li>)}</ul></div>}
    {variants[selected]?.candidateOnly&&<p className="message warning">Rewritten-source candidate — approve public use of the source before publishing.</p>}
    <div className="button-row"><button className="button" disabled={busy||working||run?.status==='applied'} onClick={()=>void apply()}>{run?.status==='applied'?'Added to drafts':'Add to my drafts for review ↗'}</button><span className="helper">Applying creates reviewable drafts. It never publishes.</span></div>
   </>:<Empty title="Nothing to edit yet">Draft from a source first; each destination becomes its own editable variant.</Empty>}
  </section>);
 const preview=(
  <section className="pane pane-preview" aria-label="Preview">
   <header className="pane-head"><span className="eyebrow">PREVIEW</span><h2>{variants.length?'Native previews':'Preview'}</h2></header>
   {variants.length?<div className="previews">{variants.map((v,i)=><article key={i} className={`post-preview ${v.platform.toLowerCase()}`}><header><span className="avatar small" aria-hidden="true">{state.speaker.label?.[0]||'M'}</span><span><strong>{state.workspace.name}</strong><small>{DEST_LABEL(v)}</small></span></header><p>{v.text}</p><footer>{v.warnings?.[0]&&<span className="tag">{v.warnings[0]}</span>}</footer></article>)}</div>
   :<Empty title="Your previews appear here">Two channel-native candidates from one idea — LinkedIn and Instagram, in the languages you choose.</Empty>}
  </section>);
 return <div className="ideas-cloud">
  <aside className="conv-list" aria-label="Conversations">
   <div className="conv-head"><span className="eyebrow">CONVERSATIONS</span><button className="text-button" onClick={()=>{setConversationId(null);setRun(null);setPane('chat');composer.current?.focus();}}>+ New</button></div>
   <ul>{conversations.map((c:Conversation)=><li key={c.conversationId}><button className={`conv ${conversationId===c.conversationId?'on':''}`} onClick={()=>{setConversationId(c.conversationId);setPane('chat');}}>{c.title||'Untitled'}<small>{new Date(c.updatedAt*1000).toLocaleDateString()}</small></button></li>)}{!conversations.length&&!list.loading&&<li className="helper">No conversations yet.</li>}</ul>
  </aside>
  <div className="mobile-seg" role="tablist" aria-label="Ideas panes">{(['chat','edit','preview'] as const).map(p=><button key={p} role="tab" aria-selected={pane===p} className={pane===p?'on':''} onClick={()=>setPane(p)}>{p[0].toUpperCase()+p.slice(1)}</button>)}</div>
  <div className={`panes show-${pane}`}>{chat}{edit}{preview}</div>
 </div>;
}

/* ───────────────────────── Channels ───────────────────────── */
export function ChannelsCloud({access,busy,onError,onNotice,reload,oauthReturn,clearReturn}:Common&{oauthReturn:{provider:string;state:string;code?:string;error?:string}|null;clearReturn:()=>void}){
 const data=useAsync(()=>cloud.channels(access),[access.workspaceId],onError);
 const [capability,setCapability]=useState<Record<string,string>>({});
 const [working,setWorking]=useState<string|null>(null);
 const [pending,setPending]=useState<{provider:ProviderView;authorizeUrl:string;permissionExplanation:string;scopes:string[]}|null>(null);
 const [confirmDisconnect,setConfirmDisconnect]=useState<string|null>(null);
 const handled=useRef(false);
 useEffect(()=>{
  if(!oauthReturn||handled.current)return;handled.current=true;
  (async()=>{try{const r=await cloud.oauthComplete(access,oauthReturn.provider,oauthReturn.state,oauthReturn.code,oauthReturn.error);
   onNotice(r.connected?`Connected ${r.account}. Confirm this is the right account below.${r.missingScopes?.length?` Missing scopes: ${r.missingScopes.join(', ')} — publishing stays Assisted.`:''}`:'Connection was not granted. Nothing was stored.');
   await data.refresh();await reload();}catch(e){onError(e instanceof Error?e.message:'Connection could not be completed.');}finally{clearReturn();}})();
 },[oauthReturn]);// eslint-disable-line react-hooks/exhaustive-deps
 async function connect(p:ProviderView){
  const cap=capability[p.id]||'publish';setWorking(p.id);
  try{const r=await cloud.oauthStart(access,p.id,cap);setPending({authorizeUrl:r.authorizeUrl,permissionExplanation:r.permissionExplanation,scopes:r.scopes,provider:p});}
  catch(e){onError(e instanceof Error?e.message:'Could not start the connection.');}finally{setWorking(null);}
 }
 async function verify(c:ChannelView){setWorking(c.id);try{const r=await cloud.verifyChannel(access,c.id);onNotice(`Verification: ${r.state.replace(/_/g,' ')}${r.detail?` — ${r.detail}`:''}`);await data.refresh();}catch(e){onError(e instanceof Error?e.message:'Verification failed.');}finally{setWorking(null);}}
 async function disconnect(c:ChannelView){if(confirmDisconnect!==c.id){setConfirmDisconnect(c.id);return;}setConfirmDisconnect(null);setWorking(c.id);try{await cloud.disconnect(access,c.id);onNotice('Disconnected. Stored tokens were wiped.');await data.refresh();await reload();}catch(e){onError(e instanceof Error?e.message:'Could not disconnect.');}finally{setWorking(null);}}
 const channels=data.data?.channels||[],providers=data.data?.providers||[];
 return <div className="channels-cloud">
  <header className="section-heading"><span className="eyebrow">CHANNELS</span><h1 id="main-title" tabIndex={-1}>Each capability, verified on its own.</h1><p className="lede">Identity, posting, scheduling, analytics and comments are separate permissions. A connected account is not the same as a publishable one.</p></header>
  {channels.length?<div className="channel-cards">{channels.map(c=><article key={c.id} className="channel-card"><header><span className={`platform-mark ${c.platform.toLowerCase()}`} aria-hidden="true">{c.platform[0]}</span><div><strong>{c.account}</strong><small>{c.platform} · {c.accountType||'account'} · <span className={`conn-state s-${c.connectionState}`}>{c.connectionState.replace(/_/g,' ')}</span></small></div></header>
   <table className="cap-table"><caption className="sr-only">Capabilities for {c.account}</caption><tbody>{CAPS.map(k=><tr key={k}><th scope="row">{CAP_LABEL[k]}</th><td><Level level={c.capabilities[k]?.level||'Unsupported'}/></td><td className="cap-evidence">{c.capabilities[k]?.evidence||'—'}</td></tr>)}</tbody></table>
   {c.expiresAt&&<p className="helper">Access expires {new Date(c.expiresAt*1000).toLocaleDateString()} · evidence: {c.evidenceSource.replace(/_/g,' ')}</p>}
   <div className="button-row"><button className="button secondary" disabled={busy||working===c.id} onClick={()=>void verify(c)}>Re-verify</button><button className="button secondary danger" disabled={busy||working===c.id} onClick={()=>void disconnect(c)}>{confirmDisconnect===c.id?'Confirm disconnect':'Disconnect'}</button>{confirmDisconnect===c.id&&<button className="text-button" onClick={()=>setConfirmDisconnect(null)}>Keep</button>}</div>{confirmDisconnect===c.id&&<p className="helper">Approved jobs for this account will be held; stored tokens are wiped and revoked remotely where supported.</p>}</article>)}</div>
  :<Empty title="No accounts connected">You can draft without connecting anything. Connect an account only when you want previews, scheduling, analytics or comments for it.</Empty>}
  {pending&&<section className="permission-step" aria-live="polite"><span className="eyebrow">BEFORE YOU CONTINUE TO {pending.provider.platform.toUpperCase()}</span><p className="lede">{pending.permissionExplanation}</p><p className="helper">Scopes requested: {pending.scopes.join(', ')}. You will confirm the exact account after {pending.provider.platform} returns you here.</p><div className="button-row"><a className="button" href={pending.authorizeUrl}>Continue to {pending.provider.platform} ↗</a><button className="button secondary" onClick={()=>setPending(null)}>Not now</button></div></section>}
  <section className="providers"><h2>Available connections</h2>
   {providers.length?<ul className="provider-list">{providers.map(p=><li key={p.id}><div><strong>{p.platform}</strong><small>{p.productionReviewed?'Production-reviewed app · Direct posting available':'Awaiting provider review · export only until then'}</small></div>
    <label className="field inline"><span className="sr-only">Capability</span><select value={capability[p.id]||'publish'} onChange={e=>setCapability({...capability,[p.id]:e.target.value})}>{CAPS.filter(k=>k!=='identity'&&k!=='moderate'&&p.capabilities[k]!==false).map(k=><option key={k} value={k}>{CAP_LABEL[k]}</option>)}</select></label>
    <button className="button" disabled={busy||working===p.id} onClick={()=>void connect(p)}>Connect ↗</button></li>)}</ul>
   :<p className="helper">No providers are configured on this deployment yet. LinkedIn, Threads and Instagram are the audited launch set; each needs its own app review before it appears here.</p>}
  </section>
 </div>;
}

/* ───────────────────────── Usage & Plan ───────────────────────── */
export function UsagePlan({access,revision,busy,onError,onNotice,reload}:Common){
 const data=useAsync(()=>cloud.usage(access),[access.workspaceId,revision],onError);
 const requests=useAsync(()=>cloud.dataRequests(access),[access.workspaceId],onError);
 const [notice,setNotice]=useState<Record<string,unknown>|null>(null);
 const u=data.data as Usage|null;
 async function request(kind:string,extra:Record<string,unknown>={}){try{const r=await cloud.dataRequest(access,{kind,...extra});onNotice(kind==='export'?`Export receipt recorded · sha256 ${String((r as {receipt?:{sha256?:string}}).receipt?.sha256||'').slice(0,12)}…`:`${kind} ${r.status}`);await requests.refresh();if(kind==='retraction')await reload();}catch(e){onError(e instanceof Error?e.message:'Request failed.');}}
 const pct=(a:number,b:number)=>b>0?Math.min(100,Math.round(100*a/b)):0;
 return <div className="usage-plan">
  <header className="section-heading"><span className="eyebrow">USAGE & PLAN</span><h1 id="main-title" tabIndex={-1}>What you have, what you've used, what it costs.</h1><p className="lede">Overage never happens silently — when an allowance runs out, drafting stops and tells you.</p></header>
  {u&&<div className="usage-grid">
   <article className="stat"><span className="eyebrow">WRITING BATCHES LEFT</span><strong className="big">{u.entitlement.writingBatchesRemaining}</strong><small>{u.entitlement.source==='trial'?'trial allowance':'plan allowance'}{u.entitlement.resetsAt?` · resets ${new Date(u.entitlement.resetsAt*1000).toLocaleDateString()}`:''}</small></article>
   <article className="stat"><span className="eyebrow">PLAN</span><strong>{u.subscription?u.subscription.label:'Trial'}</strong><small>{u.subscription?`${u.subscription.status}${u.subscription.live?'':' · fixture provider'} · price ${u.subscription.priceStatus}`:'no subscription'}</small></article>
   <article className="stat"><span className="eyebrow">SPEND THIS {u.budget.windowKind.toUpperCase()}</span><strong>{usd(u.budget.spentUsdMicro)}</strong><small>reserved {usd(u.budget.reservedUsdMicro)} · stop at {usd(u.budget.stopUsdMicro)} ({u.budget.status})</small><div className="bar" role="progressbar" aria-valuenow={pct(u.budget.spentUsdMicro+u.budget.reservedUsdMicro,u.budget.stopUsdMicro)} aria-valuemin={0} aria-valuemax={100}><span style={{width:`${pct(u.budget.spentUsdMicro+u.budget.reservedUsdMicro,u.budget.stopUsdMicro)}%`}}/></div></article>
   <article className="stat"><span className="eyebrow">OVERAGE</span><strong>Stop</strong><small>{u.lifecycle.status} · export {u.lifecycle.exportAvailable===false?'unavailable':'always available'}</small></article>
  </div>}
  {u&&<section><h2>Plan terms <span className="tag">decision records</span></h2><p className="helper">{u.note}</p><ul className="terms">{u.planTerms.map(t=><li key={t.id} className={u.subscription&&u.entitlement.planTermsId===t.id?'on':''}><strong>{t.label}</strong><span>{t.priceCents?`$${(t.priceCents/100).toFixed(0)}/mo`:'$0'} · <em>{t.priceLabel}</em></span><small>{String((t.entitlements as {writingBatches?:number}).writingBatches??0)} batches · {String((t.entitlements as {connectedAccounts?:number}).connectedAccounts??0)} accounts · v{t.version}</small></li>)}</ul></section>}
  {u&&<section><h2>Recent usage ledger</h2>{u.ledger.length?<table className="ledger"><thead><tr><th>When</th><th>Kind</th><th>Dimension</th><th>Estimated</th><th>Actual</th><th>State</th></tr></thead><tbody>{u.ledger.slice(0,12).map((l,i)=><tr key={i}><td>{new Date(l.at*1000).toLocaleString()}</td><td>{l.kind}</td><td>{l.dimension}{l.model?` · ${l.model}`:''}</td><td>{usd(l.estimatedUsdMicro)}</td><td>{usd(l.actualUsdMicro)}</td><td><span className={`tag t-${l.costState}`}>{l.costState.replace(/_/g,' ')}</span></td></tr>)}</tbody></table>:<p className="helper">No usage yet.</p>}</section>}
  <section><h2>Your data</h2><div className="button-row wrap"><button className="button secondary" disabled={busy} onClick={()=>void request('export')}>Export with receipt</button><button className="button secondary" disabled={busy} onClick={()=>{if(window.confirm('Create a sanitized diagnostics package (counts and states only, no content)?'))void request('diagnostics',{consent:true});}}>Diagnostics (with consent)</button><button className="button secondary" disabled={busy} onClick={()=>void cloud.privacy().then(setNotice).catch(()=>onError('Privacy notice unavailable.'))}>Privacy notice</button></div>
   {!!requests.data?.requests.length&&<ul className="receipts">{requests.data.requests.slice(0,6).map(r=><li key={r.requestId}><strong>{r.kind}</strong> · {r.status} · {new Date(r.requestedAt*1000).toLocaleString()}{(r.receipt as {sha256?:string}).sha256&&<code> {(r.receipt as {sha256:string}).sha256.slice(0,16)}…</code>}</li>)}</ul>}
   {notice&&<details open className="privacy"><summary>Privacy notice · <em>{String(notice.status)}</em></summary><dl>{['aiProcessing','providerAccess','ingestion','telemetry'].map(k=><div key={k}><dt>{k.replace(/([A-Z])/g,' $1')}</dt><dd>{String(notice[k])}</dd></div>)}</dl><p className="helper">Retention classes: {Object.keys((notice.retention as Record<string,unknown>)||{}).join(', ')}.</p></details>}
  </section>
 </div>;
}

/* ───────────────────────── Analytics ───────────────────────── */
export function AnalyticsLimited({access,onError}:Common){
 const data=useAsync(()=>cloud.analytics(access),[access.workspaceId],onError);
 const a=data.data as Analytics|null;
 return <div className="analytics-limited">
  <header className="section-heading"><span className="eyebrow">ANALYTICS · LIMITED</span><h1 id="main-title" tabIndex={-1}>Native numbers, side by side.</h1><p className="lede">Each metric keeps its provider's own definition. Missing shows as <strong>Unavailable</strong>, never zero. Providers are listed next to each other — never added up.</p></header>
  {a&&(a.posts.length?<div className="post-metrics">{a.posts.map(p=><article key={p.provider+p.providerPostId} className="metric-card"><header><strong>{p.platform||p.provider}</strong><small>{p.language||''} · {p.contentOrigin.replace(/_/g,' ')} · {p.publishedState}</small></header><dl>{Object.entries(p.metrics).map(([k,m])=><div key={k}><dt>{m.nativeName}</dt><dd className={m.availability!=='available'?'unavail':''}>{m.display}</dd></div>)}</dl><footer><span>likes / views: {p.rates.likesPerView?.display}</span><span>observed {new Date(p.freshness.observedAt*1000).toLocaleString()} · def {p.definitionVersion}</span></footer></article>)}</div>
  :<Empty title="No post metrics yet">Metrics appear after a publication is <em>verified</em> on a connection with the analytics capability. {a.connections.length?<ul>{a.connections.map(c=><li key={c.id}>{c.platform} · {c.account}: {c.analytics}</li>)}</ul>:'No connections yet.'}</Empty>)}
  {a&&<ul className="rules">{Object.entries(a.rules).map(([k,v])=><li key={k}><strong>{k.replace(/([A-Z])/g,' $1')}</strong> {v}</li>)}</ul>}
 </div>;
}

/* ───────────────────────── Audience ───────────────────────── */
export function AudienceLimited({access,busy,onError,onNotice}:Common){
 const data=useAsync(()=>cloud.audience(access),[access.workspaceId],onError);
 const [drafts,setDrafts]=useState<Record<string,{draftId:string;text:string;label:string}>>({});
 const [text,setText]=useState<Record<string,string>>({});
 const [preview,setPreview]=useState<{draftId:string;digest:string;action:string;replyLevel:string}|null>(null);
 const au=data.data as Audience|null;
 async function draft(threadId:string,origin:'manual'|'ai_fixture'){try{const d=await cloud.draftReply(access,threadId,{origin,text:text[threadId]||''});setDrafts({...drafts,[threadId]:d});if(origin==='ai_fixture')setText({...text,[threadId]:d.text});}catch(e){onError(e instanceof Error?e.message:'Could not draft.');}}
 async function openPreview(threadId:string){const d=drafts[threadId];if(!d)return;try{const p=await cloud.replyPreview(access,d.draftId);setPreview({draftId:d.draftId,...p});}catch(e){onError(e instanceof Error?e.message:'Preview failed.');}}
 async function send(){if(!preview)return;try{const r=await cloud.approveReply(access,preview.draftId,preview.digest);onNotice(`${r.status}. ${r.note||''}`);setPreview(null);}catch(e){onError(e instanceof Error?e.message:'Reply could not be approved.');}}
 return <div className="audience-limited">
  <header className="section-heading"><span className="eyebrow">AUDIENCE · LIMITED</span><h1 id="main-title" tabIndex={-1}>Real replies. Sent one at a time.</h1><p className="lede">You see the original comment, write or accept a labelled suggestion, then approve the exact account, thread and text. Sending and verification are recorded separately.</p></header>
  {au&&(au.threads.length?<ul className="threads">{au.threads.map(t=><li key={t.threadId} className="thread"><header><strong>@{t.author||'someone'}</strong><small>{t.provider} · post {t.providerPostId}</small></header><blockquote>{t.text}</blockquote>
   {t.replyAvailable?<div className="reply-box"><label className="field"><span className="sr-only">Your reply</span><textarea rows={2} value={text[t.threadId]||''} onChange={e=>setText({...text,[t.threadId]:e.target.value})} placeholder="Write your reply…" maxLength={500}/></label><div className="button-row"><button className="button secondary" disabled={busy} onClick={()=>void draft(t.threadId,'ai_fixture')}>Suggest (AI · labelled)</button><button className="button secondary" disabled={busy||!(text[t.threadId]||'').trim()} onClick={()=>void draft(t.threadId,'manual')}>Save my reply</button><button className="button" disabled={busy||!drafts[t.threadId]} onClick={()=>void openPreview(t.threadId)}>Review & send ↗</button></div>{drafts[t.threadId]&&<p className="helper">Draft saved · {drafts[t.threadId].label}</p>}</div>
   :<p className="helper">Replies are {t.replyLevel} for this connection — read-only here.</p>}</li>)}</ul>
  :<Empty title="No comments yet">Comments appear for connections whose <strong>Comments</strong> capability is Direct, after a verified publication. {au.capabilities.length?<ul>{au.capabilities.map(c=><li key={c.connectionId}>connection {c.connectionId.slice(0,8)}… · comments {c.commentsRead}</li>)}</ul>:null}</Empty>)}
  {au&&<p className="helper">{au.limits}</p>}
  {preview&&<div className="sheet" role="dialog" aria-modal="true" aria-labelledby="reply-title"><div className="sheet-body"><h2 id="reply-title">{preview.action}</h2><p className="helper">Reply capability: {preview.replyLevel}. Digest {preview.digest.slice(0,12)}…</p><pre className="manifest">{JSON.stringify(preview,null,1)}</pre><div className="button-row"><button className="button" disabled={busy||preview.replyLevel!=='Direct'} onClick={()=>void send()}>{preview.action}</button><button className="button secondary" onClick={()=>setPreview(null)}>Cancel</button></div></div></div>}
 </div>;
}

/* ───────────────────────── Utility menu ───────────────────────── */
export function AccountMenu({open,onClose,items}:{open:boolean;onClose:()=>void;items:{label:string;hint?:string;onSelect:()=>void;danger?:boolean}[]}){
 const first=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(open)first.current?.focus();const key=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose();};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[open,onClose]);
 if(!open)return null;
 return <div className="account-menu" role="menu" aria-label="Account and workspace">{items.map((it,i)=><button key={it.label} ref={i===0?first:undefined} role="menuitem" className={it.danger?'danger':''} onClick={()=>{onClose();it.onSelect();}}>{it.label}{it.hint&&<small>{it.hint}</small>}</button>)}</div>;
}
