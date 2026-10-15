import { afterEach, expect, it, vi } from 'vitest';
import { createServer, type RequestListener } from 'node:http';
import { readFile, access } from 'node:fs/promises';
import { downloadForUpload, isPublicAddress } from '../download.js';
const closers: Array<() => Promise<void>>=[];
afterEach(async()=>{vi.unstubAllEnvs();await Promise.all(closers.splice(0).map(fn=>fn()));});
async function endpoint(handler:RequestListener){
  const server=createServer(handler);await new Promise<void>((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  closers.push(()=>new Promise(resolve=>{server.closeAllConnections();server.close(()=>resolve());}));
  const address=server.address();if(!address||typeof address==='string')throw new Error('No address');return `http://127.0.0.1:${address.port}`;
}
it('rejects private/mapped/documentation source addresses by default',async()=>{
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS','');
  for(const address of ['127.0.0.1','169.254.169.254','10.0.0.1','192.168.1.1','100.64.0.1','::1','::ffff:127.0.0.1','2001:db8::1'])expect(isPublicAddress(address)).toBe(false);
  await expect(downloadForUpload('http://127.0.0.1/private.png')).rejects.toMatchObject({code:'REMOTE_SOURCE_REJECTED'});
});
it('streams an explicitly trusted local source and deletes its restricted temporary file',async()=>{
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS','127.0.0.1');
  const origin=await endpoint((_request,response)=>{response.end('fixture');});
  const download=await downloadForUpload(`${origin}/output.png`);expect(await readFile(download.path,'utf8')).toBe('fixture');
  await download.cleanup();await expect(access(download.path)).rejects.toThrow();
});
it('rechecks redirect targets and rejects oversized content before buffering it',async()=>{
  vi.stubEnv('KOMPRESSR_REMOTE_ALLOWED_HOSTS','127.0.0.1');
  const origin=await endpoint((request,response)=>{
    if(request.url==='/redirect'){response.writeHead(302,{Location:'http://169.254.169.254/latest/meta-data'});response.end();}
    else{response.writeHead(200,{'Content-Length':String(2*1024*1024*1024+1)});response.end();}
  });
  await expect(downloadForUpload(`${origin}/redirect`)).rejects.toMatchObject({code:'REMOTE_SOURCE_REJECTED'});
  await expect(downloadForUpload(`${origin}/huge.mp4`)).rejects.toMatchObject({code:'REMOTE_SOURCE_REJECTED'});
});
