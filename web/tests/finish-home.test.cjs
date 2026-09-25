const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const read=(name)=>fs.readFileSync(path.resolve(__dirname,'../src/features/agent',name),'utf8');
test('latest v9 retains its real composer and exposes credit approval',()=>{
 const home=read('home-view.tsx');
 assert.ok(home.includes('<IdeaComposer'),'preserve the approved design');
 assert.ok(home.includes('<CreditLimitField'),'credit limits must be visible');
 assert.ok(home.includes('maxMilliCredits: creditMode'),'send the approved limit');
 assert.ok(home.includes("useHomeGeneration(params.get('run'))"),'reload should keep generated work');
});
test('quotes remain opt-in and unfinished input has an explicit recovery action',()=>{
 const home=read('home-view.tsx');
 assert.ok(home.includes('[own, setOwn] = useState(false)'));
 assert.ok(home.includes('Save brief'));assert.ok(home.includes('decodeBrief'));
 assert.ok(home.includes('createSubmissionGate'),'lock before content-selection mutations');
});
