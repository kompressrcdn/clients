# Ruby

MRI Ruby 3.2+ with OpenSSL and a trusted CA store. Synchronous; compatible with plain Ruby, Rails, Sinatra and Hanami. JRuby, TruffleRuby and asynchronous fiber schedulers are not certified.

Add to the application's Gemfile, then run `bundle install`:

```ruby
gem 'kompressr-sdk', '~> 0.2.0', require: 'kompressr'
```

For a standalone script, `gem install kompressr-sdk` and `require 'kompressr'`. Native dependency installation may need compiler/OpenSSL development packages.

Finish helper; the caller already holds the accepted ID. Supply a callback that commits the ID before returning:

```ruby
require 'kompressr'

def finish_public_upload(files, asset_id, save_asset_id:)
  save_asset_id.call(asset_id)
  ready = files.wait_until_ready(asset_id)
  ready.fetch('cdn_url')
end
```

In the caller, upload once and retain `accepted` before finishing:

```ruby
accepted = files.upload_file(path, visibility: 'public')
url = finish_public_upload(files, accepted.fetch('id'), save_asset_id: save_asset_id)
```

If finishing raises, the caller still has `accepted.fetch('id')` and the original
exception. Retry only finishing after recovery; see
[durable recovery](sdks.md#pattern-used-in-the-language-recipes).

Create `Kompressr::Client.new(api_key: ENV.fetch('KOMPRESSR_API_KEY'))` in backend code. The [private-upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/examples/private_upload.rb) saves a local recovery ID and keeps the private link out of terminal output. The [Rails service example](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/examples/rails_service.rb) demonstrates application persistence and later-job readiness/signing.

## Upload without optimization

For original-byte storage, replace the caller's upload call above with:

```ruby
accepted = files.upload_file(path, visibility: 'public', passthrough: true)
```

The option also applies to `upload_bytes`. Read the acknowledgment as `accepted.fetch('passthrough')`; response keys remain strings. Keep the caller's receipt and the finish step. Follow [upload modes](uploads.md) for eligibility, confirmation, immediate readiness and private signing.

## Methods and shapes

Results are hashes with **string keys**, not symbols. `upload_file` streams regular files; `upload_bytes(bytes, filename)` takes a binary String. Private flow: `visibility: 'private'`, persist ID, `wait_until_ready`, authorize, `generate_private_url(id, expires_in: 3600)`, then read `'private_url'`.

Other methods: `get_upload_status`, `list_uploads`, `iterate_uploads`, `list_assets`, `get_asset`, `delete_asset`, `bulk_delete_assets`. Upload listing needs `project_id`. Platform administration is `files.platform`.

`create_user(customer_id, ...)` and `create_upload_key(user_id, name, ...)` use positional required arguments; do not mechanically translate another SDK's options object. The issued key exposes `reveal_api_key`; normal formatting redacts it. An explicit empty `scopes: []` fails locally; omission uses defaults.

## Application details

- Timeout/poll values are **seconds**. Origins use `api_base_url`, `upload_base_url`.
- `Kompressr::Error` carries `code`, `status`, `asset_id`, `retry_after_ms`, `may_have_succeeded`. Keep IDs and ambiguous outcomes when a job stops.
- Pass a `Kompressr::CancellationToken` as `cancel:` and call `cancel` from the controlling thread. It does not roll back service work.
- Regular paths are supported; arbitrary IO objects, pipes and custom readers are not. Preserve temporary uploads before scheduling later jobs.
- Reuse the synchronous client across threads while inputs remain unchanged. It opens a connection per attempt and needs no pool close. It does not automatically use proxy environment variables.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/README.md)
