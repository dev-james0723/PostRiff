import {createThreadsBroker} from './threads-broker.mjs';
let input='';
for await (const chunk of process.stdin){input+=chunk;if(input.length>32768)process.exit(1);if(input.includes('\n'))break;}
try{const config=JSON.parse(input.split('\n')[0]);input='';const broker=await createThreadsBroker(config);broker.server.listen(config.port,'127.0.0.1');let closing=false;const close=()=>{if(closing)return;closing=true;broker.server.closeAllConnections?.();broker.server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),1000).unref();};process.stdin.resume();process.stdin.once('end',close);process.stdin.once('close',close);process.once('SIGTERM',close);process.once('SIGINT',close);}catch{process.exit(1);}
