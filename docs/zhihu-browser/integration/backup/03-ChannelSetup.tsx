import {useEffect,useState} from 'react';
import {saveBlob} from './api';
import {routeLabel,setupApi,type SetupCandidate,type SetupChannel} from './setupApi';
import type {Channel} from './types';
import BlueskyConnection from './BlueskyConnection';
import YouTubeConnection from './YouTubeConnection';
import InstagramConnection from './InstagramConnection';
import TikTokConnection from './TikTokConnection';
import ThreadsConnection from './ThreadsConnection';
import PinterestConnection from './PinterestConnection';
import RedditConnection from './RedditConnection';
import XiaohongshuConnection from './XiaohongshuConnection';

export default function ChannelSetup({channel}:{channel:Channel}) {
  const [readiness,setReadiness]=useState<SetupChannel|null>(null),[error,setError]=useState('');
  const [nativeFormat,setNativeFormat]=useState(channel.formats[0]?.id||'');
  const [accountLabel,setAccountLabel]=useState(''),[destinationLabel,setDestinationLabel]=useState('');
  const [candidate,setCandidate]=useState<SetupCandidate|null>(null),[busy,setBusy]=useState(false);
  useEffect(()=>{let active=true;setupApi.readiness().then(result=>{
    if(!active)return;
    const row=result.channels.find(item=>item.id===channel.id);
    if(!row)throw new Error('This channel is missing from the readiness catalog.');
    setReadiness(row);
  }).catch(cause=>{if(active)setError(cause instanceof Error?cause.message:'Readiness could not load.');});return()=>{active=false;};},[channel.id]);
  function changed(){setCandidate(null);setError('');}
  async function prepare(event:React.SubmitEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');setCandidate(null);
    try{setCandidate(await setupApi.prepare({channel:channel.id,nativeFormat,accountLabel,destinationLabel}));}
    catch(cause){setError(cause instanceof Error?cause.message:'The setup plan could not be prepared.');}
    finally{setBusy(false);}
  }
  return <section className="setup-panel" aria-label="Channel setup planning">
    {channel.id==='bluesky'&&<BlueskyConnection/>}
    {channel.id==='youtube'&&<YouTubeConnection/>}
    {channel.id==='instagram'&&<InstagramConnection/>}
    {channel.id==='tiktok'&&<TikTokConnection/>}
    {channel.id==='threads'&&<ThreadsConnection/>}
    {channel.id==='pinterest'&&<PinterestConnection/>}
    {channel.id==='reddit'&&<RedditConnection/>}
    {channel.id==='xiaohongshu'&&<XiaohongshuConnection/>}
    {channel.id==='bilibili'&&<section><h3>Bilibili upload</h3><p>Connect your personal account and review a video for upload using bililive-auto-upload.</p><button className="button" onClick={async()=>{setError('');try{const response=await fetch('/api/connections/bilibili/open',{method:'POST',headers:{'X-Studio-Request':'1'}});const data=await response.json();if(!response.ok)throw new Error(data.error?.message||'Bilibili could not open');window.location.assign(data.url);}catch(e){setError(e instanceof Error?e.message:'Bilibili could not open');}}}>Open Bilibili connection and upload</button></section>}
    <h3>Prepare account setup</h3>
    <p>{channel.publishReady?'This channel has a qualified publishing route. Choose the exact destination to assess; every post still requires its own content review and approval.':channel.connection==='connected_identity'?'Your account identity is connected. Choose the exact destination to assess; publishing remains unavailable until a separate route test and exact post approval.':'Choose the exact destination to assess. Use public labels only. Your account remains unverified until a private connection and route test are completed.'}</p>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    {readiness&&<>
      <p className="callout"><strong>{readiness.publishReady?'Controlled browser route':routeLabel(readiness.candidateRoute)}</strong><br/>{readiness.pilotScope}. Available now: {readiness.availableRoute==='controlled_browser'?'controlled browser':'manual handoff'}.</p>
      {readiness.documentationState==='documentation_unavailable'&&<p className="muted">Current portal documentation could not be checked. Browser compatibility remains unverified.</p>}
      <form onSubmit={prepare}>
        <fieldset disabled={busy} className="setup-fields">
          <label className="field">Native format<select value={nativeFormat} onChange={e=>{setNativeFormat(e.target.value);changed();}}>{channel.formats.map(format=><option key={format.id} value={format.id}>{format.label} · {format.id}</option>)}</select></label>
          <label className="field">Public account label<input required maxLength={160} autoComplete="off" value={accountLabel} onChange={e=>{setAccountLabel(e.target.value);changed();}} placeholder="Profile name or public handle"/></label>
          <label className="field">Exact destination label<input required maxLength={160} autoComplete="off" value={destinationLabel} onChange={e=>{setDestinationLabel(e.target.value);changed();}} placeholder="Name the profile, page or channel"/></label>
          <p className="hint">Do not enter passwords, tokens or cookies. These labels are used only in the candidate you can download. Close this dialog to clear it.</p>
          <button className="button" type="submit" disabled={!accountLabel.trim()||!destinationLabel.trim()}>{busy?'Preparing…':'Preview setup plan'}</button>
        </fieldset>
      </form>
      {candidate&&<div className="setup-result" role="status" aria-label="Setup plan preview">
        <h3>Setup candidate · not connected</h3>
        <p><strong>{candidate.target.accountLabel}</strong> → {candidate.target.destinationLabel}</p>
        <p>{candidate.target.nativeFormat} · {routeLabel(candidate.candidateRoute)}</p>
        <ol>{candidate.requirements.map(item=><li key={item.id}>{item.detail}</li>)}</ol>
        <p className="muted">Creating this plan grants no setup or publication permission. Scopes, costs and connection details still need review.</p>
        <button className="button" onClick={()=>saveBlob(new Blob([JSON.stringify(candidate,null,2)+'\n'],{type:'application/json'}),`studio-setup-${channel.id}.json`)}>Download setup candidate</button>
        <details><summary>Evidence and plan fingerprint</summary><code className="setup-hash">{candidate.manifestHash}</code>{candidate.sources.map(source=><p key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a><br/>{source.note} {source.checkedAt?`Checked ${source.checkedAt}.`:''}</p>)}{!candidate.sources.length&&<p>No current operation documentation reviewed yet.</p>}</details>
      </div>}
    </>}
  </section>;
}
