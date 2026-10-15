import assert from 'node:assert/strict';
import {mkdtemp,open,rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as pause} from 'node:timers/promises';
import {KompressrClient} from '../dist/esm/index.js';
const directory=await mkdtemp(join(tmpdir(),'kompressr-large-'));
const file=join(directory,'large.mp4'); const size=256*1024*1024;
const handle=await open(file,'wx',0o600); await handle.truncate(size);await handle.close();
let received=0;
const server=createServer(async(request,response)=>{
  for await(const chunk of request){received+=chunk.length;await pause(1);}
  response.end(JSON.stringify({success:true,data:{asset_id:42,status:'pending',deletion_status:'active',visibility:'public',original_name:'large.mp4',original_size:size,asset_type:'video'}}));
});
try{
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const baseline=process.memoryUsage().rss;let peak=baseline;
 const monitor=setInterval(()=>{peak=Math.max(peak,process.memoryUsage().rss);},10);
 const start=performance.now();
 const client=new KompressrClient({apiKey:'fixture',apiBaseUrl:`http://127.0.0.1:${server.address().port}`});
 try{const accepted=await client.uploadFile(file,{quality:'1080p'});assert.equal(accepted.id,42);assert(received>size);}
 finally{clearInterval(monitor);}
 console.log(JSON.stringify({runtime:process.version,fileMiB:size/1024/1024,receivedBytes:received,elapsedSeconds:Math.round((performance.now()-start)/100)/10,combinedClientAndFixturePeakRssMiB:Math.round(peak/1024/1024),rssIncreaseMiB:Math.round((peak-baseline)/1024/1024)}));
}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true});}
