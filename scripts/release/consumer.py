"""Install an exact public release into a fresh consumer and exercise its entry point."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
from release import ROOT, KEYS, STABLE, require, run, write_json, consumer_environment


def verify(key, version):
    require(key in KEYS and STABLE.fullmatch(version), 'Invalid consumer target')
    with tempfile.TemporaryDirectory(prefix='kompressr-public-consumer-') as temporary:
        work = Path(temporary)
        env = consumer_environment()
        env['HOME'] = str(work / 'home')
        Path(env['HOME']).mkdir()
        env.update(PYTHONNOUSERSITE='1', npm_config_cache=str(work / 'npm-cache'))
        def cmd(*args, **kwargs):
            return run(*map(str, args), cwd=work, env=env, **kwargs)
        if key in KEYS[:2]:
            name = '@kompressr/sdk' if key == 'sdk-js' else '@kompressr/mcp-server'
            write_json(work / 'package.json', {'private': True, 'type': 'module'})
            cmd('npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org', f'{name}@{version}')
            if key == 'sdk-js':
                cmd('node', '--input-type=module', '-e', "import {KompressrClient} from '@kompressr/sdk'; if(typeof KompressrClient !== 'function')throw Error('Missing ESM export')")
                cmd('node', '--input-type=commonjs', '-e', "if(typeof require('@kompressr/sdk').KompressrClient !== 'function')throw Error('Missing CJS export')")
            else:
                (work / 'consumer.mjs').write_text('''import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
const client = new Client({name:'public-consumer',version:'1.0.0'});
const transport = new StdioClientTransport({command:process.execPath,args:['node_modules/@kompressr/mcp-server/dist/index.js'],env:{PATH:process.env.PATH},stderr:'pipe'});
const timer = setTimeout(()=>{process.exit(1)},30000);
try { await client.connect(transport); assert.equal(client.getServerVersion().version, process.argv[2]);
const {tools} = await client.listTools(); assert(tools.some(tool=>tool.name==='upload_asset'));
} finally { clearTimeout(timer); await client.close(); }
''')
                cmd('node', 'consumer.mjs', version)
        elif key == 'python':
            cmd(sys.executable, '-m', 'venv', work / 'venv')
            python = work / 'venv/bin/python'
            cmd(python, '-m', 'pip', 'install', '--no-cache-dir', '--index-url', 'https://pypi.org/simple', f'kompressr-sdk=={version}', 'cryptography>=45,<51')
            cmd(python, '-c', f'import kompressr; assert kompressr.__version__ == {version!r}')
            shutil.copytree(ROOT / 'sdk-python/tests', work / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'sdk-python/examples', work / 'examples', ignore=shutil.ignore_patterns('__pycache__'))
            cmd(python, '-m', 'unittest', 'discover', '-s', 'tests')
        elif key == 'go':
            env.update(GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org', GOMODCACHE=str(work / 'modules'), GOWORK='off')
            cmd('go', 'mod', 'init', 'example.com/consumer')
            cmd('go', 'get', f'github.com/kompressrcdn/clients/sdk-go@v{version}')
            (work / 'main.go').write_text('package main\nimport("fmt"; sdk "github.com/kompressrcdn/clients/sdk-go")\nfunc main(){fmt.Print(sdk.Version)}\n')
            require(cmd('go', 'run', '.', capture=True).strip() == version, 'Go consumer version differs')
        elif key == 'java':
            shutil.copyfile(ROOT / 'sdk-java/scripts/consumer/pom.xml', work / 'pom.xml')
            (work / 'src/main/java').mkdir(parents=True)
            shutil.copyfile(ROOT / 'sdk-java/scripts/consumer/InstalledConsumer.java', work / 'src/main/java/InstalledConsumer.java')
            cmd('mvn', '-B', f'-Dmaven.repo.local={work / "m2"}', f'-Dkompressr.version={version}', '-Daether.remoteRepositoryFilter.prefixes=false', 'package', 'dependency:build-classpath', '-Dmdep.outputFile=classpath.txt')
            cmd('java', '-Xmx64m', '-cp', str(work / 'target/classes') + ':' + (work / 'classpath.txt').read_text().strip(), 'InstalledConsumer')
        elif key == 'dotnet':
            (work / 'Consumer.csproj').write_text(f'''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="*.cs"/><PackageReference Include="Kompressr.Sdk" Version="{version}"/><None Include="fixtures/file-lifecycle.json" CopyToOutputDirectory="PreserveNewest"/></ItemGroup></Project>''')
            for source in (ROOT / 'sdk-dotnet/tests/Kompressr.Sdk.Tests').glob('*.cs'):
                shutil.copyfile(source, work / source.name)
            shutil.copytree(ROOT / 'sdk-dotnet/tests/Kompressr.Sdk.Tests/fixtures', work / 'fixtures')
            cmd('dotnet', 'restore', '--source', 'https://api.nuget.org/v3/index.json', '--packages', work / 'packages', '--no-cache')
            cmd('dotnet', 'run', '--configuration', 'Release', '--no-restore')
        elif key == 'php':
            env['COMPOSER_CACHE_DIR'] = str(work / 'composer-cache')
            write_json(work / 'composer.json', {'name': 'example/consumer', 'require': {'kompressr/sdk': version}})
            cmd('composer', 'install', '--no-interaction', '--no-scripts', '--no-plugins', '--prefer-dist')
            env['KOMPRESSR_TEST_AUTOLOAD'] = str(work / 'vendor/autoload.php')
            cmd('php', '-d', 'error_reporting=E_ALL', work / 'vendor/kompressr/sdk/tests/run.php')
        else:
            env.update(GEM_HOME=str(work / 'gems'), GEM_PATH=str(work / 'gems'))
            cmd('gem', 'install', 'kompressr-sdk', '--version', version, '--no-document', '--clear-sources', '--source', 'https://rubygems.org')
            cmd('ruby', '-e', f'require "kompressr"; abort "Version mismatch" unless Kompressr::VERSION == "{version}"')
        print(f'Public {key} {version} installed and checked in an isolated consumer.')


if __name__ == '__main__':
    verify(*sys.argv[1:])
