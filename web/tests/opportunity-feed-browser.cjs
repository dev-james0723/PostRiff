/** UI contract acceptance only: real app/session shell, synthetic TaskV1 HTTP responses, no models/providers. */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { isDeepStrictEqual } = require('node:util');
const { randomUUID } = require('node:crypto');
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:4439';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw Error('Cloud disposable harness only');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')));
const out = path.resolve(args.out || '../artifacts/opportunity-feed'); fs.mkdirSync(out, { recursive: true });
const name = args.browser === 'webkit' ? 'webkit' : 'chromium';
const principal = randomUUID();
const headers = { Authorization: `Bearer dev:${principal}`, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Origin: base };
const checks = [];
function check(label, ok) { checks.push({ name: label, ok: Boolean(ok) }); console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); assert(ok, label); }
const tours = [...fs.readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const tourState = { completed: {}, dismissed: Object.fromEntries(tours.map((id) => [id, 1])), nudged: Object.fromEntries(tours.map((id) => [id, 1])) };
let activePage;
const digest = 'a'.repeat(64);
const selection = { suggestionId: 'suggestion-a', platforms: ['Threads'], budgetCeilingUsdMicro: 0 };
function preview(w) { return { ...selection, workspaceId: w, digest, observation: 'Confirmed campaign has no draft.', source: { id: 'campaign-a', type: 'campaign', revision: 1, goal: 'Recital', audience: 'Neighbours', facts: { venue: 'Studio' } }, expectedBenefit: { kind: 'estimate', text: 'A reviewable draft; engagement impact is unmeasured.' }, effort: 'Review each draft.', cost: { state: 'unknown', text: 'Price unavailable; text credits apply.', ceilingUsdMicro: 0 }, permissions: ['Workspace edit','Agent create/edit grants'], inputs: { brief: 'Use confirmed campaign facts only: recital at Studio for Neighbours.', platforms: ['Threads'] }, canCreate: true, permissionReason: 'allowed' }; }
function entry() { return { taskId: 'task-a', title: 'Prepare recital drafts', state: 'completed', href: '/app/tasks?task=task-a', observation: 'Confirmed campaign has no draft.', expectedBenefit: { text: 'Unmeasured expected benefit.' }, drafts: [{ id: 'draft-a', platform: 'Threads', revision: 1, href: '/app/queue?view=drafts&draft=draft-a' }], jobs: [{ id: 'job-a', platform: 'Threads', state: 'queued', verified: false, verifiedAt: null, providerReference: null, href: '/app/queue?job=job-a' }], experiment: { hypothesis: 'May close a content gap.' }, measurement: { status: 'unavailable', reason: 'No metric reading exists.' }, analyticsHref: '/app/analytics' }; }
(async () => {
 const seed = await fetch(`${base}/api/auth/verify`, { method: 'POST', headers, body: '{}' });
 if (!seed.ok) throw Error(`Harness auth ${seed.status}`);
 const { workspaceId: w } = await seed.json();
 const snapshot = await fetch(`${base}/api/workspaces/${w}`, { headers }).then(r=>r.json());
 snapshot.state.raffi ??= {}; snapshot.state.raffi.suggestions = [{ id: 'suggestion-a', kind: 'campaign_gap', reason: 'Confirmed campaign has no draft.', status: 'open', evidence: [{type:'campaign',id:'campaign-a',revision:1}], action:'campaign' }];
 const browser = await (name === 'webkit' ? webkit : chromium).launch({headless:true});
 try { for (const width of [1440,390]) {
  const ctx = await browser.newContext({viewport:{width,height:1000},colorScheme:'dark',locale:'en-US',reducedMotion:'reduce'});
  await ctx.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  await ctx.addInitScript(({id,tours})=>{localStorage.setItem('postriff-dev-principal',id);localStorage.setItem('postriff-onboarding',JSON.stringify(tours));},{id:principal,tours:tourState});
  const creates=[], decisions=[];let drop=true,stale=false,deny=false,uncertainStatus=0,card=entry(), experimentUnknown=false, experimentStale=false;
  const common={digest:'b'.repeat(64),reason:'A specific observed source signal.',source:'Current workspace activity',state:'open',observedAt:1791586800,expiresAt:null,evidence:[{type:'campaign',id:'campaign-a',revision:1}],expectedBenefit:{kind:'estimate',text:'Benefit is unmeasured.'},cost:{state:'no_provider_call',text:'Review only; no provider call.'},permissions:['Workspace edit'],dismissalScope:'workspace',preview:'Open the existing source and review its actual content.'};
  let opportunities=[
   {...common,id:'suggestion:suggestion-a',family:'suggestion',sourceId:'suggestion-a',title:'Campaign ready for a draft',action:{kind:'prepare_task',label:'Review draft task',suggestionId:'suggestion-a'}},
   {...common,id:'suggestion:asset',family:'suggestion',sourceId:'asset',title:'Unused image',evidence:[{type:'asset',id:'image-a',revision:1}],action:{kind:'open',label:'Open asset for review',href:'/app/library'}},
   {...common,id:'performance:h',family:'performance',sourceId:'h',title:'Question openings may perform better',source:'Authorized account performance',action:{kind:'experiment',label:'Define comparison experiment'},measurement:{kind:'observed',metric:'views',definitionVersion:'native-v1',window:'24h',dateRange:[1791500400,1791586800],samples:{a:6,b:6},comparison:{accountId:'account-a',accountLabel:'Studio A',provider:'threads',language:'en',contentTypeId:null,dimension:'opening',armA:'question',armB:'statement'},causal:false},preview:'Alternate the two arms for the next comparable posts.'}
  ];
  opportunities.push({...opportunities[2],id:'performance:h-b',title:'Second account comparison',measurement:{...opportunities[2].measurement,comparison:{...opportunities[2].measurement.comparison,accountId:'account-b',accountLabel:'Studio B'}},action:{kind:'open',label:'Review other account experiment',href:'/app/workspace/personalization'}});
  const feed=()=>({workspaceId:w,items:opportunities,hasMore:false,coverage:'Current permitted sources only. Missing metrics are withheld.',sourceLinks:[{label:'Review analytics and outcomes',href:'/app/analytics'}]});
  await ctx.route(`**/api/workspaces/${w}`,route=>route.fulfill({json:snapshot}));
  await ctx.route(`**/api/workspaces/${w}/agent/creator-pipeline**`,async route=>{
   const url=new URL(route.request().url());
   if(url.pathname.endsWith('/opportunities')||url.pathname.endsWith('/opportunities/refresh')) return deny?route.fulfill({status:403,json:{error:'Opportunity access changed.'}}):route.fulfill({json:feed()});
   if(url.pathname.endsWith('/opportunities/decide')) {const body=route.request().postDataJSON();decisions.push(body);if(experimentStale&&body.decision==='experiment')return route.fulfill({status:409,json:{error:'This opportunity changed. Review its current evidence.'}});opportunities=body.decision==='dismiss'?opportunities.filter(i=>i.id!==body.id):opportunities.map(i=>i.id===body.id?{...i,digest:'c'.repeat(64),state:'experiment',experiment:{outcome:'unmeasured',measurementWindow:'24h'},action:{kind:'open',label:'Review performance experiment',href:'/app/workspace/personalization'}}:i);if(experimentUnknown){experimentUnknown=false;return route.abort('failed');}return route.fulfill({json:{workspaceId:w,id:body.id,state:body.decision==='experiment'?'experiment':'dismissed',verified:true,note:'Existing source decision saved.'}});}
   if(url.pathname.endsWith('/preview')) return route.fulfill({json:preview(w)});
   if(url.pathname.endsWith('/create')) { creates.push(route.request().postDataJSON()); if(uncertainStatus)return route.fulfill({status:uncertainStatus,json:{error:'Ambiguous gateway response.'}}); if(stale)return route.fulfill({status:409,json:{error:'The campaign changed. Review the new preview.'}});if(drop){drop=false;return route.abort('failed');}return route.fulfill({json:{taskId:'task-a',href:'/app/tasks?task=task-a',replayed:true}}); }
   return deny?route.fulfill({status:403,json:{error:'Access changed.'}}):route.fulfill({json:{workspaceId:w,items:[card],hasMore:false}});
  });
  const page=await ctx.newPage();activePage=page;await page.goto(`${base}/app/creator-pipeline?suggestion=suggestion-a`,{waitUntil:'domcontentloaded'});
  await page.getByRole('heading',{level:1,name:'Creator Pipeline',exact:true}).waitFor({timeout:180000});
  await page.getByRole('region',{name:'Opportunity Feed',exact:true}).waitFor();
  check(`${name} ${width}: source-backed opportunities expose observed window and honest native review`,await page.getByRole('link',{name:'Open asset for review',exact:true}).getAttribute('href')==='/app/library'&&(await page.getByRole('article',{name:'Question openings may perform better'}).textContent()).includes('24h reading window'));
  await page.getByRole('button',{name:'Review draft task',exact:true}).click();
  check(`${name} ${width}: feed prepares selection without execution`,await page.getByLabel('Suggestion',{exact:true}).inputValue()==='suggestion-a'&&creates.length===0);
  await page.getByRole('button',{name:'Review task',exact:true}).click();
  const panel=page.getByRole('region',{name:'Exact task preview'});await panel.waitFor();
  check(`${name} ${width}: exact facts, expected benefit and unknown cost are visible`,(await panel.textContent()).includes('Studio')&&(await panel.textContent()).includes('Price unavailable')&&(await panel.textContent()).includes('estimate'));
  check(`${name} ${width}: preview does not create a task`,creates.length===0);
  await panel.getByRole('button',{name:'Create approval task',exact:true}).click();await page.getByRole('region',{name:'Reconcile pending request'}).waitFor();
  check(`${name} ${width}: unknown result locks original request controls`,await page.getByLabel('Suggestion',{exact:true}).isDisabled()&&await page.getByRole('button',{name:'Back',exact:true}).isDisabled());
  await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'Reconcile same request',exact:true}).waitFor();
  check(`${name} ${width}: remount never automatically resubmits`,creates.length===1);
  await page.getByRole('button',{name:'Reconcile same request',exact:true}).click();await page.getByRole('link',{name:'Review in Task Center',exact:true}).waitFor();
  check(`${name} ${width}: reconciliation keeps exact key/body`,creates.length===2&&isDeepStrictEqual(creates[0],creates[1]));
  check(`${name} ${width}: completed draft task cannot claim queued publication`,await page.getByText('Publication not verified · Threads · queued',{exact:true}).isVisible());
  await page.getByText('Experiment and observed outcomes',{exact:true}).click();
  check(`${name} ${width}: unavailable analytics is not zero benefit`,await page.getByText('Measurement: unavailable. No metric reading exists.',{exact:true}).isVisible());
  for(const status of [408,429]) {
   uncertainStatus=status;const before=creates.length;await page.getByRole('button',{name:'Review task',exact:true}).click();await panel.getByRole('button',{name:'Create approval task',exact:true}).click();await page.getByText('Ambiguous gateway response.',{exact:true}).waitFor();
   check(`${name} ${width}: HTTP ${status} retains locked reconciliation`,await page.getByRole('button',{name:'Back',exact:true}).isDisabled());
   uncertainStatus=0;await page.getByRole('button',{name:'Reconcile same request',exact:true}).click();await page.getByRole('link',{name:'Review in Task Center',exact:true}).waitFor();
   check(`${name} ${width}: HTTP ${status} retry retains same key/body`,creates.length===before+2&&isDeepStrictEqual(creates[before],creates[before+1]));
  }
  stale=true;await page.getByRole('button',{name:'Review task',exact:true}).click();await panel.getByRole('button',{name:'Create approval task',exact:true}).click();await page.getByText('The campaign changed. Review the new preview.',{exact:true}).waitFor();
  check(`${name} ${width}: stale server preview ends confirmation without new authority`,await panel.count()===0&&await page.getByRole('region',{name:'Reconcile pending request'}).count()===0);
  card={...card,jobs:[{...card.jobs[0],state:'verified',verified:true,verifiedAt:1791586800,providerReference:'synthetic-provider-post'}]};await page.getByRole('button',{name:'Refresh results',exact:true}).click();await page.getByText('Provider publication verified · Threads · verified',{exact:true}).waitFor();
  check(`${name} ${width}: verified display needs actual-shaped receipt fields`,await page.getByRole('link',{name:'Inspect publishing receipt',exact:true}).isVisible());
  experimentStale=true;await page.getByRole('button',{name:'Define comparison experiment',exact:true}).click();const experiment=page.getByRole('region',{name:'Exact experiment preview'});await experiment.waitFor();
  check(`${name} ${width}: exact experiment identifies account and both arms`,(await experiment.textContent()).includes('Studio A (account-a)')&&(await experiment.textContent()).includes('question versus statement')&&!(await experiment.textContent()).includes('Studio B')&&(await page.getByRole('article',{name:'Second account comparison',exact:true}).textContent()).includes('Studio B (account-b)'));
  check(`${name} ${width}: experiment has exact observed window and no generation claim`,(await experiment.textContent()).includes('24h reading window')&&(await experiment.textContent()).includes('does not generate'));
  await experiment.getByRole('button',{name:'Confirm experiment',exact:true}).click();await page.getByText('This opportunity changed. Review its current evidence.',{exact:true}).waitFor();
  check(`${name} ${width}: stale experiment evidence cannot be silently accepted`,await experiment.count()===0&&opportunities.some(i=>i.id==='performance:h'&&i.state==='open'));
  experimentStale=false;experimentUnknown=true;await page.getByRole('button',{name:'Define comparison experiment',exact:true}).click();await experiment.getByRole('button',{name:'Confirm experiment',exact:true}).click();await page.getByText('Decision outcome unknown. Refresh source records before another action; nothing is automatically retried.',{exact:true}).waitFor();
  const beforeDecisions=decisions.length;
  check(`${name} ${width}: unknown experiment locks replacement decisions`,await page.getByRole('button',{name:'Close preview',exact:true}).isDisabled()&&await page.getByRole('button',{name:'Dismiss for workspace',exact:true}).first().isDisabled());
  await page.getByRole('button',{name:'Refresh opportunities',exact:true}).click();await page.getByText('Experiment defined. Outcome: unmeasured.',{exact:true}).waitFor();
  check(`${name} ${width}: reconcile reads existing outcome without duplicate POST`,decisions.length===beforeDecisions&&await page.getByRole('button',{name:'Define comparison experiment',exact:true}).count()===0);
  const asset=page.getByRole('article',{name:'Unused image',exact:true});await asset.getByRole('button',{name:'Dismiss for workspace',exact:true}).click();await asset.waitFor({state:'detached'});await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('region',{name:'Opportunity Feed',exact:true}).waitFor();
  check(`${name} ${width}: dismissal persists across remount`,await asset.count()===0&&decisions.at(-1).decision==='dismiss');
  check(`${name} ${width}: no horizontal overflow`,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,`${name}-${width}-opportunities.png`),fullPage:true});
  deny=true;await page.getByRole('button',{name:'Refresh results',exact:true}).click();await page.getByText('Access changed.',{exact:true}).waitFor();
  check(`${name} ${width}: revoked read removes stale result`,await page.getByRole('heading',{name:'Prepare recital drafts',exact:true}).count()===0);
  await page.getByRole('button',{name:'Refresh opportunities',exact:true}).click();await page.getByText('Opportunity access changed.',{exact:true}).first().waitFor();
  check(`${name} ${width}: revoked source fetch removes cached opportunity bodies`,await page.getByRole('article',{name:'Question openings may perform better',exact:true}).count()===0);
  await ctx.close();
 }} catch(error) { if(activePage && !activePage.isClosed()) await activePage.screenshot({path:path.join(out,`${name}-opportunities-failure.png`),fullPage:true}); throw error; } finally { await browser.close();fs.writeFileSync(path.join(out,`${name}-opportunities-receipt.json`),JSON.stringify({execution:'synthetic API fixtures in real native app/browser',checks},null,2)); }
})().catch(e=>{console.error(e);process.exitCode=1;});
