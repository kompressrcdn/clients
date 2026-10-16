import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync,openAsBlob} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';

// Smithery CLI 1.2.0 forwards MCPB tool summaries without required input schemas.
// Submit the separately captured MCP server card through the publishing API.
const [artifact,qualifiedName,mode]=process.argv.slice(2);
if(!artifact||!qualifiedName||!/^[-a-z0-9]+\/[-a-z0-9]+$/.test(qualifiedName)||mode&&mode!=='--check') {
  throw new Error('Usage: node smithery/publish.mjs artifact.mcpb namespace/server [--check]');
}
const bundle=resolve(artifact);
const manifest=JSON.parse(execFileSync('unzip',['-p',bundle,'manifest.json'],{encoding:'utf8'}));
const payload=JSON.parse(readFileSync(new URL('./release-payload.json',import.meta.url),'utf8'));
assert.equal(payload.type,'stdio');assert.equal(payload.runtime,'node');
assert.equal(payload.serverCard.serverInfo.name,manifest.name);
assert.equal(payload.serverCard.serverInfo.version,manifest.version);
assert.deepEqual(payload.serverCard.tools.map(({name,description})=>({name,description})),manifest.tools);
assert(payload.serverCard.tools.every(tool=>tool.inputSchema?.type==='object'));
const sha256=createHash('sha256').update(readFileSync(bundle)).digest('hex');
console.log(`Validated ${manifest.name} ${manifest.version}; SHA-256 ${sha256}`);
if(mode==='--check')process.exit(0);

let token=process.env.SMITHERY_API_KEY;
if(!token){
  let output;
  try { output=execFileSync('npx',['--yes','smithery@1.2.0','auth','whoami','--full'],{encoding:'utf8',stdio:['ignore','pipe','pipe']}); }
  catch { throw new Error('Could not read the Smithery CLI login. Run npx smithery@1.2.0 auth login first.'); }
  token=output.match(/^SMITHERY_API_KEY=(.+)$/m)?.[1];
}
if(!token)throw new Error('Run npx smithery@1.2.0 auth login first.');
const serverPath=`/servers/${encodeURIComponent(qualifiedName)}`;
async function request(method,path,body,allowMissing=false){
  const headers={Authorization:`Bearer ${token}`};
  if(body&&!(body instanceof FormData)){headers['Content-Type']='application/json';body=JSON.stringify(body);}
  let response;
  try{response=await fetch(`https://api.smithery.ai${path}`,{method,headers,body,signal:AbortSignal.timeout(45000)});}
  catch{throw new Error(`Smithery request interrupted. Check https://smithery.ai/servers/${qualifiedName}/releases before retrying a publication.`);}
  if(response.status===404&&allowMissing)return null;
  const text=await response.text();
  if(!response.ok)throw new Error(`Smithery HTTP ${response.status}: ${text.replaceAll(token,'[redacted]')}`);
  return JSON.parse(text);
}
if(!await request('GET',serverPath,undefined,true))await request('PUT',serverPath,{});
const form=new FormData();
form.append('payload',JSON.stringify(payload));
form.append('bundle',await openAsBlob(bundle),`${manifest.name}-${manifest.version}.mcpb`);
const release=await request('PUT',`${serverPath}/releases`,form);
console.log(JSON.stringify({deploymentId:release.deploymentId,status:release.status,listing:`https://smithery.ai/servers/${qualifiedName}`},null,2));
await request('PATCH',serverPath,{displayName:manifest.display_name??manifest.name,description:manifest.long_description??manifest.description,homepage:manifest.homepage,repositoryUrl:manifest.repository?.url,license:manifest.license,unlisted:false});
console.log('Listing metadata updated. Download and verify the published artifact before announcing the release.');
