import { checkPackedFiles } from '../../scripts/public-content.mjs';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const sdk = resolve(process.argv[2] ?? fileURLToPath(new URL('../../sdk-js', import.meta.url)));
const directory = mkdtempSync(join(tmpdir(), 'kompressr-mcp-consumer-'));
const servers = [];
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const asset = {id:42,status:'processed',visibility:'public',deletion_status:'active',original_name:'fixture.png',original_size:3,asset_type:'image',kompressd_size:2,savings_percent:33,can_generate_private_url:false,cdn_url:'https://cdn.example/ready.webp'};
const state = {id:42,project_id:'660e8400-e29b-41d4-a716-446655440001',kind:1,source:'upload',processing_status:3,deletion_status:'deleting',storage_credited_mb:0};
async function endpoint(handler) {
  const server=createServer((request,response)=>{Promise.resolve(handler(request,response)).catch(()=>{response.writeHead(500);response.end('{}');});});
  servers.push(server);
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return `http://127.0.0.1:${server.address().port}`;
}
try {
  const pack = cwd => {
    // npm 10 mixes lifecycle messages with --json stdout unless separated.
    execFileSync('npm', ['run', 'build'], { cwd, stdio: 'inherit' });
    return JSON.parse(execFileSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', directory], { cwd, encoding: 'utf8' }))[0];
  };
  const sdkPack=pack(sdk),mcpPack=pack(root); assert.equal(sdkPack.version,manifest.dependencies['@kompressr/sdk']);
  const repositoryRoot=fileURLToPath(new URL('../../', import.meta.url));
  checkPackedFiles(sdkPack.files,sdk,repositoryRoot);
  checkPackedFiles(mcpPack.files,root,repositoryRoot);
  const lock=JSON.parse(readFileSync(join(root,'package-lock.json'),'utf8'));
  assert.equal(sdkPack.integrity,lock.packages['node_modules/@kompressr/sdk'].integrity,'Refresh the SDK artifact checksum with node scripts/update-sdk-integrity.mjs from the clients root.');
  for (const artifact of [sdkPack,mcpPack]) {
    assert(artifact.files.some(x=>x.path==='LICENSE'));
    assert(!artifact.files.some(x=>/(?:^|\/)(?:__tests__|tests|node_modules|src)\//.test(x.path)));
  }
  writeFileSync(join(directory,'package.json'),JSON.stringify({private:true,type:'module'}));
  execFileSync('npm',['install',join(directory,sdkPack.filename),join(directory,mcpPack.filename),'--ignore-scripts','--no-audit','--no-fund'],{cwd:directory,stdio:'pipe'});
  let uploads=0,polls=0,deletion=0;
  const uploadOrigin=await endpoint(async(request,response)=>{
    assert.equal(request.url,'/api/upload');assert.equal(request.headers.authorization,'Bearer fixture-artifact');
    const chunks=[];for await(const chunk of request)chunks.push(chunk);
    const form=await new Request('http://fixture',{method:'POST',headers:{'Content-Type':request.headers['content-type']},body:Buffer.concat(chunks)}).formData();
    assert.deepEqual([...form.keys()],['visibility','kmp-quality','file']);uploads++;
    response.end(JSON.stringify({success:true,data:{...asset,asset_id:42,id:undefined,status:'pending',cdn_url:'https://cdn.example/initial.webp'}}));
  });
  const apiOrigin=await endpoint(async(request,response)=>{
    assert.equal(request.headers.authorization,'Bearer fixture-artifact');
    if(request.url==='/api/upload/42/status'){polls++;response.end(JSON.stringify({success:true,data:asset}));}
    else if(request.url==='/api/assets/42'&&request.method==='DELETE'){deletion++;response.writeHead(202);response.end(JSON.stringify(state));}
    else if(request.url==='/api/assets/42')response.end(JSON.stringify({...state,deletion_status:'deleted',storage_credited_mb:1}));
    else{response.writeHead(404);response.end('{}');}
  });
  const file=join(directory,'fixture.png');writeFileSync(file,'abc');
  const consumer=`
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
const client=new Client({name:'packed-consumer',version:'1.0.0'});
const transport=new StdioClientTransport({command:process.execPath,args:[${JSON.stringify(join(directory,'node_modules/@kompressr/mcp-server/dist/index.js'))}],env:{...process.env,KOMPRESSR_API_KEY:'fixture-artifact',KOMPRESSR_PROJECT_ID:'660e8400-e29b-41d4-a716-446655440001',KOMPRESSR_API_URL:${JSON.stringify(apiOrigin)},KOMPRESSR_UPLOAD_BASE_URL:${JSON.stringify(uploadOrigin)}},stderr:'pipe'});
let stderr='';transport.stderr?.on('data',chunk=>{stderr+=chunk;});
try{
 await client.connect(transport);assert.equal(client.getServerVersion().version,${JSON.stringify(manifest.version)});
 const{tools}=await client.listTools();assert.equal(tools.length,10);assert.equal(tools.find(x=>x.name==='delete_asset').annotations.destructiveHint,true);
 const accepted=await client.callTool({name:'upload_asset',arguments:{file_path:${JSON.stringify(file)},visibility:'public',quality:'1080p'}});
 assert.equal(accepted.isError,undefined,JSON.stringify(accepted));assert.equal(accepted.structuredContent.asset_id,42);assert.equal(accepted.structuredContent.ready,false);
 const ready=await client.callTool({name:'wait_for_asset',arguments:{asset_id:42,timeout_ms:1000}});assert.equal(ready.structuredContent.cdn_url,'https://cdn.example/ready.webp');
 const deleted=await client.callTool({name:'delete_asset',arguments:{asset_id:42}});assert.equal(deleted.structuredContent.deletion_status,'deleting');
 const progress=await client.callTool({name:'get_asset_deletion_status',arguments:{asset_id:42}});assert.equal(progress.structuredContent.deletion_status,'deleted');
 assert(!stderr.includes('fixture-artifact'));
}finally{await client.close();}
`;
  const script=join(directory,'consumer.mjs');writeFileSync(script,consumer);
  const child=spawn(process.execPath,[script],{cwd:directory,stdio:['ignore','pipe','pipe']});
  let output='';child.stdout.on('data',chunk=>{output+=chunk;});child.stderr.on('data',chunk=>{output+=chunk;});
  const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});
  assert.equal(code,0,output);assert.equal(uploads,1);assert.equal(polls,1);assert.equal(deletion,1);
  console.log('Packed SDK/MCP verified in an isolated npm consumer: stdio handshake, schemas, upload/readiness and permanent deletion/progress over separate HTTP origins.');
  console.log(`SDK artifact integrity: ${sdkPack.integrity}`);
}finally{
  await Promise.all(servers.map(server=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);})));rmSync(directory,{recursive:true,force:true});
}
