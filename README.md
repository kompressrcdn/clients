# Kompressr clients

Official libraries and agent tools for storing, optimizing and delivering files with [Kompressr](https://kompressr.com).

| Package | Use | Documentation |
| --- | --- | --- |
| `@kompressr/sdk` | JavaScript and TypeScript applications on Node.js | [Quick start](sdk-js/README.md), [API reference](sdk-js/API.md), [examples](sdk-js/examples) |
| `@kompressr/mcp-server` | MCP clients and AI agents | [Setup and tools](mcp-server/README.md) |

Current release candidates: SDK **1.0.0**, MCP **2.0.0**. Registry installation requires those versions to be published. Each package has its own version and changelog. Node.js 22.12+ and 24 are supported.

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
const accepted = await files.uploadFile('./image.png');
// Save accepted.id in your application before waiting, so a timeout does not lose the upload.
const ready = await files.waitUntilReady(accepted.id);
console.log(ready.cdn_url);
```

An accepted upload can still be processing. Save its ID and wait for readiness before sharing a delivery URL. See the [SDK guide](sdk-js/README.md) for private files, deletion, errors and scoped keys. Keep project/master credentials on trusted backends.

## Connect an agent

Configure your MCP client to run `npx -y @kompressr/mcp-server@2.0.0` with a Kompressr key. See the [MCP configuration example](mcp-server/README.md#setup), available tools and permission requirements. MCP uses the JS SDK for file operations; applications can use the SDK directly.

## Develop from source

```sh
git clone https://github.com/kompressrcdn/clients.git
cd clients
npm --prefix sdk-js ci --ignore-scripts
node scripts/verify.mjs
```

Verification builds/tests both packages, checks public content and the shared contract, and exercises installed packages using local HTTP fixtures. It requires no live account or service checkout. See [CONTRIBUTING.md](CONTRIBUTING.md), [publishing instructions](PUBLISHING.md) and the [public contract](contracts/README.md).

Report bugs through [GitHub issues](https://github.com/kompressrcdn/clients/issues). Follow [SECURITY.md](SECURITY.md) for private security reports. Packages are [MIT licensed](LICENSE).
