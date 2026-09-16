import {createInstagramBroker} from './instagram-broker.mjs';

let raw='';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { raw += chunk; });
process.stdin.on('end', async () => {
  try {
    const config=JSON.parse(raw);
    const broker=await createInstagramBroker(config);
    broker.server.listen(config.port,'127.0.0.1');
    const close=()=>broker.server.close(()=>process.exit(0));
    process.once('SIGTERM',close);process.once('SIGINT',close);
  } catch { process.exit(1); }
});
