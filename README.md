# Kompressr clients

Official libraries and agent tools for storing, optimizing and delivering files with [Kompressr](https://kompressr.com).

| Language or tool | Package | Minimum runtime | Get started |
| --- | --- | --- | --- |
| JavaScript / TypeScript | npm: `@kompressr/sdk` | Node.js 22 | [Node.js SDK](sdk-js/README.md) |
| Python | PyPI: `kompressr-sdk` | Python 3.11 | [Python SDK](sdk-python/README.md) |
| Go | `github.com/kompressrcdn/clients/sdk-go` | Go 1.24 | [Go SDK](sdk-go/README.md) |
| Java | Maven Central: `com.kompressr:kompressr-sdk` | Java 17 | [Java SDK](sdk-java/README.md) |
| C# / .NET | NuGet: `Kompressr.Sdk` | .NET 8 | [.NET SDK](sdk-dotnet/README.md) |
| PHP | Packagist: `kompressr/sdk` | 64-bit PHP 8.1 | [PHP SDK](sdk-php/README.md) |
| Ruby | RubyGems: `kompressr-sdk` | MRI Ruby 3.2 | [Ruby SDK](sdk-ruby/README.md) |
| MCP | npm: `@kompressr/mcp-server` | Node.js 22 | [Agent setup](mcp-server/README.md), [desktop extension](smithery/README.md) |

Each package has its own version and changelog. The SDKs share the same [file, permission and recovery behavior](contracts/sdk-behavior.md), expressed through language-native APIs. MCP uses the JavaScript SDK.

## Framework compatibility

These are server-side libraries with no application-framework dependency. Use them from applications, command-line scripts or background jobs that meet the package's runtime and dependency requirements.

For Python, use `KompressrClient` in synchronous Django views or worker tasks, and `AsyncKompressrClient` in FastAPI `async def` handlers or Django async views. The sync client deliberately rejects use inside a running asyncio loop. Ruby's synchronous client works in plain Ruby and Rails controllers/jobs; it does not provide a separate async API. Keep project and customer keys on trusted servers, and choose the credential for the authenticated user before making a request.

Framework upload wrappers may need adapting: pass supported bytes or a regular local file to the SDK. For example, Django's `UploadedFile` and FastAPI's `UploadFile` are not directly accepted by the Python upload methods. Use bytes for small uploads, or save large uploads to a regular file and stream that file using the package's documented input type.

Framework independence does not imply browser support, every language version or every hosting environment. Check each package's runtime, TLS/network, filesystem and concurrency requirements. A framework-specific plugin is not required.

## Choose your starting point

- **Upload from your Node.js application:** [run your first private upload](guides/private-upload.md), including setup, expected output and timeout recovery.
- **Use Claude Desktop or another agent:** [install the MCP extension](smithery/README.md) and try the sample upload prompt.
- **Build a chatbot with separate users:** [test scoped access, then integrate it](guides/chatbot-integration.md).

## Integrate with an AI coding assistant

The [Kompressr skill](skills/kompressr/SKILL.md) helps your coding assistant choose and implement the right integration for your application. It covers product capabilities, all seven SDKs, custom HTTP integrations for other languages, website URL prepend, private files, scoped keys and troubleshooting. It works independently of the MCP server.

From your application directory, install it for your compatible coding assistant:

```sh
npx skills add kompressrcdn/clients --skill kompressr
```

The installer lets you choose an assistant. You can also copy the complete `skills/kompressr` folder into your assistant's documented skills directory. Keep its reference files together. See the [Agent Skills format](https://agentskills.io/specification) and [installer options](https://github.com/vercel-labs/skills).

Run `npx skills list` from the same application directory to confirm installation. Start a new assistant session there and ask it to use the Kompressr skill for your task.

Example requests: “Add private file uploads to my Django app,” “Use Kompressr for my existing website images,” or “Integrate Kompressr in Rust using the HTTP API.” The assistant adapts the guidance to your stack; you still supply your own account/project configuration and keep secrets in your application's secret store.

## Start with the SDK

1. [Create a Kompressr account](https://kompressr.com/signup) and select a plan with API upload access.
2. In [Dashboard → Projects](https://kompressr.com/dashboard/projects), open your project and choose **API Keys**. Store the key in your server's `KOMPRESSR_API_KEY` environment variable.
3. Install the SDK and upload from your backend:

```sh
npm install @kompressr/sdk
```

```js
import { KompressrClient } from '@kompressr/sdk';

const files = new KompressrClient({ apiKey: process.env.KOMPRESSR_API_KEY });
const accepted = await files.uploadFile('./image.png', { visibility: 'public' });
// Save accepted.id in your application before waiting, so a timeout does not lose the upload.
const ready = await files.waitUntilReady(accepted.id);
console.log(ready.cdn_url);
```

An accepted upload can still be processing. Save its ID and wait for readiness before sharing a delivery URL. See the [SDK guide](sdk-js/README.md) for private files, deletion, errors and scoped keys. Keep project/master credentials on trusted backends.

## Build a chatbot with separate user access

Follow the [chatbot integration guide](guides/chatbot-integration.md) to provision identities and scoped keys, bind tools to authenticated users, upload private attachments, wait for processing and refresh delivery links. Start with a runnable test, then follow the linked production reference for credential storage, conversation access and recovery.

Ordinary API uploads are included on paid plans, subject to file and usage limits. Per-user scoped keys require a Platform/AI project and a plan that includes them: currently Growth, API or Enterprise. Check the [plan comparison](https://kompressr.com/pricing#file-support).

## Connect an agent

Configure your MCP client to run `npx -y @kompressr/mcp-server@2.0.2` with a Kompressr key. See the [MCP configuration example](mcp-server/README.md#setup), available tools and permission requirements. MCP uses the JS SDK for file operations; applications can use the SDK directly. For Claude Desktop, follow the [desktop extension walkthrough](smithery/README.md).

## Develop from source

```sh
git clone https://github.com/kompressrcdn/clients.git
cd clients
npm --prefix sdk-js ci --ignore-scripts
node scripts/verify.mjs
```

This command verifies the JS SDK and MCP, checks public source content and the shared contract, and exercises their installed packages using local HTTP fixtures. For another language, use its native verifier or `node scripts/verify-all.mjs` with a language name after installing its development tools. See [CONTRIBUTING.md](CONTRIBUTING.md) for prerequisites and the all-package command, and the [public contract](contracts/README.md) for API behavior. Local verification requires no live account or service checkout.

Report bugs through [GitHub issues](https://github.com/kompressrcdn/clients/issues). Follow [SECURITY.md](SECURITY.md) for private security reports. Packages are [MIT licensed](LICENSE).
