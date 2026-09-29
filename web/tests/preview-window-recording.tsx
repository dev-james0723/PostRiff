'use client';
import { useState } from 'react';
import { PreviewWindow } from '@/components/application/post-preview/preview-window';
import { PostPreview } from '@/components/application/post-preview/post-preview';
import { VariantCard } from '@/features/agent/variant-card';
import type { RunVariant } from '@/lib/api/types';

const text = 'A good idea deserves room to breathe.\n\nStart with one clear thought. Shape it for the people reading it. Keep the details that make it yours.\n\nLess noise. More meaning.\n\nWhat are you working on this week?';
const variants = [{ platform: 'Threads', language: 'en', text, unknowns: [], warnings: [] }] as RunVariant[];
const post = { channel: 'threads', channelName: 'Threads', account: 'Rafii Studio', text, media: [], publishAt: new Date('2026-09-29T13:00:00Z'), timeZone: 'America/New_York' };
export default function RecordingFixture() {
  const [active, setActive] = useState(true);
  return <main id='main-content' className='demo-root'>
    <header className='demo-header'>
      <div><strong>Rafii<span className='demo-dot'>.</span></strong><span className='demo-subtitle'>Conversation preview</span></div>
      <div className='demo-action'><span id='demo-device'>DESKTOP</span><p id='demo-action'>Keep the phone beside your conversation.</p></div>
    </header>
    <div className='demo-rail' aria-hidden><b>Workspace</b><p>Home</p><p className='demo-selected'>Conversations</p><p>Library</p><p>Queue</p><p>Settings</p><small>Component recording<br/>Sample content only</small></div>
    <div data-conversation-layout className='demo-layout'>
      <section className='demo-thread'>
        <span className='demo-eyebrow'>CONVERSATION</span><h1>Give this idea a voice.</h1>
        <p className='demo-intro'>One draft, with its real platform preview beside it.</p>
        <div className='demo-user'>Turn my notes into a short Threads post. Keep it clear and human.</div>
        <div className='demo-answer'><span className='demo-avatar'>R</span><div><b>Rafii</b><p>Here is the draft. You can keep reading while checking how it looks in the app.</p></div></div>
        <VariantCard variants={variants} selected={0} onSelect={()=>{}} preview={(_, options)=><PostPreview post={post} scale={options?.scale ?? 0.62} />} />
        <p className='demo-note'>Sample draft for this recording. Nothing will be posted.</p>
        {Array.from({length:26}, (_,i)=><div className='demo-message' key={i}>
          <div className='demo-message-heading'><span className='demo-avatar'>R</span><b>Rafii</b><small>Draft conversation</small></div>
          <h2>{['Keep the opening specific.','Let the structure do the work.','Make the next step easy.'][i%3]}</h2>
          <p>{['Lead with the idea, not a long introduction. A clear first sentence gives readers a reason to stay.','Use short paragraphs and give each thought its own space. The preview lets you check the rhythm as you scroll.','End with one natural question. Keep the tone consistent and leave room for a real response.'][i%3]}</p>
        </div>)}
      </section>
      <aside className='demo-inspector'><div className='demo-inspector-sticky'>
        <div className='demo-tabs'><button data-demo-preview aria-pressed={active} onClick={()=>setActive(true)}>Preview</button><button data-demo-sources aria-pressed={!active} onClick={()=>setActive(false)}>Sources · 2</button></div>
        <PreviewWindow active={active} available label='Threads · English' onDock={()=>setActive(true)}>
          {(scale)=><PostPreview post={post} scale={scale} />}
        </PreviewWindow>
        {!active && <div data-demo-source-content className='demo-sources'><article><small>WRITING NOTES</small><h3>One clear idea</h3><p>Stay specific, use short paragraphs, and write like a person.</p></article><article><small>VOICE GUIDE</small><h3>Less noise. More meaning.</h3><p>Clear, grounded, conversational. Sample sources for this recording.</p></article></div>}
      </div></aside>
    </div>
    <div className='demo-provenance'>ACTUAL COMPONENTS · ISOLATED DEMO · SAMPLE CONTENT · 08bbd52</div>
    <style>{`
      html{background:#f7f8fa!important;color-scheme:light}body{margin:0;background:#f7f8fa!important;color:#25282e!important}
      .demo-root{min-height:100vh;font-family:Arial,Helvetica,sans-serif}.demo-header{position:sticky;top:0;z-index:40;height:92px;background:rgba(255,255,255,.97);border-bottom:1px solid #e7e9ee;display:flex;align-items:center;justify-content:space-between;padding:0 32px;gap:18px}.demo-header strong{font-size:29px;letter-spacing:-1px}.demo-dot{color:#7869f3}.demo-subtitle{display:inline-block;margin-left:22px;padding-left:22px;border-left:1px solid #ddd;color:#858890;font-size:14px}.demo-action{text-align:right;max-width:680px}.demo-action span{font-size:10px;letter-spacing:2px;color:#7a728f;font-weight:700}.demo-action p{margin:5px 0 0;font-size:16px;font-weight:500;color:#292635}.demo-rail{position:fixed;top:92px;bottom:0;left:0;width:188px;padding:36px 20px;border-right:1px solid #e7e9ee;background:#fff}.demo-rail b{color:#91939b;letter-spacing:1px;font-size:10px;text-transform:uppercase}.demo-rail p{font-size:13px;padding:11px 12px;margin:12px 0;border-radius:10px;color:#858890}.demo-rail .demo-selected{color:#292635;background:#f0eefb;font-weight:600}.demo-rail small{position:absolute;bottom:48px;font-size:11px;line-height:1.8;color:#9a9ca4}.demo-layout{display:grid;grid-template-columns:minmax(0,1fr) 336px;gap:40px;padding:36px 32px 80px;margin-left:188px}.demo-thread{min-width:0;max-width:720px}.demo-eyebrow{font-size:10px;font-weight:700;letter-spacing:2px;color:#91939b}.demo-thread h1{font-size:30px;font-weight:500;letter-spacing:-1px;margin:10px 0}.demo-intro{font-size:14px;color:#8a8c93;margin:0 0 28px}.demo-user{background:#efedf7;padding:18px 20px;border-radius:18px;font-size:14px;line-height:1.7;max-width:85%;margin-left:auto;margin-bottom:28px}.demo-answer{display:flex;gap:12px;align-items:flex-start;margin:22px 0}.demo-avatar{display:inline-flex;align-items:center;justify-content:center;background:#efedf7;color:#66568c;border:1px solid #e6e0f2;border-radius:10px;width:32px;height:32px;flex-shrink:0;font-size:13px;font-weight:600}.demo-answer b,.demo-message b{font-size:12px;font-weight:600}.demo-answer p{font-size:14px;line-height:1.8;margin-top:7px;color:#62656d}.demo-note{font-size:11px;color:#9799a1;margin:14px 0 26px}.demo-message{margin:24px 0;padding:24px;background:#fff;border:1px solid #e7e9ee;border-radius:16px}.demo-message-heading{display:flex;align-items:center;gap:10px}.demo-message-heading small{font-size:10px;color:#9799a1;margin-left:auto}.demo-message h2{font-size:17px;margin:18px 0 12px;font-weight:500}.demo-message p{font-size:14px;line-height:1.9;color:#787b84}.demo-inspector{min-width:0}.demo-inspector-sticky{position:sticky;top:112px}.demo-tabs{display:flex;border:1px solid #e4e5ec;border-radius:11px;padding:4px;margin-bottom:15px;background:#edecf1;gap:4px}.demo-tabs button{flex:1;height:36px;font-size:12px;border-radius:7px;color:#787680}.demo-tabs button[aria-pressed=true]{background:#fff;color:#272332;box-shadow:0 1px 3px #00000009}.demo-sources article{padding:20px;background:#fff;border:1px solid #e7e9ee;border-radius:14px;margin:14px 0}.demo-sources small{font-size:9px;letter-spacing:1.4px;color:#9a959f}.demo-sources h3{font-size:16px;margin:10px 0}.demo-sources p{font-size:13px;line-height:1.8;color:#7f7989}.demo-provenance{position:fixed;bottom:0;left:0;right:0;z-index:70;height:24px;display:flex;align-items:center;justify-content:center;background:#eeedf4ed;color:#827d91;font-size:9px;letter-spacing:1.5px;pointer-events:none}
      @media(max-width:1199px){.demo-rail{display:none}.demo-layout{margin-left:0;gap:24px;padding:24px;grid-template-columns:minmax(0,1fr) 280px}.demo-header{padding:0 24px}.demo-subtitle{display:none}.demo-action p{font-size:14px}.demo-inspector-sticky{top:108px}}
      @media(max-width:767px){.demo-layout{display:block;padding:24px 18px 60px}.demo-inspector{display:none}.demo-header{height:116px;display:block;padding:13px 18px}.demo-header strong{font-size:23px}.demo-action{text-align:left;margin-top:8px}.demo-action span{font-size:8px;letter-spacing:1.5px}.demo-action p{font-size:12px;line-height:1.4;margin-top:3px}.demo-thread h1{font-size:25px}.demo-user{max-width:95%;padding:15px}.demo-provenance{font-size:6.5px;letter-spacing:.6px}.demo-message{padding:18px}}
    `}</style>
  </main>;
}
