import {createTikTokBroker} from './tiktok-broker.mjs';
let input='';
for await (const chunk of process.stdin){input+=chunk;if(input.length>32768)process.exit(1);if(input.includes('\n'))break;}
try { const config=JSON.parse(input.split('\n')[0]);input='';const {server}=await createTikTokBroker(config);server.listen(config.port,'127.0.0.1');process.stdin.resume();process.stdin.on('end',()=>server.close(()=>process.exit(0))); } catch { process.exit(1); }
