import {KompressrClient} from '../dist/esm/index.js';
// This isolates allocations before sending a body; it is not a network benchmark.
if (!global.gc) throw new Error('Run with node --expose-gc scripts/verify-bytes-memory.mjs');
const size=64*1024*1024;
const input=Buffer.alloc(size,1);
global.gc?.();
const before=process.memoryUsage();
let captured;
const client=new KompressrClient({apiKey:'fixture',fetch:async(_url,init)=>{
  const after=process.memoryUsage();
  captured={runtime:process.version,inputMiB:size/1024/1024,arrayBuffersIncreaseMiB:(after.arrayBuffers-before.arrayBuffers)/1024/1024,rssIncreaseMiB:(after.rss-before.rss)/1024/1024,fileBytes:init.body.get('file').size};
  return Response.json({success:true,data:{asset_id:42,status:'pending',visibility:'public',deletion_status:'active',original_name:'generated.bin',original_size:size,asset_type:'text'}});
}});
await client.uploadBytes(input,'generated.bin');
console.log(JSON.stringify(captured));
