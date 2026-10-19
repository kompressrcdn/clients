import { checkPackedFiles } from '../../scripts/public-content.mjs';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const directory = mkdtempSync(join(tmpdir(), 'kompressr-sdk-consumer-'));
let server;
try {
  const [packed] = JSON.parse(execFileSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', directory], { cwd: root, encoding: 'utf8' }));
  checkPackedFiles(packed.files, root, fileURLToPath(new URL('../../', import.meta.url)));
  assert(packed.files.some(x => x.path === 'LICENSE'));
  assert(!packed.files.some(x => /(?:^|\/)(?:tests|__tests__|node_modules|src)\//.test(x.path)));
  writeFileSync(join(directory, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  execFileSync('npm', ['install', join(directory, packed.filename), '--ignore-scripts', '--no-audit', '--no-fund'], { cwd: directory, stdio: 'pipe' });
  const imports = `import assert from 'node:assert/strict'; import {KompressrClient,KompressrError} from '@kompressr/sdk'; const client=new KompressrClient({apiKey:'fixture',apiBaseUrl:'https://management.example.test',uploadBaseUrl:'https://uploads.example.test'}); assert.equal(client.uploadBaseUrl,'https://uploads.example.test'); assert.equal(typeof client.platform.createUser,'function'); assert.equal(typeof KompressrError,'function');`;
  execFileSync(process.execPath, ['--input-type=module', '-e', imports], { cwd: directory, stdio: 'pipe' });
  execFileSync(process.execPath, ['--input-type=commonjs', '-e', `const assert=require('node:assert/strict'); const {KompressrClient}=require('@kompressr/sdk'); assert.equal(new KompressrClient({apiKey:'fixture'}).apiBaseUrl,'https://kompressr.com');`], { cwd: directory, stdio: 'pipe' });
  for (const example of ['usage.ts', 'next-route.ts']) copyFileSync(join(root, 'examples', example), join(directory, example));
  writeFileSync(join(directory, 'consumer.cts'), `import { KompressrClient, type UploadAsset } from '@kompressr/sdk'; const client=new KompressrClient({apiKey:'fixture'}); const result:Promise<UploadAsset>=client.waitUntilReady(42); void result; const unnamed:UploadAsset={id:42,status:'processed',deletion_status:'active',visibility:'public',original_size:3,asset_type:'image',kompressd_size:2,savings_percent:33,can_generate_private_url:false}; void unnamed;`);
  execFileSync(process.execPath, [join(root, 'node_modules/typescript/bin/tsc'), '--noEmit', '--strict', '--target', 'ES2022', '--module', 'Node16', '--moduleResolution', 'Node16', '--typeRoots', join(root, 'node_modules/@types'), 'usage.ts', 'next-route.ts', 'consumer.cts'], { cwd: directory, stdio: 'pipe' });
  let uploaded = false;
  server = createServer(async (request, response) => {
    try {
      if (request.method === 'POST' && request.url === '/api/upload') {
        for await (const chunk of request) { void chunk; }
        uploaded = true;
        response.end(JSON.stringify({success:true,data:{asset_id:42,status:'pending',deletion_status:'active',visibility:'public',original_name:'fixture.png',original_size:3,asset_type:'image'}}));
      } else if (request.url === '/api/upload/42/status') {
        response.end(JSON.stringify({success:true,data:{id:42,status:'processed',deletion_status:'active',visibility:'public',original_name:'fixture.png',original_size:3,asset_type:'image',kompressd_size:2,savings_percent:33,can_generate_private_url:false,cdn_url:'https://cdn.example/ready.webp'}}));
      } else { response.writeHead(404); response.end('{}'); }
    } catch { response.writeHead(500); response.end('{}'); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  writeFileSync(join(directory,'fixture.png'),'abc');
  const receipt = join(directory, 'receipt.json');
  const child = spawn(process.execPath, [join(directory,'node_modules/@kompressr/sdk/examples/public-upload.mjs'),join(directory,'fixture.png')], {cwd:directory,env:{...process.env,KOMPRESSR_API_KEY:'fixture',KOMPRESSR_API_URL:origin,KOMPRESSR_UPLOAD_BASE_URL:origin,KOMPRESSR_RECEIPT_PATH:receipt},stdio:['ignore','pipe','pipe']});
  let output = ''; child.stdout.on('data', chunk => { output += chunk; }); child.stderr.on('data', chunk => { output += chunk; });
  const code = await new Promise((resolve, reject) => { child.once('error',reject); child.once('exit',resolve); });
  assert.equal(code,0,output); assert(uploaded); assert.equal(JSON.parse(readFileSync(receipt,'utf8')).asset_id,42); assert(output.includes('https://cdn.example/ready.webp'));
  const deadlineCheck = join(directory, 'deadlines.mjs');
  copyFileSync(join(root, 'scripts/verify-deadlines.mjs'), deadlineCheck);
  execFileSync(process.execPath, ['--expose-gc', deadlineCheck], { cwd: directory, stdio: 'inherit', timeout: 30_000 });
  console.log('Packed SDK verified: ESM, CommonJS, TypeScript declarations and executable upload receipt/readiness example.');
} finally {
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  rmSync(directory, {recursive:true,force:true});
}
