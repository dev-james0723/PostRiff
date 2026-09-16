import {createInterface} from 'node:readline';
import {createYouTubeBroker} from './youtube-broker.mjs';
process.umask(0o077);const lines=createInterface({input:process.stdin});let server,started=false;
lines.on('line',async line=>{if(started)return;started=true;try{const config=JSON.parse(line);({server}=await createYouTubeBroker(config));server.listen(config.port,'127.0.0.1');}catch{process.exit(1);}});
lines.on('close',()=>{server?.close();process.exit(0);});process.on('SIGTERM',()=>{server?.close();process.exit(0);});process.on('uncaughtException',()=>process.exit(1));process.on('unhandledRejection',()=>process.exit(1));
