# Kompressr Ruby SDK

Upload, optimize and deliver files from Ruby applications. The SDK works independently of Rails, Sinatra, Hanami or any other framework. It provides a synchronous client for request handlers, background jobs and command-line applications.

Requires MRI Ruby 3.2 or later with OpenSSL and a trusted CA store. Other Ruby implementations and asynchronous fiber schedulers are not supported.

Bundler installs the required standard-library gems when your Ruby version bundles older ones. Installing the JSON or OpenSSL gems from source requires Ruby development headers and a C compiler; OpenSSL also requires its development libraries.

## Install

Add to your application's Gemfile:

```ruby
gem 'kompressr-sdk', '~> 0.1.0', require: 'kompressr'
```

Run `bundle install`. For a standalone script, install with `gem install kompressr-sdk` and load it with `require 'kompressr'`. The gem declares its Ruby standard-gem dependencies and has no framework dependency.

## Upload your first file

Create a project in the [Kompressr dashboard](https://kompressr.com/dashboard/projects), select a plan with API upload access, and store its API key in your backend's `KOMPRESSR_API_KEY` environment variable. See [pricing](https://kompressr.com/pricing#file-support) for plan features and limits.

```ruby
require 'kompressr'

files = Kompressr::Client.new(api_key: ENV.fetch('KOMPRESSR_API_KEY'))
accepted = files.upload_file('image.png', visibility: 'public')
asset_id = accepted.fetch('id')
# Persist asset_id in your application's database before waiting.
ready = files.wait_until_ready(asset_id)
delivery_url = ready.fetch('cdn_url')
```

An accepted upload can still be processing. Save its ID before waiting so a timeout does not lose the recovery handle. Results are hashes with **string keys**. `upload_bytes(bytes, filename)` accepts a Ruby String containing binary file content. File paths stream in bounded chunks; arbitrary IO objects, pipes and custom readers are unsupported.

## Private files and recovery

```ruby
accepted = files.upload_file('attachment.png', visibility: 'private')
asset_id = accepted.fetch('id')
# Save asset_id against the authenticated user's attachment record here.

begin
  files.wait_until_ready(asset_id, timeout: 120)
  signed = files.generate_private_url(asset_id, expires_in: 3600)
  delivery_url = signed.fetch('private_url')
  # Return this URL only to a user authorized to access the attachment.
rescue Kompressr::Error => error
  if %w[WAIT_TIMEOUT WAIT_CANCELLED REQUEST_TIMEOUT REQUEST_CANCELLED].include?(error.code)
    # Resume from the saved asset_id in a later job. Do not upload again.
  else
    raise
  end
end
```

Private URLs expire independently of their assets. Generate a fresh URL when an authorized user needs access, and keep signed URLs out of ordinary logs. A timeout or cancellation stops the caller; it does not roll back accepted server work. If an upload fails with `error.may_have_succeeded`, save `error.asset_id` when present and inspect that asset before retrying. If no ID was recovered, reconcile the upload through your project records or listing before starting another upload.

The [private-upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/examples/private_upload.rb) saves a recovery ID to a new local file before waiting. From `sdk-ruby`, with `KOMPRESSR_API_KEY` set, run:

```sh
bundle exec ruby examples/private_upload.rb image.png asset-id.txt
```

It keeps the signed URL out of terminal output. In an application, use its `save_asset_id:` callback to persist the ID in your database. To resume from a saved file:

```ruby
saved_id = Integer(File.read('asset-id.txt').strip, 10)
files.wait_until_ready(saved_id)
signed = files.generate_private_url(saved_id)
```

The example refuses to overwrite an existing recovery file. An empty file means no ID was saved; an uncertain upload still needs reconciliation before retrying.

Cancel an operation from another thread using `Kompressr::CancellationToken.new`, pass it as `cancel: token`, then call `token.cancel`. See [errors and timing](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/API.md#errors-and-timing) for fields and deadline behavior.

## Scoped keys for application users

Keep the project key on a trusted backend. Scoped-key management requires a plan that includes that feature; ordinary API upload access alone does not grant it. Use the project key to create a Kompressr identity for your authenticated application user, then issue the permissions that user needs:

```ruby
created = files.platform.create_user('customer-123', display_name: 'Customer 123')
user_id = created.fetch('project_user').fetch('id')
issued = files.platform.create_upload_key(
  user_id, 'Chat attachments',
  scopes: %w[upload status list private_url],
  allowed_visibility: 'private'
)
scoped_key = issued.reveal_api_key
# Store scoped_key in your secret store, bound to this authenticated user.
user_files = Kompressr::Client.new(
  api_key: scoped_key,
  project_id: ENV.fetch('KOMPRESSR_PROJECT_ID') # Required when listing uploads.
)
```

`IssuedKey#inspect`, `to_s`, `to_h` and JSON serialization redact the returned secret. Access it explicitly with `reveal_api_key`; keep that value out of logs. Omitting `scopes` uses the server's defaults: upload, status, listing and private signing. A nonempty list replaces those defaults. **An explicit empty list is rejected before HTTP**; if application permission filtering leaves no scopes, do not issue a key. Deletion requires the explicit `delete` scope.

Store the project-user ID and scoped key once for the user; reuse them for later uploads. Never give the project key to a browser or mobile client. The service enforces project ownership, scopes and plan entitlement. Constructing a platform client with a scoped credential does not grant administrative permissions. Your application remains responsible for authenticating users, storing credentials, checking conversation/attachment access and persisting recovery records. See the [chatbot guide](https://github.com/kompressrcdn/clients/blob/main/guides/chatbot-integration.md) for the complete flow; its application boundaries also apply to Ruby.

## Rails and other frameworks

Use the same `Kompressr::Client` in Rails services or jobs; no adapter is required. Keep long uploads and readiness waits in background jobs when they would occupy a web request worker for too long. [`examples/rails_service.rb`](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/examples/rails_service.rb) illustrates a framework-independent service class you can call from Rails. It accepts a trusted regular file path, which may come from your framework's uploaded temporary file after validation.

```ruby
service = KompressrAttachmentService.new(files: user_files)
service.upload(validated_file_path, attachment_record: attachment)
# In a job, use the ID that upload saved on your record:
service.prepare(attachment.kompressr_asset_id)
# After checking the requesting user's access to this attachment:
url = service.download_url(attachment.kompressr_asset_id)
```

Create a `kompressr_asset_id` bigint column in your application and load/copy the example service before using it. Persist temporary uploads to durable storage before passing their paths to a later job. Configure job retries to resume an existing asset ID rather than repeat an accepted or uncertain upload.

The client is synchronous and thread-safe when inputs remain unchanged during a call. It creates a fresh connection per attempt and has no persistent connection pool to close. It does not automatically use proxy environment variables. This release does not promise asynchronous fiber scheduler integration, JRuby or TruffleRuby compatibility.

## More operations

```ruby
files = Kompressr::Client.new(
  api_key: ENV.fetch('KOMPRESSR_API_KEY'),
  project_id: ENV.fetch('KOMPRESSR_PROJECT_ID')
)
files.iterate_uploads(visibility: 'private', limit: 50).each do |asset|
  # Reconcile asset.fetch('id') with your own records.
end

state = files.get_asset(123)
deletion = files.delete_asset(123)
batch = files.bulk_delete_assets([124, 125])
failures = batch.fetch('results').reject { |item| item.fetch('accepted') }
```

Deletion is permanent and asynchronous. Acceptance means cleanup was requested; it does not establish physical removal or cache invalidation. Bulk deletion keeps each item's outcome, including failures returned inside HTTP 200.

Read the [API reference](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/API.md), [behavior and coverage map](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/PARITY.md), [runnable examples](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/examples) and [publishing instructions](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/PUBLISHING.md).

## Verify from source

```sh
cd sdk-ruby
bundle install
ruby scripts/verify.rb
```

Verification uses local HTTP/TLS fixtures, builds `pkg/kompressr-sdk-0.1.0.gem`, installs it in an isolated gem directory and reruns the regressions against the installed package. It requires no live service credentials. For release verification, run `node scripts/verify-all.mjs ruby` from the repository root instead of the native command; it runs the native verifier plus shared contract, source and archive checks and requires Node.js and Python 3 as well as Ruby.

Report security issues privately using the repository's [security policy](https://github.com/kompressrcdn/clients/blob/main/SECURITY.md). MIT licensed; see [LICENSE](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/LICENSE).
