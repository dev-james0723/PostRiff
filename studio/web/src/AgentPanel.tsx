import {useEffect, useRef, useState, type ReactNode} from 'react';
import {agentApi, isActiveRun, readyForGeneration, runStateLabel, type AgentStatus, type ContentType, type Conversation, type InputReview, type Run, type RunRequest} from './agentApi';
import type {Channel, Draft} from './types';
import {readWorkspaceRuns, selectHistory} from './agentHistory';

type Props = {
  draft: Draft|null; dirty: boolean; channels: Channel[]; workspaceDrafts: Draft[];
  onApplied: (draft: Draft) => void;
  onStatus: (status: AgentStatus|null) => void;
  onPendingInput: (pending: boolean) => void;
  onOpenDraft: (draft: Draft) => void;
};
const failure = (cause: unknown) => cause instanceof Error?cause.message:'The local bridge could not complete this request.';

function AgentDialog({title,onClose,children}: {title: string; onClose:()=>void; children:ReactNode}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const element=dialog.current!, previous=document.activeElement as HTMLElement|null;element.showModal();return()=>{element.close();previous?.focus();};},[]);
  return <dialog className="agent-dialog" ref={dialog} aria-labelledby="agent-dialog-title" onCancel={event=>{event.preventDefault();onClose();}}>
    <div className="dialog-head"><h2 id="agent-dialog-title">{title}</h2><button className="icon-button" type="button" aria-label="Close agent review" onClick={onClose}>×</button></div>{children}
  </dialog>;
}

export default function AgentPanel({draft,dirty,channels,workspaceDrafts,onApplied,onStatus,onPendingInput,onOpenDraft}:Props) {
  const [status,setStatus]=useState<AgentStatus|null>(null),[checking,setChecking]=useState(false);
  const [conversation,setConversation]=useState<Conversation|null>(null),[history,setHistory]=useState<Conversation[]>([]);
  const [run,setRun]=useState<Run|null>(null),[runs,setRuns]=useState<Run[]>([]),[review,setReview]=useState<InputReview|null>(null);
  const [contentType,setContentType]=useState<ContentType>('article'),[answer,setAnswer]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[feedback,setFeedback]=useState('');
  const [reviewOpen,setReviewOpen]=useState(false),[candidateOpen,setCandidateOpen]=useState(false),[consent,setConsent]=useState(false);
  const [selected,setSelected]=useState<string[]>([]),[request,setRequest]=useState<RunRequest|null>(null),[pollPaused,setPollPaused]=useState(false);
  const [workspaceRun,setWorkspaceRun]=useState<Run|null>(null),[scanning,setScanning]=useState(false);
  const currentWorkspaceRun=useRef<Run|null>(null);
  const scanEpoch=useRef(0), workspaceIds=workspaceDrafts.map(item=>item.id).sort().join('|');
  const epoch=useRef(0), mounted=useRef(true), currentDraft=useRef(draft);
  const stale=!!conversation&&conversation.draftRevision!==draft?.revision;
  const active=isActiveRun(run), knownActive=active||isActiveRun(workspaceRun)||runs.some(item=>isActiveRun(item)), ready=readyForGeneration(status);
  const editable=!!draft&&!draft.archived&&!dirty;
  currentDraft.current=draft;
  currentWorkspaceRun.current=workspaceRun;
  const fresh=(token:number)=>mounted.current&&token===epoch.current;

  function rememberRun(value:Run){
    if(value.draftId===currentDraft.current?.id)setRuns(current=>[value,...current.filter(item=>item.id!==value.id)]);
    setRun(current=>current?.id===value.id?value:current);
    setWorkspaceRun(current=>isActiveRun(value)?value:current?.id===value.id?null:current);
  }

  async function scanWorkspace(){
    const token=++scanEpoch.current;
    setScanning(true);
    try{
      const allRuns=await readWorkspaceRuns(workspaceDrafts.map(item=>item.id),agentApi.runs);
      if(!mounted.current||token!==scanEpoch.current)return;
      const tracked=allRuns.find(isActiveRun);
      if(tracked)setWorkspaceRun(tracked);
      else {
        const settled=allRuns.find(item=>item.id===currentWorkspaceRun.current?.id);
        if(settled)rememberRun(settled);
      }
    }catch(cause){if(mounted.current&&token===scanEpoch.current)setError(failure(cause));}
    finally{if(mounted.current&&token===scanEpoch.current)setScanning(false);}
  }

  useEffect(()=>{if(workspaceIds)void scanWorkspace();},[workspaceIds]);

  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current++;};},[]);

  async function checkReadiness(){
    setChecking(true);
    try{const value=await agentApi.status();if(!mounted.current)return;setStatus(value);onStatus(value);}
    catch(cause){if(!mounted.current)return;setStatus(null);onStatus(null);setError(failure(cause));}
    finally{if(mounted.current)setChecking(false);}
  }
  useEffect(()=>{void checkReadiness();},[]);

  async function loadHistory(preferRequestId?:string){
    const target=currentDraft.current;if(!target)return;
    const token=epoch.current;
    const [conversationsResult,runsResult]=await Promise.all([agentApi.conversations(target.id),agentApi.runs(target.id)]);
    if(!mounted.current||token!==epoch.current)return;
    setHistory(conversationsResult.conversations);setRuns(runsResult.runs);
    const resumed=selectHistory(conversationsResult.conversations,runsResult.runs,preferRequestId);
    setConversation(resumed.conversation);setRun(resumed.run);setSelected([]);setPollPaused(false);
    if(resumed.run&&isActiveRun(resumed.run))setWorkspaceRun(resumed.run);
    if(preferRequestId&&!runsResult.runs.some(item=>item.requestId===preferRequestId))setFeedback('No saved run with this request ID was found. There has been no automatic retry.');
  }

  useEffect(()=>{
    epoch.current++;setBusy(false);setConversation(null);setHistory([]);setRun(null);setRuns([]);setReview(null);setReviewOpen(false);setCandidateOpen(false);setAnswer('');setError('');setFeedback('');setRequest(null);setConsent(false);setSelected([]);setPollPaused(false);
    const token=epoch.current;
    if(draft?.id)void loadHistory().catch(cause=>{if(fresh(token))setError(failure(cause));});
  },[draft?.id,draft?.revision]);

  useEffect(()=>{
    if(!run||!isActiveRun(run)||workspaceRun?.id===run.id)return;
    let stopped=false,timer:number|undefined,attempts=0;
    const id=run.id,token=epoch.current;
    const maxPolls=Math.min(240,Math.ceil((status?.limits.timeoutSeconds||180)/1.5)+20);
    async function poll(){
      if(stopped||token!==epoch.current)return;
      try{
        const value=await agentApi.run(id);
        if(stopped||token!==epoch.current)return;
        rememberRun(value.run);
        if(!isActiveRun(value.run)){setPollPaused(false);return;}
        attempts++;
        if(attempts>=maxPolls){setPollPaused(true);setFeedback('Automatic status checks paused at the local limit. Check status to continue; no generation is retried.');return;}
        timer=window.setTimeout(()=>void poll(),1500);
      }catch(cause){if(stopped||token!==epoch.current)return;setPollPaused(true);setError(failure(cause));}
    }
    timer=window.setTimeout(()=>void poll(),1200);
    return()=>{stopped=true;if(timer)window.clearTimeout(timer);};
  },[run?.id,workspaceRun?.id]);

  // The tracked active run stays observable even while its history/draft is hidden.
  useEffect(()=>{
    if(!workspaceRun||!isActiveRun(workspaceRun))return;
    let stopped=false,timer:number|undefined,attempts=0;
    const id=workspaceRun.id,maxPolls=Math.min(240,Math.ceil((status?.limits.timeoutSeconds||180)/1.5)+20);
    async function poll(){
      if(stopped||!mounted.current)return;
      try{
        const value=await agentApi.run(id);
        if(stopped||!mounted.current)return;
        rememberRun(value.run);
        if(!isActiveRun(value.run)){setPollPaused(false);return;}
        attempts++;
        if(attempts>=maxPolls){setPollPaused(true);setFeedback('Automatic checks reached their limit. Use Check tracked status; no generation was retried.');return;}
        timer=window.setTimeout(()=>void poll(),1500);
      }catch(cause){if(!stopped&&mounted.current){setPollPaused(true);setError(failure(cause));}}
    }
    timer=window.setTimeout(()=>void poll(),1200);
    return()=>{stopped=true;if(timer)window.clearTimeout(timer);};
  },[workspaceRun?.id]);

  useEffect(()=>{
    onPendingInput(!!answer.trim());
    const handler=(event:BeforeUnloadEvent)=>{if(answer.trim()){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);
  },[answer]);

  async function startConversation(){
    if(!editable||!draft)return;
    if(answer.trim()&&!window.confirm('Discard the unsaved answer and start a fresh conversation?'))return;
    const token=epoch.current;
    setBusy(true);setError('');setFeedback('');
    try{
      const value=await agentApi.create(draft.id,draft.revision,contentType);
      if(!fresh(token))return;
      setConversation(value.conversation);setHistory(current=>[value.conversation,...current]);
      setRun(null);setReview(null);setRequest(null);setConsent(false);setAnswer('');
      setFeedback('Guided intake started. No model request has been made.');
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  async function answerQuestion(){
    if(!conversation?.question||!editable||stale)return;
    const token=epoch.current;
    setBusy(true);setError('');
    try{
      const value=await agentApi.answer(conversation.id,conversation.revision,conversation.question.slot,answer);
      if(!fresh(token))return;
      setConversation(value.conversation);setHistory(current=>[value.conversation,...current.filter(item=>item.id!==value.conversation.id)]);
      setAnswer('');setReview(null);setRequest(null);setFeedback('Answer saved locally. No model request has been made.');
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  async function prepareReview(){
    if(!conversation||!editable||stale)return;
    const token=epoch.current;
    setBusy(true);setError('');
    try{
      const value=await agentApi.review(conversation.id);
      if(!fresh(token))return;
      setReview(value);setConversation(value.conversation);setReviewOpen(true);setConsent(false);
      setRequest(current=>current?.inputHash===value.inputHash&&!run?current:null);
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  async function generate(){
    if(!review||!conversation||!editable||stale||!consent||!ready||knownActive)return;
    const token=epoch.current;
    setBusy(true);setError('');
    const exactRequest=request||{expectedRevision:review.conversation.revision,inputHash:review.inputHash,requestId:crypto.randomUUID(),consent:true as const};
    setRequest(exactRequest);
    try{
      const value=await agentApi.generate(conversation.id,exactRequest);
      if(!fresh(token))return;
      setRun(value.run);rememberRun(value.run);
      setSelected([]);setReviewOpen(false);setFeedback('Generation request recorded. Candidate copy still requires your review.');
    }catch(cause){if(fresh(token))setError(`${failure(cause)} No automatic retry will occur. Check saved runs before retrying this same request.`);}
    finally{if(fresh(token))setBusy(false);}
  }
  async function checkRun(){
    const token=epoch.current;
    setBusy(true);setError('');
    try{
      if(run){
        const value=await agentApi.run(run.id);
        if(!fresh(token))return;
        rememberRun(value.run);
        setFeedback(isActiveRun(value.run)?'Generation is still active. Status checked without retrying.':runStateLabel(value.run.state));
      }else await loadHistory(request?.requestId);
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  async function cancelRun(target:Run|null=run){
    if(!target)return;
    const token=epoch.current;
    setBusy(true);setError('');
    try{
      const value=await agentApi.cancel(target.id);
      if(!fresh(token))return;
      rememberRun(value.run);
      setFeedback('Cancellation requested for this run. Late candidate output will not be applied.');
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  async function checkTrackedRun(){
    if(!workspaceRun)return;
    setBusy(true);setError('');
    try{const value=await agentApi.run(workspaceRun.id);if(mounted.current){rememberRun(value.run);setFeedback(runStateLabel(value.run.state));}}
    catch(cause){if(mounted.current)setError(failure(cause));}
    finally{if(mounted.current)setBusy(false);}
  }
  function showTrackedRun(){
    if(!workspaceRun)return;
    const target=workspaceDrafts.find(item=>item.id===workspaceRun.draftId);
    if(target?.id!==draft?.id){if(target)onOpenDraft(target);return;}
    if(answer.trim()&&!window.confirm('Discard the unsaved answer and return to the active generation?'))return;
    setConversation(history.find(item=>item.id===workspaceRun.conversationId)||null);setRun(workspaceRun);
    setAnswer('');setSelected([]);setCandidateOpen(false);setReviewOpen(false);setError('');
  }
  async function applyCandidate(){
    if(!run?.resultHash||!draft||!editable||run.draftRevision!==draft.revision||!selected.length)return;
    const token=epoch.current;
    setBusy(true);setError('');
    try{
      const value=await agentApi.apply(run.id,draft.revision,run.resultHash,selected);
      if(!fresh(token))return;
      setRun(value.run);setCandidateOpen(false);setSelected([]);
      setFeedback('Selected candidate copy applied to the local draft. Nothing was scheduled, approved for publication or posted.');onApplied(value.draft);
    }catch(cause){if(fresh(token))setError(failure(cause));}
    finally{if(fresh(token))setBusy(false);}
  }
  function chooseHistory(id:string){const value=history.find(item=>item.id===id);if(!value)return;if(answer.trim()&&!window.confirm('Discard the unsaved answer and inspect this conversation?'))return;setConversation(value);setRun(runs.find(item=>item.conversationId===id)||null);setAnswer('');setReview(null);setRequest(null);setConsent(false);setSelected([]);setError('');}

  return <section className="agent-panel" aria-labelledby="agent-panel-heading">
    <div className="copilot-heading"><span aria-hidden="true">✳</span><h2 id="agent-panel-heading">Guided drafting</h2></div>
    <p className="agent-intro">Your context. One question at a time.</p>
    <div className={`agent-readiness ${ready?'ready':''}`} role="status"><span aria-hidden="true">{ready?'●':'○'}</span><span>{checking?'Checking Codex readiness…':ready?'Codex CLI available':status?.authentication==='login_required'?'Private Codex sign-in needed':'Generation unavailable'}</span></div>
    {status?.reason&&<p className="hint">{status.reason}</p>}
    <button className="text-button" type="button" disabled={checking} onClick={()=>void checkReadiness()}>Check readiness</button>
    <button className="text-button workspace-scan" type="button" disabled={scanning} onClick={()=>void scanWorkspace()}>{scanning?'Checking workspace records…':'Check workspace runs'}</button>
    <p className="agent-boundary">Checking, choosing and answering are local steps. Only Generate sends the reviewed input to a model.</p>
    {error&&<div className="agent-error" role="alert"><strong>Request needs attention.</strong><p>{error}</p></div>}
    <p className="agent-feedback" role="status" aria-live="polite">{feedback}</p>
    {workspaceRun&&isActiveRun(workspaceRun)&&workspaceRun.id!==run?.id&&<section className="tracked-run-card" aria-label="Tracked active generation"><p className="eyebrow">ACTIVE ELSEWHERE IN THIS WORKSPACE</p><h3>{workspaceDrafts.find(item=>item.id===workspaceRun.draftId)?.title||`Saved draft ${workspaceRun.draftId}`}</h3><p>{runStateLabel(workspaceRun.state)}</p><p className="hint">This request remains active while you inspect another conversation. Cancel applies only to the identified run.</p><div className="agent-actions"><button className="button" disabled={busy} onClick={showTrackedRun}>View tracked generation</button><button className="button" disabled={busy} onClick={()=>void cancelRun(workspaceRun)}>Cancel tracked generation</button><button className="button" disabled={busy} onClick={()=>void checkTrackedRun()}>Check tracked status</button></div><details className="agent-meta"><summary>Exact tracked record</summary><p>Draft: {workspaceRun.draftId}</p><p>Run: {workspaceRun.id}</p></details></section>}
    {!draft?<div className="quiet-box">Open a saved draft to begin. Add a source, your angle and the native channels in the editor.</div>:<>
      {dirty&&<div className="agent-warning">Save your draft changes before continuing guided drafting. Unsaved copy will not be sent or replaced.</div>}
      {draft.archived&&<div className="agent-warning">Restore this archived draft before starting or applying a candidate.</div>}
      <div className="agent-start">
        <label className="field">Content type<select value={contentType} disabled={busy||knownActive} onChange={event=>setContentType(event.target.value as ContentType)}><option value="article">Article / adaptation</option><option value="reflection">Personal reflection</option><option value="news">News & opinion</option><option value="launch">Product / launch</option><option value="youtube">YouTube content</option></select></label>
        <button className="button primary" type="button" disabled={!editable||busy||knownActive} onClick={()=>void startConversation()}>{busy&&!conversation?'Starting…':conversation?'Start a fresh conversation':'Start guided drafting'}</button>
      </div>
      {history.length>1&&<label className="field agent-history">Conversation history<select value={conversation?.id||''} disabled={busy} onChange={event=>chooseHistory(event.target.value)}>{history.map(item=><option key={item.id} value={item.id}>{item.contentType} · draft v{item.draftRevision} · {new Date(item.createdAt).toLocaleString()}</option>)}</select></label>}
      {stale&&<div className="agent-warning">This conversation used draft v{conversation?.draftRevision}; your current draft is v{draft.revision}. Start a fresh conversation to use the new input. Old answers and candidates remain saved.</div>}
      {conversation&&<div className="guided-conversation"><div className="agent-section-label"><span>GUIDED INTAKE</span><span>Draft v{conversation.draftRevision}</span></div>{conversation.question?<form onSubmit={event=>{event.preventDefault();void answerQuestion();}}><label className="field question-label">{conversation.question.prompt}<textarea value={answer} onChange={event=>setAnswer(event.target.value)} rows={5} disabled={busy||!editable||stale} required placeholder={conversation.question.slot==='source'?'Paste the actual source text, not only a link.':conversation.question.slot==='angle'?'Your perspective, or an explicitly neutral summary.':'Who is this for, and what should it help them understand?'}/></label>{conversation.question.slot==='angle'&&<button className="text-button" type="button" disabled={busy||!editable||stale} onClick={()=>setAnswer('Create a neutral, attributed summary. Do not invent personal opinions or experiences for me.')}>Use a neutral-summary angle</button>}<button className="button" type="submit" disabled={busy||!editable||stale||!answer.trim()}>Save answer & continue</button><p className="hint">This question follows the intake rules. It is not a generated model response.</p></form>:<><p className="agent-ready-copy">The brief is ready for your review.</p><button className="button primary" type="button" disabled={busy||!editable||stale||knownActive} onClick={()=>void prepareReview()}>Review exact input</button></>}
      </div>}
      {conversation&&<details className="agent-meta saved-intake"><summary>Saved conversation context</summary><p>Source and angle are supplied context, not verified facts.</p><pre>{JSON.stringify({source:conversation.snapshot.source,angle:conversation.snapshot.angle,objective:conversation.objective,channels:conversation.snapshot.channels,languages:conversation.snapshot.languages,formats:conversation.snapshot.formats,templateId:conversation.snapshot.templateId,templateVersion:conversation.snapshot.templateVersion},null,2)}</pre></details>}
      {conversation&&runs.filter(item=>item.conversationId===conversation.id).length>1&&<label className="field agent-history">Generation history<select value={run?.id||''} disabled={busy} onChange={event=>{setRun(runs.find(item=>item.id===event.target.value)||null);setSelected([]);setCandidateOpen(false);setReviewOpen(false);setError('');}}>{runs.filter(item=>item.conversationId===conversation.id).map(item=><option key={item.id} value={item.id}>{runStateLabel(item.state)} · {new Date(item.createdAt).toLocaleString()}</option>)}</select></label>}
      {run&&<section className="agent-run" aria-label="Generation status"><p className="eyebrow">MODEL REQUEST</p><h3>{runStateLabel(run.state)}</h3><p className="agent-progress" role="status">{run.progress}</p>{run.error&&<p className="agent-warning">{run.error.message}</p>}{active&&<><p className="hint">Closing the browser does not cancel this request. Restarted/interrupted work is never silently retried.</p><div className="agent-actions"><button className="button" disabled={busy} onClick={()=>void cancelRun()}>Cancel generation</button><button className="button" disabled={busy} onClick={()=>void checkRun()}>{pollPaused?'Check status again':'Check status'}</button></div></>}{run.state==='needs_review'&&run.result&&<><p className="hint">Generated copy is a candidate. Check source claims, tone and each platform variant.</p><button className="button primary" onClick={()=>{setSelected([]);setCandidateOpen(true);}}>Review candidate copies</button></>}{['failed','cancelled','interrupted'].includes(run.state)&&<p className="hint">No candidate was applied. Review the input and explicitly request a new run if you want to try again.</p>}{run.state==='applied'&&<p className="hint">Applied to local draft v{run.appliedDraftRevision}. You can continue editing it; no publication was approved.</p>}{run.usage&&<p className="hint">Reported usage: {run.usage.inputTokens} input / {run.usage.outputTokens} output tokens.</p>}<details className="agent-meta"><summary>Run record</summary><p>Run ID: {run.id}</p><p>Input hash: {run.inputHash}</p><p>Last update: {run.updatedAt}</p></details></section>}
      {(request&&!run)&&<button className="button" disabled={busy} onClick={()=>void checkRun()}>Check saved generation requests</button>}
    </>}
    {reviewOpen&&review&&<AgentDialog title="Review before generation" onClose={()=>setReviewOpen(false)}><p className="callout">This is the exact selected content snapshot for the model request. Source claims remain unverified until you check them.</p><p className="agent-usage-notice">{review.usageNotice}</p><label className="field">Exact input sent to Codex<textarea className="code-field agent-input-review" readOnly value={JSON.stringify(review.input,null,2)} rows={16}/></label><details className="agent-meta"><summary>Reviewed instruction bindings & input hash</summary><p>{review.inputHash}</p>{review.skillBindings.map(binding=><p key={binding.name}><strong>{binding.name}</strong><br/>{binding.sha256}</p>)}</details>{!ready&&<p className="agent-warning">Generation is unavailable until the local Codex CLI is qualified and signed in. Do not enter credentials here.</p>}{(dirty||stale)&&<p className="agent-warning">Your draft changed. Close this review, save the draft and start a fresh conversation.</p>}{error&&<p className="agent-error" role="alert">{error}</p>}<label className="check-label agent-consent"><input type="checkbox" checked={consent} disabled={busy} onChange={event=>setConsent(event.target.checked)}/><span>I agree to send this reviewed input to Codex and use model capacity. This does not authorize publishing.</span></label><div className="dialog-actions"><button className="button" type="button" onClick={()=>setReviewOpen(false)}>Keep reviewing later</button><button className="button primary" type="button" disabled={busy||!consent||!ready||!editable||stale||knownActive} onClick={()=>void generate()}>{busy?'Recording request…':request?'Retry this same request':'Generate candidate'}</button></div><p className="hint">Nothing is sent until you press Generate. A repeated request uses the same idempotency key.</p></AgentDialog>}
    {candidateOpen&&run?.result&&<AgentDialog title="Review candidate copies" onClose={()=>setCandidateOpen(false)}><div className="callout"><strong>Human fact review required.</strong> Candidate text is not verified news, a publication approval or a scheduled post.</div><section className="candidate-brief"><p className="eyebrow">CANONICAL BRIEF</p><p>{run.result.canonicalBrief}</p></section>{run.result.warnings.length>0&&<div className="candidate-warnings"><h3>Review notes</h3><ul>{run.result.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></div>}{run.result.variants.map(variant=><section className="candidate-variant" key={variant.channelId}><label className="check-label"><input type="checkbox" checked={selected.includes(variant.channelId)} onChange={()=>setSelected(current=>current.includes(variant.channelId)?current.filter(id=>id!==variant.channelId):[...current,variant.channelId])}/><strong>{channels.find(channel=>channel.id===variant.channelId)?.name||variant.channelId}</strong></label><label className="field"><span className="sr-only">{variant.channelId} candidate copy</span><textarea readOnly rows={7} value={variant.copy}/></label>{variant.notes&&<p className="hint">{variant.notes}</p>}</section>)}{(!editable||run.draftRevision!==draft?.revision)&&<p className="agent-warning">This candidate cannot overwrite a changed or unsaved draft. Save your work and create a fresh guided conversation.</p>}{error&&<p className="agent-error" role="alert">{error}</p>}<div className="dialog-actions"><button className="button" type="button" onClick={()=>setCandidateOpen(false)}>Keep candidate for later</button><button className="button primary" type="button" disabled={busy||!editable||run.draftRevision!==draft?.revision||selected.length===0||run.state!=='needs_review'} onClick={()=>void applyCandidate()}>{busy?'Applying…':`Apply ${selected.length||''} selected ${selected.length===1?'copy':'copies'} to draft`}</button></div><p className="hint">Only selected variant copies and source/angle answered in this conversation are applied. Other draft fields are preserved.</p></AgentDialog>}
  </section>;
}
