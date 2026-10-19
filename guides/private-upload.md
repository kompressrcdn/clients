# Upload your first private file

This example uploads a file, waits for processing and prints a link you can open in your browser. The link expires after one hour; the file stays stored until you delete it.

You need Node.js 22 or later, an active Kompressr trial or paid plan and a project API key. For an ordinary backend upload, get the key from **Dashboard → Projects → API Keys**. For separate chatbot users, first [create a test user's scoped key](chatbot-integration.md#1-create-a-test-user). A scoped key needs `upload`, `status` and `private_url`, and must allow private uploads.

## 1. Set up a local folder

These commands use a terminal with `curl`. Keep this folder outside your application's repository:

```sh
mkdir kompressr-quickstart
cd kompressr-quickstart
npm init -y
npm install @kompressr/sdk@1.0.0
curl -fSLo private-upload.mjs https://raw.githubusercontent.com/kompressrcdn/clients/main/examples/private-upload.mjs
```

You can also [download the example](../examples/private-upload.mjs) and save it as `private-upload.mjs` in this folder. It uses only the published SDK and Node's built-in file utilities.

Create a file named `.env` in this folder and replace the placeholder with the **full** key:

```dotenv
KOMPRESSR_API_KEY=PASTE_YOUR_KEY_HERE
```

Keep `.env` private and out of Git. On macOS/Linux, restrict access with `chmod 600 .env`. The key goes in this file, never in chat. A project ID is only needed for listing uploads, so this example does not require one.

## 2. Upload and open the result

Copy a small, disposable PNG into the folder as `sample.png`, then run:

```sh
node --env-file=.env private-upload.mjs ./sample.png
```

Expected output looks like:

```text
Accepted asset 42.
Saved kompressr-upload-42.receipt.json.
Ready. Private link expires at <timestamp>:
<your signed HTTPS URL>
```

Open the final URL to verify delivery. The receipt contains the asset ID and API origin, with no key or signed URL. The example deliberately prints the private URL for you to open locally; do not run it in shared CI logs. Anyone holding that link can use it until expiry.

## 3. Resume or refresh a link

If the wait times out, keep the asset ID. Processing continues. Replace `42` with your ID and use the same key/identity and API origin:

```sh
node --env-file=.env private-upload.mjs --resume 42
```

This checks the existing asset and generates a fresh link without uploading again. You can also use it after a link expires. The wait defaults to two minutes; set `KOMPRESSR_WAIT_TIMEOUT_MS` in `.env` if needed.

| Problem | What to do |
| --- | --- |
| Missing or invalid key | Check `.env` and use the full current key. |
| Permission denied | Check the key's scopes, private visibility allowance, identity status and plan. |
| Processing failed | Check the file format/size and processing status before trying a different file. |
| Upload outcome unknown | Inspect the identity's recent uploads in **Users & Agents** (or **Uploads** for project-owned files) before repeating the write. |
| Cannot save receipt | Keep the printed asset ID, fix local disk permissions/space and use `--resume`. |

When finished, delete the disposable file through its dashboard upload controls or an authorized key with `delete` permission. Revoking a key or expiring a link does not delete the file.

Next: [connect this flow to a chatbot](chatbot-integration.md#3-connect-it-to-your-chatbot) or read the [SDK reference](../sdk-js/API.md).
