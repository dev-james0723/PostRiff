import { NextRequest } from 'next/server';
import { request as connect } from 'node:http';
import { admitted, localBackend } from '../../../../../boundary.mjs';

async function forward(request: NextRequest, context: {params:Promise<{path:string[]}>}) {
  if (!admitted(request.headers.get('host'),process.env) || process.env.VERCEL || process.env.VERCEL_ENV) return new Response(null,{status:404});
  const {path} = await context.params;
  if (path.some(segment => !/^[a-zA-Z0-9_-]{1,160}$/.test(segment))) return new Response(null,{status:400});
  const body = request.method==='GET' ? undefined : await request.text();
  if (body && new TextEncoder().encode(body).length>32768) return new Response(null,{status:413});
  const headers = new Headers();
  for (const name of ['cookie','origin','content-type','authorization','x-csrf-token','x-control-exchange','idempotency-key']) {
    const value = request.headers.get(name);
    if (value) headers.set(name,value);
  }
  headers.set('host',new URL(process.env.RAFII_CONTROL_ORIGIN!).host);
  try {
    // Node fetch rewrites Host to the loopback destination. A bounded native HTTP request
    // preserves the already-admitted original host without weakening the API's host guard.
    const url=new URL(localBackend(process.env)+'/api/control/v2/'+path.join('/'));
    const upstream=await new Promise<{body:string;status:number;cookie?:string}>((resolve,reject)=>{
      const socket=connect(url,{method:request.method,headers:Object.fromEntries(headers),signal:AbortSignal.timeout(13000)},response=>{
        const chunks:Buffer[]=[];let size=0;
        response.on('data',(chunk:Buffer)=>{size+=chunk.length;if(size>524288){socket.destroy(new Error('Control response exceeded bound'));return;}chunks.push(chunk);});
        response.on('end',()=>resolve({body:Buffer.concat(chunks).toString('utf8'),status:response.statusCode||503,cookie:response.headers['set-cookie']?.[0]}));
        response.on('error',reject);
      });
      socket.on('error',reject);socket.end(body);
    });
    const result = new Headers({'Content-Type':'application/json','Cache-Control':'private, no-store'});
    const cookie = upstream.cookie;
    if (cookie) result.set('set-cookie',cookie);
    return new Response(upstream.body,{status:upstream.status,headers:result});
  } catch { return Response.json({code:'SOURCE_UNAVAILABLE',message:'Control source unavailable'},{status:503,headers:{'Cache-Control':'no-store'}}); }
}
export const GET=forward;
export const POST=forward;
