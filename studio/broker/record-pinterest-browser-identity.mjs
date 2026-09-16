import {privateStore} from './private-store.mjs';

const [root,username,...signals]=process.argv.slice(2);
const expected=['business_hub_name_and_handle','public_profile_name_and_handle'];
if(typeof root!=='string'||!root||username!=='jamesaucreates'||signals.length!==expected.length||expected.some((signal,index)=>signals[index]!==signal))process.exit(2);
const control=(await privateStore(root))('pinterest-control');
if(await control.get('identity')||await control.get('browser_identity'))process.exit(3);
await control.set('browser_identity',{username:'jamesaucreates',accountId:null,accountType:'BUSINESS_BROWSER_VERIFIED',scope:'controlled_browser_session',routeDriver:'controlled_browser',verifiedAt:new Date().toISOString(),expiresAt:null,identitySignals:expected,publishReady:false,publishing:false});
process.stdout.write(JSON.stringify({status:'connected_browser_identity',username:'jamesaucreates',routeDriver:'controlled_browser',publishReady:false,publishing:false})+'\n');
