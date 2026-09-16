import {test, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {api, ApiError} from '../src/api.ts';
import {emptyDraft, draftInput, type Draft} from '../src/types.ts';

const realFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=realFetch;});

test('GET uses the same-origin owner session and never a mutation marker',async()=>{
  globalThis.fetch=async(url,options)=>{
    assert.equal(url,'/api/bootstrap');
    assert.equal(options?.credentials,'same-origin');
    assert.equal(new Headers(options?.headers).has('X-Studio-Request'),false);
    return Response.json({drafts:[]});
  };
  assert.deepEqual(await api('/api/bootstrap'),{drafts:[]});
});

test('JSON draft mutations include the local CSRF marker and expected revision',async()=>{
  globalThis.fetch=async(_url,options)=>{
    const headers=new Headers(options?.headers);
    assert.equal(headers.get('X-Studio-Request'),'1');
    assert.equal(headers.get('Content-Type'),'application/json');
    assert.equal(JSON.parse(String(options?.body)).expectedRevision,4);
    return Response.json({draft:{revision:5}});
  };
  assert.deepEqual(await api('/api/drafts/id',{method:'PUT',body:JSON.stringify({expectedRevision:4})}),{draft:{revision:5}});
});

test('file uploads leave multipart boundary generation to the browser',async()=>{
  const form=new FormData();
  form.append('file',new Blob(['local-image'],{type:'image/png'}),'image.png');
  globalThis.fetch=async(_url,options)=>{
    assert.equal(new Headers(options?.headers).get('X-Studio-Request'),'1');
    assert.equal(new Headers(options?.headers).has('Content-Type'),false);
    assert.equal(options?.body,form);
    return Response.json({asset:{id:'local'}});
  };
  await api('/api/assets',{method:'POST',body:form});
});

test('a revision conflict remains a 409 with a specific recoverable message',async()=>{
  globalThis.fetch=async()=>Response.json({error:{code:'revision_conflict',message:'Another editor saved revision 5.'}},{status:409});
  await assert.rejects(api('/api/drafts/id'),(error:unknown)=>error instanceof ApiError&&error.status===409&&error.code==='revision_conflict'&&error.message.includes('revision 5'));
});

test('unavailable service gives an explicit offline state instead of sample records',async()=>{
  globalThis.fetch=async()=>{throw new TypeError('network unavailable');};
  await assert.rejects(api('/api/bootstrap'),(error:unknown)=>error instanceof ApiError&&error.status===0&&error.code==='offline'&&error.message.includes('unsaved input'));
});

test('non-JSON HTTP failure is retained rather than reported as save success',async()=>{
  globalThis.fetch=async()=>new Response('Unavailable',{status:503});
  await assert.rejects(api('/api/drafts/id'),(error:unknown)=>error instanceof ApiError&&error.status===503&&error.message.includes('input has been kept'));
});

test('new workspaces create genuinely empty drafts with no generated beliefs',()=>{
  const draft=emptyDraft();
  assert.equal(draft.source,'');
  assert.equal(draft.angle,'');
  assert.deepEqual(draft.channels,[]);
  assert.deepEqual(draft.copies,{});
  assert.equal(draft.templateVersion,0);
  assert.equal(draft.plannedAt,'');
  assert.equal('published' in draft,false);
});

test('editable payload excludes server-controlled identity and status fields',()=>{
  const draft={...emptyDraft(),title:'A real user-supplied idea',id:'one',revision:4,archived:false,status:'draft',planningState:'unplanned',createdAt:'date',updatedAt:'date'} as Draft;
  const payload=draftInput(draft);
  assert.equal(payload.title,draft.title);
  for(const key of ['id','revision','archived','status','planningState','createdAt','updatedAt'])assert.equal(key in payload,false);
});
