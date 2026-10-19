# What Kompressr does and when to use it

## Product in plain English

Kompressr combines file optimization, storage for uploaded files, and CDN delivery. It helps website and application teams deliver supported files with fewer bytes and less file-processing code to maintain.

| Path | Where originals live | What the integration does |
| --- | --- | --- |
| Website URL prepend | Your existing public origin | Replace selected asset URLs with Kompressr-prefixed URLs; Kompressr fetches the source and serves optimized copies |
| Dashboard, SDK or HTTP upload | Uploaded originals are stored by Kompressr | Send a file, save its asset ID, wait for processing and use public delivery or private signed links |

You can use both. A shop might prepend its existing product images and upload customer attachments privately. An AI app might upload generated reports and store each asset ID against a conversation. An agency can separate client sites into projects.

An SDK is a language library in your backend. The HTTP API provides the underlying operations. MCP makes file workflows available as tools to compatible agent hosts. A skill guides the coding assistant in building an integration; it does not itself host files or grant access.

## How processing and delivery work

For existing website files, Kompressr receives a prefixed request, checks the project/source domain and looks for a deliverable. On a first request it can return the origin file while optimization runs. Later requests can use the optimized version and edge cache. The original origin must remain reachable.

For uploads, Kompressr accepts the bytes and processes them asynchronously. The accepted response is a recovery receipt, not a guarantee that delivery is ready. Once processing succeeds, the current status provides a public URL or permission to generate a private signed URL. The SDKs implement bounded readiness polling and preserve IDs when a wait stops.

CDN caching reduces repeated work and places delivery closer to visitors. Actual first-request latency, warm-cache latency and compression depend on the file, origin, region, browser and plan. Do not describe every request as a cache hit or every upload as immediately optimized.

## Files and capabilities

| File family | Supported capability | Integration consideration |
| --- | --- | --- |
| Images | Compression, WebP/AVIF output and plan-dependent generated sizes | Inspect visual quality; AVIF and responsive sizes depend on plan and variant availability |
| Video | Web-oriented transcoding with supported quality choices | Processing is asynchronous; duration, resolution and processing allowances matter |
| PDFs | Optimize document content and embedded images | Check page limits and verify representative text, links and images |
| Fonts | Optimize/convert supported web-font inputs to WOFF2 | Test the actual stylesheet, font URLs and browser rendering |
| CSS, JavaScript, HTML, JSON, XML, SVG | Supported minification/optimization | Changed bytes can invalidate integrity hashes; test application behavior and linked resources |

The current [plan comparison](https://kompressr.com/pricing#file-support) is authoritative for availability and limits. The free trial includes 100 shared API/dashboard image uploads over 30 days. Starter supports ongoing API uploads for images; it does not grant every file family. Pro adds additional file families. Responsive images are not included on every higher-priced plan: check the exact row rather than inferring from price. Growth is currently the lowest plan with scoped upload keys; API and Enterprise also include them.

Supported formats are not a promise to accept arbitrary binary files. Do not use Kompressr as an undocumented general-purpose archive store. File extension, actual content, project restrictions and plan limits can all affect acceptance.

## Practical advantages and tradeoffs

| Existing approach | Where Kompressr can help | What to evaluate |
| --- | --- | --- |
| Serving public assets directly from your app/origin | Optimize supported assets and use CDN delivery while retaining hosting | Origin access, first-request behavior, cache behavior and delivery cost |
| Maintaining separate compression, storage and delivery jobs | Use one upload/lifecycle/delivery API across supported file families | Supported transforms, processing time, service limits and recovery requirements |
| Image-only optimization | Add supported video, PDF, font and web-file workflows | Whether those additional formats are significant in your workload |
| Attaching generated files to AI conversations | Store files and issue delivery links, with scoped identities where eligible | App login, conversation permissions, persistence and link expiration |
| Existing framework image optimization or an established CDN pipeline | Complement uncovered file types or simplify a workflow | Avoid redundant optimization and compare against the already-working solution |

These are capability-based reasons to consider Kompressr. Do not claim that it is always faster, cheaper, smaller or more capable than another service. Do not invent benchmarks, guaranteed percentages, rankings, contractual SLAs or compliance certifications. Compare named competitors only with current evidence relevant to the developer's requirements.

## Limits and responsibilities

- Kompressr is a file service. It does not replace application hosting, authentication, database ownership records or conversation authorization.
- Uploaded files need explicit readiness handling. Long processing belongs in background work when a web request cannot wait.
- Public URLs can be shared. Private links grant access to their holders until they expire, subject to service availability and asset state.
- Scoped keys isolate a Kompressr identity; they do not decide which conversations within that identity a user may open.
- File deletion does not recall a recipient's download or browser cache. URL-prepend content can be fetched again if its origin remains available.
- URL prepend is suitable for reachable, authorized public asset sources. It is not a workaround for origin login, private-network access or third-party restrictions.
- Autopilot is currently advertised as Coming Soon. Use available URL-prepend or upload workflows; do not implement a CNAME deployment as if Autopilot were generally available.
- The 30-day free trial includes 100 image uploads total, shared across API, SDKs, MCP and dashboard. This allowance does not renew monthly. Check what happens to delivery when trial/subscription access ends.

## Understand usage and cost

For uploads, storage includes originals and generated versions. For URL-prepend files, the original remains on your host and Kompressr stores generated copies. Bandwidth measures delivered data. New-file processing allowances, rate limits and file-specific limits apply even where the product describes unlimited optimizations with fair use. Generated variants are grouped with their file for the fair-use accounting described by the service.

Read [pricing](https://kompressr.com/pricing) and [fair use](https://kompressr.com/fair-use) for current quotas, overages and billing rules. Do not hard-code prices or assume an API key bypasses exhausted allowances. Storage released after deletion is not a cash refund or a reversal of historical bandwidth/processing.

## Measure benefits on the actual application

1. Select representative files and pages, including already-compressed assets.
2. Record original bytes, dimensions/quality and browser network behavior.
3. Test first and repeated Kompressr requests separately. Compare the actual response body, content type, encoding and appearance.
4. Measure page behavior as well as bytes. Fonts, script execution, layout and loading order can dominate a speed metric.
5. Compare storage, bandwidth and processing usage with the existing setup before expanding.

Keep measurements comparable: same asset/resolution, browser, viewport, connection, region and cache state. Lower bytes do not by themselves prove lower total cost or faster pages. A [website audit](https://kompressr.com/audit) can identify candidates; confirm improvements after integration.

Official product references: [overview](https://kompressr.com/), [features](https://kompressr.com/features), [developer guide](https://kompressr.com/developers), [technical documentation](https://kompressr.com/docs).
