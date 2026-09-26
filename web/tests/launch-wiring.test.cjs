const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '../src');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
function policy() {
 const filename = path.join(root, 'features/agent/use-model.ts');
 const loaded = new Module(filename); loaded.paths = module.paths;
 loaded.require = (id) => id === './reasoning-map' ? {} : require(id);
 loaded._compile(ts.transpileModule(read('features/agent/use-model.ts'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, filename);
 return loaded.exports.resolveModelChoice;
}
const models = [{id:'codex:test', qualified:true, route:'codex'}, {id:'cloud/model', qualified:true, route:'managed',costClass:'paid'}, {id:'deterministic-preview',qualified:true,route:'fixture'}];
test('new users prefer an available cloud model without installing a CLI', () => {
 const resolve = policy(); assert.equal(typeof resolve, 'function');
 assert.equal(resolve(models, null), 'cloud/model');
});
test('an unavailable saved model never silently changes provider or billing', () => {
 const resolve = policy(); assert.equal(typeof resolve, 'function');
 assert.equal(resolve(models, 'missing/model'), 'missing/model');
 assert.equal(resolve(models, 'codex:test'), 'codex:test');
});
test('Auto follows a priced workspace default; an explicit pick is never replaced by it', () => {
 const resolve = policy();
 const offered = [...models, {id:'cloud/other', qualified:true, route:'managed', costClass:'paid', priced:true}, {id:'cloud/unpriced', qualified:true, route:'managed', costClass:'paid', priced:false}];
 assert.equal(resolve(offered, 'auto', {workspace:'cloud/other', deployment:'cloud/model'}), 'cloud/other');
 assert.equal(resolve(offered, null, {workspace:'cloud/unpriced', deployment:'cloud/model'}), 'cloud/model', 'an unpriced workspace default is not used');
 assert.equal(resolve(offered, 'codex:test', {workspace:'cloud/other', deployment:'cloud/model'}), 'codex:test');
});
test('Home mounts account folders and preserves destination IDs', () => {
 const home = read('features/agent/home-view.tsx'); assert.ok(/useDestinations/.test(home), "Home uses account destination hook"); assert.ok(/ChannelBloomDialog/.test(home), "Home mounts existing folder dialog"); assert.ok(/setTargets/.test(home), "Home sends account-level targets");
});
test('saved folders are available from account management',()=>{
 assert.ok(/ChannelFoldersSection/.test(read('features/channels/channels-view.tsx')));
 assert.ok(read('features/channels/channels-view.tsx').includes('folderView.includes(channel.id)'), 'preserve saved-folder filtering');
});
test('public quotation is opt-in and brand copy acknowledges reviewed AI proposals',()=>{
 assert.ok(/\[own, setOwn\] = useState\(false\)/.test(read('features/agent/home-view.tsx')));
 assert.equal(read('features/workspace/brand-view.tsx').includes('nothing here is inferred by a model'),false);
});

test('quick starts are secondary to the composer instead of an always-open catalogue',()=>{
 const home=read('features/agent/home-view.tsx'), disclosure=read('features/agent/home/home-nudges.tsx');
 assert.ok(home.includes('<QuickStartsDisclosure'));
 assert.ok(disclosure.includes('[open, setOpen] = useState(false)'));
 assert.ok(disclosure.includes('aria-expanded={open}') && disclosure.includes('useMeasuredDisclosure<HTMLDivElement>(open)'));
});

test('campaign schedule and suggestion snooze expose existing backend controls',()=>{
 // Weekly scheduling moved from Home's planner to the Automation builder: weekday toggles, a time and a zone.
 const builder=read('features/automations/automation-builder.tsx');
 assert.ok(builder.includes('aria-pressed={on}') && builder.includes('aria-label={day}'));
 assert.ok(builder.includes("id='automation-time' type='time'"));
 assert.ok(builder.includes("id='automation-zone'"));
 const planner=read('features/agent/raffi-planner.tsx');
 assert.ok(planner.includes('raffi_suggestion_snooze'));
});
