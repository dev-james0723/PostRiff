/* Reuse the existing Growth Phase 2 browser acceptance on this owned harness.
   Only loopback port, installed Chrome and disposable-fixture routing change. */
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'../../../..'),original=path.join(root,'web/tests/growth-phase2-browser.cjs');
let source=fs.readFileSync(original,'utf8');
assertContains("const base='http://127.0.0.1:3296'");
assertContains('chromium.launch({headless:true})');
source=source.replace("const base='http://127.0.0.1:3296'","const base='http://127.0.0.1:33404'").replace('chromium.launch({headless:true})',"chromium.launch({headless:true,channel:'chrome'})");
const beforeEmpty="execFileSync(python,['tests/phase2/growth_phase2_browser_fixture.py','55796',principal,wid,'empty'],{cwd:root});";
assertContains(beforeEmpty);
source=source.replace(beforeEmpty,`
execFileSync(python,['tests/phase2/review_fixture.py','55404',principal,wid,'calibration_seed'],{cwd:root});
await page.goto(base+'/app/growth',{waitUntil:'domcontentloaded'});await page.getByRole('tab',{name:'Your patterns',exact:true}).click();
const patterns=page.getByRole('tabpanel');await patterns.getByRole('button',{name:'Prepare a calibration',exact:true}).waitFor();
assert.ok(await patterns.getByRole('button',{name:'Prepare a calibration',exact:true}).isEnabled());
await patterns.getByRole('button',{name:'Prepare a calibration',exact:true}).click();
await patterns.getByRole('checkbox',{name:'I reviewed the evidence and want this version used.',exact:true}).waitFor();
const first=await patterns.getByLabel('Calibration version',{exact:true}).inputValue();
assert.ok(await patterns.getByRole('button',{name:'Use this calibration',exact:true}).isDisabled());
await patterns.getByRole('checkbox',{name:'I reviewed the evidence and want this version used.',exact:true}).check();
await patterns.getByRole('button',{name:'Use this calibration',exact:true}).click();
await patterns.getByRole('button',{name:'Use this calibration',exact:true}).waitFor({state:'detached'});
await patterns.getByRole('button',{name:'Prepare a calibration',exact:true}).click();
await patterns.getByRole('checkbox',{name:'I reviewed the evidence and want this version used.',exact:true}).waitFor();
await patterns.getByRole('checkbox',{name:'I reviewed the evidence and want this version used.',exact:true}).check();
await patterns.getByRole('button',{name:'Use this calibration',exact:true}).click();
await patterns.getByRole('button',{name:'Use this calibration',exact:true}).waitFor({state:'detached'});
await patterns.getByLabel('Calibration version',{exact:true}).selectOption(first);
await patterns.getByRole('checkbox',{name:'I reviewed the evidence and want this version used.',exact:true}).check();
await patterns.getByRole('button',{name:'Restore this calibration',exact:true}).click();
await patterns.getByRole('button',{name:'Restore this calibration',exact:true}).waitFor({state:'detached'});
await shot('calibration-owner-restored');
checks.push('existing chronological calibration with explicit owner approve, second version and restore; no automatic timing or frequency preference');
${beforeEmpty}
`);
const adapted=new Module(original,module);adapted.filename=original;adapted.paths=Module._nodeModulePaths(path.dirname(original));
const originalRequire=adapted.require.bind(adapted);
adapted.require=name=>name==='node:child_process'?{execFileSync:(file,args,options)=>{
  if(args?.[0]==='tests/phase2/growth_phase2_browser_fixture.py'){
    if(args[1]!=='55796')throw new Error('Unexpected fixture target');
    args=['tests/phase2/review_fixture.py','55404',args[2],args[3],args[4]==='empty'?'empty':'growth_seed'];
  }
  return execFileSync(file,args,options);
}}:originalRequire(name);
adapted._compile(source,original);
function assertContains(text){if(!source.includes(text))throw new Error('Existing browser test changed; review the adapter before running');}
