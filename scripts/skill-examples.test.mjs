import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const reference = name => new URL(`../skills/kompressr/references/sdk-${name}.md`, import.meta.url);
const blocks = (name, language) => [...readFileSync(reference(name), 'utf8')
  .matchAll(new RegExp('```' + language + '\\n([\\s\\S]*?)\\n```', 'g'))].map(match => match[1]);

// Execute the documented helpers and upload calls. The SDK stand-in records
// calls; these tests cover application recovery, not transport correctness.
function javascript(mode) {
  const [helper, caller, original] = blocks('js', 'js');
  const calls = [];
  let waitError;
  const files = {
    async uploadFile(_path, options) {
      calls.push(['upload', options.passthrough === true]);
      return { id: 42 };
    },
    async waitUntilReady(id) {
      calls.push(['wait', id]);
      if (waitError) throw waitError;
      return { cdn_url: 'https://cdn.example.com/fixture.png' };
    },
  };
  const upload = mode === 'original' ? original : caller.slice(0, caller.indexOf('\nconst url'));
  const context = {
    KompressrClient: function () { return files; },
    process: { env: { KOMPRESSR_API_KEY: 'fixture-key' } },
  };
  runInNewContext(helper.replace(/^import .*;\n/m, '').replace('export async', 'async') +
    `\nthis.finish = finishPublicUpload;
     this.accept = async path => { ${upload}; return accepted; };`, context);
  return { calls, finish: context.finish, accept: context.accept,
    failWait(error) { waitError = error; } };
}

for (const mode of ['optimized', 'original']) {
  test(`JS ${mode}: persistence precedes readiness`, async () => {
    const fixture = javascript(mode);
    const accepted = await fixture.accept('fixture.png');
    const url = await fixture.finish(accepted.id, async id => fixture.calls.push(['save', id]));
    assert.equal(url, 'https://cdn.example.com/fixture.png');
    assert.deepEqual(fixture.calls, [['upload', mode === 'original'], ['save', 42], ['wait', 42]]);
  });

  for (const cancelled of [false, true]) {
    test(`JS ${mode}: ${cancelled ? 'cancellation' : 'save failure'} retains caller ID and original error`, async () => {
      const fixture = javascript(mode);
      const accepted = await fixture.accept('fixture.png');
      const failure = cancelled ? new DOMException('Cancelled', 'AbortError') : new Error('Save failed');
      await assert.rejects(fixture.finish(accepted.id, async () => { throw failure; }), error => error === failure);
      assert.equal(accepted.id, 42);
      assert.deepEqual(fixture.calls, [['upload', mode === 'original']]);
      await fixture.finish(accepted.id, async id => fixture.calls.push(['save', id]));
      assert.deepEqual(fixture.calls, [['upload', mode === 'original'], ['save', 42], ['wait', 42]]);
    });
  }

  test(`JS ${mode}: readiness failure preserves receipt and does not upload again`, async () => {
    const fixture = javascript(mode);
    const accepted = await fixture.accept('fixture.png');
    const failure = new Error('Wait failed');
    fixture.failWait(failure);
    const save = async id => fixture.calls.push(['save', id]);
    await assert.rejects(fixture.finish(accepted.id, save), error => error === failure);
    assert.equal(accepted.id, 42);
    fixture.failWait(undefined);
    await fixture.finish(accepted.id, save);
    assert.deepEqual(fixture.calls, [['upload', mode === 'original'], ['save', 42], ['wait', 42], ['save', 42], ['wait', 42]]);
  });
}

test('Python examples preserve recovery and native cancellation in both upload modes', () => {
  const [helper, caller, original] = blocks('python', 'python');
  const source = `
import asyncio, json, os, sys, types
helper, caller, original = json.loads(sys.stdin.read())
os.environ['KOMPRESSR_API_KEY'] = 'fixture-key'
class Files:
    def __init__(self, **_):
        self.calls = []
        self.wait_error = None
    async def upload_file(self, path, **options):
        self.calls.append(('upload', options.get('passthrough') is True))
        return {'id': 42}
    async def wait_until_ready(self, asset_id):
        self.calls.append(('wait', asset_id))
        if self.wait_error is not None:
            raise self.wait_error
        return {'cdn_url': 'https://cdn.example.com/fixture.png'}
module = types.ModuleType('kompressr')
module.AsyncKompressrClient = Files
sys.modules['kompressr'] = module
async def check(mode, stage):
    scope = {}
    exec(helper, scope)
    files = scope['files']
    upload = original if mode else caller.split('\\nurl =')[0]
    exec('async def accept(path):\\n' + '\\n'.join('    '+line for line in upload.splitlines()) + '\\n    return accepted', scope)
    accepted = await scope['accept']('fixture.png')
    failure = asyncio.CancelledError('Cancelled') if stage == 'cancel' else RuntimeError('Synthetic failure')
    async def save(asset_id):
        if stage in ('save', 'cancel'):
            raise failure
        files.calls.append(('save', asset_id))
    if stage == 'wait':
        files.wait_error = failure
    try:
        url = await scope['finish_public_upload'](accepted['id'], save)
    except BaseException as error:
        assert stage != 'success' and error is failure
        assert accepted['id'] == 42
        if stage in ('save', 'cancel'):
            assert files.calls == [('upload', mode)]
        files.wait_error = None
        async def recovered_save(asset_id):
            files.calls.append(('save', asset_id))
        url = await scope['finish_public_upload'](accepted['id'], recovered_save)
    else:
        assert stage == 'success'
    assert url == 'https://cdn.example.com/fixture.png'
    expected = [('upload', mode), ('save', 42), ('wait', 42)]
    if stage == 'wait':
        expected += [('save', 42), ('wait', 42)]
    assert files.calls == expected, files.calls
async def main():
    for mode in (False, True):
        for stage in ('success', 'save', 'cancel', 'wait'):
            await check(mode, stage)
asyncio.run(main())
print('8 Python recovery scenarios passed')
`;
  const result = spawnSync(process.env.KOMPRESSR_PYTHON || 'python3', ['-c', source], {
    input: JSON.stringify([helper, caller, original]), encoding: 'utf8', timeout: 30_000,
  });
  assert.equal(result.error, undefined, result.error?.message);
  assert.equal(result.status, 0, result.stderr);
});
