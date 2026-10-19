# Add private files to your chatbot

Your company owns one Kompressr **Platform/AI project** for each environment. Each chat user gets a Kompressr identity and a scoped key, which limits file access to that identity. Your backend uses the key on the user's behalf; the user does not need a Kompressr account or subscription.

The flow is: **signed-in user → your backend → Kompressr → private link in the chat**.

Use the SDK for a shared chatbot backend. Use MCP when an agent application needs to call the file tools itself.

## 1. Create a test user

Your company needs a plan with scoped keys: **Growth, API or Enterprise**. The free trial, Starter and Pro support ordinary API uploads but do not include per-user keys. Check the [plan comparison](https://kompressr.com/pricing#file-support).

1. In [Dashboard → Projects](https://kompressr.com/dashboard/projects), create or open a **Platform/AI** project for testing.
2. Open **Users & Agents**, choose **Add identity** and enter `demo-alice` as the **External identity ID**.
3. Expand that identity, enter a recognizable **Key name**, leave **Allow permanent asset deletion** unchecked and choose **Create key**. The default key allows public and private uploads, status, listing and private URLs. The example below always uploads privately; the production reference shows how to issue a private-only key through the SDK.
4. Save the full key securely when it is shown. You cannot retrieve its secret again later.

This manual setup demonstrates what your backend will automate in production. The project's **API Keys** page supplies the master key for that automation; it has broader access and stays on your trusted backend.

## 2. Get your first working link

Follow [Upload your first private file](private-upload.md), placing **Alice's scoped key** in `KOMPRESSR_API_KEY`. The example is runnable as supplied: no authentication service, database or job queue is needed for this local test.

You should see an accepted asset ID, a saved receipt and a fresh private URL after processing. Open the URL. Run the example's `--resume` command to get a new link for the same file.

For an isolation check, create `demo-bob` with its own key. Run `--resume` for Alice's asset using Bob's key: access must be denied. Alice's uploads must also be absent from Bob's listing. Sharing Alice's signed URL with Bob still allows delivery until it expires; signed URLs are access credentials themselves.

## 3. Connect it to your chatbot

Once the local test works, make your backend responsible for these steps:

| When | Your backend does |
| --- | --- |
| User first needs file access | Read their ID from your verified login session; create/find a Kompressr identity and issue one scoped key. Store it encrypted. |
| User attaches or generates a file | Load that user's saved key, authorize the conversation and upload with `visibility: 'private'`. |
| Kompressr accepts the file | Save the asset ID with its owning user and conversation before waiting for processing. |
| File is ready | Recheck access, generate a private URL and return the URL and expiry to the chat UI. |
| User reopens a chat | Look up the saved asset ID, authorize access and generate a fresh link. |

The model receives tool results such as asset IDs and delivery links, never API keys. Your backend chooses the credential. User IDs supplied by the model or request body are not proof of identity.

Keys separate Kompressr identities. Your application still checks conversation membership: two conversations using the same identity can access that identity's files. Metadata such as `conversation_id` helps organize records but does not enforce permissions.

The [production integration reference](chatbot-production.md) gives SDK snippets for provisioning, private browser uploads, persistence, key rotation and recovery. Those snippets mark the application services you must implement; the local upload example above is complete.

## Prefer MCP for an agent application?

Follow [Install in Claude Desktop](../smithery/README.md#install-in-a-desktop-client) and configure the same scoped key. For another host, use the [local stdio configuration](chatbot-production.md#5-use-mcp-when-the-agent-host-needs-it).

MCP loads one credential per process. Different users need separate processes and filesystem isolation. For a shared chatbot backend, selecting a user-bound SDK client per request is usually simpler.

Before launch, run the [two-user verification checklist](chatbot-production.md#verify-your-integration) with your real login, storage and chat UI. Delete the disposable test assets when finished; removing a key does not remove its files.
