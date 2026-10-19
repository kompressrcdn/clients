---
name: kompressr
description: Explain, integrate and troubleshoot Kompressr file optimization, storage and CDN delivery. Use when a developer asks to connect a website or app to Kompressr using URL prepend, a language SDK, the HTTP Upload API, private links, scoped user keys or MCP. Includes product fit, project setup, framework integration, lifecycle recovery and verification.
license: MIT
metadata:
  author: Kompressr
  version: "1.0.0"
---

# Kompressr

Help the developer reach a working, verified integration in their existing application. Explain the product when asked; implement only the changes the user requests. Keep their framework, hosting and authentication choices unless a concrete compatibility issue requires a change.

Kompressr optimizes supported files and delivers them through a CDN. Existing website files can stay on their origin; applications can also upload files for Kompressr to store. SDKs and the HTTP API manage uploads and files. MCP exposes file operations to an agent host. This skill supplies integration knowledge and works without MCP.

## Start with the developer's task

Inspect the application's language/runtime, framework, file sources, deployment target and existing file handling. Infer what is already clear; ask only for consequential missing information such as public versus private access, an unchosen integration route or required tenant isolation. Obtain credentials through the user's environment or secret store, never by asking them to paste secrets into chat.

| Developer needs | Starting route | Read |
| --- | --- | --- |
| Understand the product, benefits, limitations or plan fit | Explain capabilities against their workload | [Product guide](references/product.md) |
| Optimize public files already hosted on a website | URL prepend; retain the origin | [Website URLs](references/url-prepend.md) |
| Upload user files or generated output from an application | Official SDK matching the supported backend runtime | [SDK selection](references/sdks.md), then its language reference |
| Use a language/runtime with no compatible official SDK, or request raw HTTP | Native HTTP integration with explicit lifecycle/error handling | [HTTP API](references/http-api.md) and [custom integration blueprint](references/custom-integration.md) |
| Deliver restricted documents or isolate customers/agents | Private uploads, app authorization and scoped keys where eligible | [Security and tenancy](references/security.md) |
| Connect an agent host to file tools | Local stdio MCP server | [MCP](references/mcp.md) |
| Diagnose a failed integration or confirm it works | Trace the relevant stage and preserve recovery IDs | [Troubleshooting and verification](references/troubleshooting.md) |

The same application can combine website URL prepend and uploads. Follow a developer's explicit choice when it fits; do not require an SDK for simple website URLs or require MCP for an SDK integration.

## Integration workflow

1. **Establish fit.** Explain what will be optimized and where files will live. Read the product guide if capabilities or tradeoffs matter. Check current [pricing and file support](https://kompressr.com/pricing#file-support) before recommending a plan or promising a format/limit.
2. **Set up the right project.** Follow [account, project and credential setup](references/setup.md). Website domain verification and upload credentials serve different workflows. Use a Platform/AI project for scoped identities. Keep environments separate.
3. **Implement one complete path.** Read the route reference and, where relevant, [framework integration](references/frameworks.md). Adapt its code to the real application's authentication, persistence and upload types. Identify illustrative application hooks; do not leave undefined helpers in code presented as runnable.
4. **Handle the next request.** Follow [lifecycle and recovery](references/lifecycle.md): persist IDs, resume timeouts, refresh private links and retain per-item bulk results. A feature is incomplete if it only works on its first successful call.
5. **Verify.** Run relevant local checks and the route's verification steps. Live uploads consume plan resources; live deletions are permanent. Use the user's authorized test project/assets and report what was actually exercised. Do not create subscriptions, change DNS, publish or deploy merely because the skill describes those steps.
6. **Explain the result.** State changes, required configuration, where IDs/credentials are held, observed results and remaining checks. Distinguish code/fixture tests from authenticated service behavior.

## Rules that change implementation decisions

- **Upload acceptance is not readiness.** Save the numeric asset ID before waiting. A returned URL can precede a usable file. Use the current processed public URL, or wait for private signing readiness and mint a fresh link. A wait timeout does not justify reuploading.
- **Website first-request behavior differs.** URL prepend may deliver the origin file while optimization runs. Keep the origin accessible; inspect a subsequent request and measure the actual delivered result.
- **Keep master keys on trusted backends.** A project UUID in a public CDN URL is not a secret key. Browser/mobile code must never receive project authority. Scoped keys restrict identity/actions but do not replace application login or conversation authorization.
- **Permissions and plan limits remain enforced.** SDK construction and key selection cannot bypass them. Omitted scopes use defaults; explicitly empty scopes must be rejected. Deletion is an explicit additional scope.
- **Do not blindly retry writes.** A lost or malformed response may follow a successful upload/key issuance/deletion. Preserve the SDK's uncertainty and any safe asset ID; reconcile before replaying a mutation.
- **Private links are bearer credentials.** Authorize the viewer before signing. Do not log them, strip their query parameters, prepend another CDN prefix or assume revoking an API key recalls links already issued.
- **Deletion is permanent and asynchronous.** Acceptance is not completed file removal or instant cache invalidation. Inspect deletion status. Bulk HTTP success can include failed items.
- **Runtime support is specific.** Framework independence does not certify browsers, edge isolates, every language runtime or arbitrary framework upload wrappers. Use the matching language reference.
- **Use only supported public controls.** Do not invent resize/crop parameters, S3 APIs, upload-from-URL endpoints, webhooks or hosted MCP URLs. Check the current reference when a capability is not covered.

## References by task

- [Product, benefits, limits and measurement](references/product.md)
- [Account, projects, plans and credentials](references/setup.md)
- [URL prepend, variants and existing-site rollout](references/url-prepend.md)
- [SDK selection and operation map](references/sdks.md)
- SDK recipes: [JavaScript/TypeScript](references/sdk-js.md), [Python](references/sdk-python.md), [Go](references/sdk-go.md), [Java](references/sdk-java.md), [.NET](references/sdk-dotnet.md), [PHP](references/sdk-php.md), [Ruby](references/sdk-ruby.md)
- [Direct HTTP API, multipart and response shapes](references/http-api.md)
- [Build an integration when no compatible SDK exists](references/custom-integration.md)
- [Privacy, scoped keys and multi-user applications](references/security.md)
- [Processing, recovery, listing and deletion](references/lifecycle.md)
- [Frameworks, frontend boundaries and deployment](references/frameworks.md)
- [MCP installation and agent access](references/mcp.md)
- [Troubleshooting, migration and acceptance checks](references/troubleshooting.md)

Read only the references needed for the task. The public [SDK/API contract](https://github.com/kompressrcdn/clients/blob/main/contracts/kompressr-api.yaml), language API references and [integration guides](https://kompressr.com/integrations) supply deeper detail. Resolve discrepancies against the installed SDK version and current documented service behavior; do not silently invent a compatible method. Check current official sources for changing plan availability or framework configuration.
