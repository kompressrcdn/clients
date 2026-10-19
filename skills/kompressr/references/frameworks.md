# Framework and deployment integration

Choose the SDK by backend language and supported runtime, then adapt it to the framework. Do not install a fictional Kompressr framework plugin when the official language client or URL configuration already meets the need.

## Application upload flow

```text
browser/mobile form → authenticated app endpoint → validated file
→ SDK or custom HTTP adapter → accepted ID saved in app record
→ bounded wait/background job → authorized delivery response
```

Authenticate and validate before selecting a credential. Enforce your app's size/type policy before buffering an entire request. Use regular local files or bounded bytes supported by the SDK. Keep temporary files alive until upload completes; move them to durable storage before handing work to a later process. Record the asset ID before polling so a job retry can resume.

Do not require a two-minute web request merely because the SDK's readiness default is two minutes. If platform/request budgets are shorter, return your own pending attachment/job identifier and update it from background work. App endpoints still enforce authorization on each subsequent status/download request.

## Stack guidance

| Stack | Upload integration | Website URL integration |
| --- | --- | --- |
| Next.js / Node web frameworks | Node.js 22+ server route/action/job using JS SDK; credentials stay out of client components | Inspect `assetPrefix` for framework static chunks; handle public images and image components separately |
| React/Vue/Svelte SPA | Frontend calls your authenticated backend; select SDK by that backend | Prefix selected assets or configure bundler asset base; verify generated/lazy-loaded paths |
| Django | Sync SDK in sync views/workers; async SDK in async views | Static URL/template helpers for a verified public asset origin |
| FastAPI | Async SDK inside async handlers; sync code only in suitable sync workers | Template/static-asset helpers where the app renders HTML; pure JSON APIs may leave asset references to the frontend |
| Go frameworks | Reusable Go client with request/job contexts | URL/template helpers or frontend build configuration |
| Spring/Java | Java client as an application service, closed on shutdown; calls block | Resource/template URL configuration or frontend build configuration |
| ASP.NET Core | Async .NET client in backend services, cancellation token as appropriate | Static asset/template configuration; browser-hosted Blazor calls backend for uploads |
| Laravel/Symfony | PHP SDK in controllers/services/queue jobs; calls block | Asset URL helpers/build configuration |
| Rails/Sinatra/Hanami | Ruby client in services/jobs; synchronous | Asset-host/template configuration for supported public assets |
| Other languages | Build a native HTTP adapter using the [blueprint](custom-integration.md) | URL prepend remains language-independent |

SDK references explain exact inputs. Framework `UploadedFile`, `UploadFile`, `MultipartFile`, `IFormFile` and similar wrappers are not interchangeable with each other or with the SDK's file input. Adapt them deliberately. For small files, enforce a bound before creating an in-memory byte input; for large files use supported streaming/local-file paths.

## Next.js details

The Node SDK belongs in a supported Node server runtime. Do not claim edge-runtime support or expose project credentials through `NEXT_PUBLIC_*`.

`assetPrefix` covers `/_next/static` assets. It does not automatically change files in `public/` or the dynamic `next/image` path. The Kompressr [Next.js guide](https://kompressr.com/integrations/next-js) shows separate treatment for static chunks and images. For an image already delivered through Kompressr, an explicit CDN `src` with `unoptimized` on that `Image` avoids an additional Next optimization pass; that alone does not generate responsive width variants. Preserve dimensions and alt text, and check current framework configuration requirements.

Do not rewrite API routes, server actions, page navigation or framework data requests through a static-file prefix. Rebuild after changing a prefix that is baked into generated assets and check a production preview.

## Existing websites, bundlers and CMSs

Use the [integration index](https://kompressr.com/integrations) for the actual framework/CMS version, then inspect emitted HTML, CSS and network requests. Confirm that lazy chunks, fonts and CSS-relative assets resolve to the intended source. An asset helper does not rewrite every hard-coded URL automatically.

Keep verified source domains available. Do not make broad DNS/CDN changes as a side effect of introducing a few prefixed URLs. Autopilot is currently Coming Soon; do not use it as a presumed fallback.

Byte transformations can invalidate SRI hashes or assumptions in an existing optimization pipeline. Check CORS for fonts/module scripts and make targeted CSP changes if required. Do not remove these protections silently. Test image rendering, JavaScript behavior and navigation as well as successful HTTP status codes.

## Hosting constraints

- Check your function/container's supported language version, outbound HTTPS, request timeout, body limits, temporary storage and memory budget.
- Long videos/PDF processing may outlive a request even when upload succeeds. Use durable IDs and resumable checks rather than extending every request indefinitely.
- A background job cannot depend on a request's deleted temporary file. Preserve bytes before enqueueing an upload job; after acceptance, enqueue only the saved asset ID for polling.
- Serverless ephemeral files are not durable recovery storage. Put IDs and state in your application database/job system.
- Custom HTTP adapters must obey the same authorization, error and lifecycle rules. Direct HTTP is not a way to make a project secret safe in browser code.

Inspect the framework's current official documentation before writing version-specific configuration. Use a small application-specific change and verify it in the built app; avoid installing a replacement architecture solely for this integration.

Framework references: [Next.js assetPrefix](https://nextjs.org/docs/app/api-reference/config/next-config-js/assetPrefix), [Next.js image options](https://nextjs.org/docs/app/api-reference/components/image#unoptimized), [Vite public base path](https://vite.dev/guide/build#public-base-path).
