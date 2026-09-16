import fs from 'node:fs/promises';
import path from 'node:path';
import {constants} from 'node:fs';
import {createHash,randomBytes,createCipheriv,createDecipheriv} from 'node:crypto';

async function noSymlinks(target){
  const resolved=path.resolve(target);
  for(let p=resolved;;p=path.dirname(p)){
    try{if((await fs.lstat(p)).isSymbolicLink())throw new Error('unsafe_private_path');}
    catch(error){if(error.code!=='ENOENT')throw error;}
    if(path.dirname(p)===p)break;
  }
  return resolved;
}

export async function privateStore(root){
  root=await noSymlinks(root);
  await fs.mkdir(root,{recursive:true,mode:0o700});await fs.chmod(root,0o700);
  const keyPath=path.join(root,'broker.key');
  try{await fs.writeFile(keyPath,randomBytes(32),{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST')throw e;}
  const keyHandle=await fs.open(await noSymlinks(keyPath),constants.O_RDONLY|constants.O_NOFOLLOW);
  let key;
  try{const s=await keyHandle.stat();if(!s.isFile()||s.size!==32||(s.mode&0o077)||s.nlink!==1)throw new Error('unsafe_private_key');key=await keyHandle.readFile();}finally{await keyHandle.close();}
  const file=(bucket,id)=>path.join(root,createHash('sha256').update(bucket+'\0'+id).digest('hex')+'.vault');
  return bucket=>({
    async set(id,value){
      const dest=file(bucket,id);await noSymlinks(dest);
      const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,iv);
      cipher.setAAD(Buffer.from(bucket+'\0'+id));
      const encrypted=Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()]);
      const payload=Buffer.concat([iv,cipher.getAuthTag(),encrypted]);
      if(payload.length>1024*1024)throw new Error('private_record_too_large');
      const tmp=dest+'.'+randomBytes(10).toString('hex')+'.tmp';
      try{await fs.writeFile(tmp,payload,{flag:'wx',mode:0o600});await noSymlinks(dest);await fs.rename(tmp,dest);}finally{await fs.rm(tmp,{force:true});}
    },
    async get(id){
      let h;
      try{h=await fs.open(await noSymlinks(file(bucket,id)),constants.O_RDONLY|constants.O_NOFOLLOW);}
      catch(e){if(e.code==='ENOENT')return undefined;throw e;}
      let bytes;try{const s=await h.stat();if(!s.isFile()||(s.mode&0o077)||s.nlink!==1||s.size>1024*1024||s.size<28)throw new Error('unsafe_private_record');bytes=await h.readFile();}finally{await h.close();}
      const decipher=createDecipheriv('aes-256-gcm',key,bytes.subarray(0,12));
      decipher.setAAD(Buffer.from(bucket+'\0'+id));decipher.setAuthTag(bytes.subarray(12,28));
      return JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)),decipher.final()]).toString('utf8'));
    },
    async del(id){await fs.rm(await noSymlinks(file(bucket,id)),{force:true});},
  });
}
