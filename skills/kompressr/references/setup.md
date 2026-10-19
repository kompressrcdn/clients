# Account, projects and credentials

## Choose the workflow

| Workload | Setup |
| --- | --- |
| Existing public website assets | Website project for the source domain; complete its dashboard domain verification |
| Application-owned uploads | Upload-capable project and a project key kept on your backend |
| Separate customers, tenants or agents | Platform/AI project, eligible scoped-key plan, identities under that project |
| Manual file upload | Dashboard Uploads; observe trial/plan restrictions |

Use separate projects for production and test environments. A multi-user application normally uses identities inside a project; it does not need a paid Kompressr account or separate project for every end user. Choose the isolation unit—person, tenant, workspace or agent—deliberately.

## First setup

1. [Create an account](https://kompressr.com/signup) or sign in. Select a plan that supports the required file types, API access and identity features.
2. Open [Dashboard → Projects](https://kompressr.com/dashboard/projects) and create/open the appropriate project.
3. For URL prepend, follow the exact DNS verification record shown by the project. Preserve unrelated DNS records. Wait until the dashboard recognizes ownership before testing. No API key belongs in a prefixed asset URL.
4. For backend uploads, open the project's **API Keys** page. Store the full `KEY_ID.SECRET` value when shown; the secret cannot be read back later. Use your deployment's secret manager or server-only environment configuration.
5. For scoped access, open **Users & Agents** or use the platform API to create an identity and issue a restricted key. See [security](security.md).

## Configuration values

| Value | Meaning | Where it belongs |
| --- | --- | --- |
| `KOMPRESSR_API_KEY` | Complete project or scoped secret supplied to SDK/MCP or HTTP bearer authentication | Trusted server/authorized isolated runtime secret store |
| `KOMPRESSR_PROJECT_ID` | Project UUID, needed for upload listing and website prefix | Backend configuration; website IDs may appear in public URLs |
| API management origin | `https://kompressr.com` | Normally use the SDK default |
| Upload-body origin | `https://uploads.kompressr.com` | Normally use the SDK default |
| Delivery origin | `https://cdn.kompressr.com` | URLs returned by the API or constructed for website prepend |

SDKs take explicit constructor options; an environment variable is not read automatically unless the example passes it. MCP reads its documented environment variables. Do not add public frontend environment prefixes to secrets. A frontend build can expose a value even if its source file was ignored by Git.

Use the package's endpoint option names if custom endpoints are required. A custom API origin defaults uploads to the same origin unless an upload origin is also supplied. Overrides are origins, not full API paths. Never send a real key to an untrusted endpoint to troubleshoot it.

## Plan selection

The 30-day free trial includes 100 image uploads shared across API, SDKs, MCP and dashboard, with no monthly renewal. Starter continues ordinary API image uploads after the trial; Growth is the minimum for per-user scoped upload keys. Pro supports additional file families. API and Enterprise also support scoped keys. File size, resolution, video/PDF limits, responsive images and quotas vary independently. Consult [current pricing](https://kompressr.com/pricing#file-support) for the actual combination before choosing a plan.

After email verification, an active free trial permits API image uploads within the shared 100-upload allowance. Possessing a key does not override plan, project or scope checks.

## What your application stores

- The numeric accepted asset ID against its authenticated owner and app record before waiting for processing.
- The Kompressr project-user UUID and key-record identifiers for scoped-key management; store the secret encrypted with access limited to the intended backend/runtime.
- Pending/ready/failed state and enough information to resume work after a process restart.

Store the asset ID as the durable reference. Private URLs expire and should be refreshed after authorization. A public URL does not replace the ID needed for lifecycle operations. Metadata supports reconciliation but does not establish ownership or idempotency.

Before testing a long file, confirm the application's request/body limits, proxy timeouts, temporary-file storage and worker budget as well as Kompressr's limits. See [frameworks](frameworks.md).
