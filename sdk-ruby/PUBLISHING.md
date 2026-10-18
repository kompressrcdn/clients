# Publishing the Ruby SDK

Publish the `kompressr-sdk` gem to RubyGems.org. Its require path is `kompressr` and public namespace is `Kompressr`.

## Set up RubyGems access

Create or sign in to the publishing account at [RubyGems.org](https://rubygems.org/sign_up) and enable MFA. Confirm access to the gem name; for an existing gem, the account must be an owner. Use `gem signin --host https://rubygems.org` to authenticate interactively, or configure a scoped API key through RubyGems' credential mechanism outside the repository. See the [official publishing guide](https://guides.rubygems.org/publishing/).

## Prepare and verify

From a clean reviewed checkout:

```sh
cd sdk-ruby
bundle install
cd ..
node scripts/verify-all.mjs ruby
```

Run this with MRI Ruby 3.2, 3.3, 3.4 and 4.0 before release. The root command requires Node.js and Python 3 alongside Ruby and Bundler. It invokes the native verifier, which checks Ruby syntax, runs real HTTP/TLS regressions, builds the explicit payload allowlist, validates the gem and installs it into an isolated gem directory before repeating the suite. It prints the verified SHA-256 digest. The root verifier also checks the public contract, source and nested `.gem` archive content. For a shorter development check, run `ruby scripts/verify.rb` from `sdk-ruby`; release verification still requires the root command. A passing JS/MCP verifier does not verify this gem.

The artifact is `sdk-ruby/pkg/kompressr-sdk-0.1.0.gem`. Inspect its metadata, README, examples and `lib/` payload. Do not ship tests, package caches, local configuration or credentials. Set version in `lib/kompressr/version.rb`; update the changelog and install examples for an actual release. Keep review/testing tools outside the runtime dependencies. The gem deliberately declares its standard-gem dependencies so Bundler can resolve them across supported Ruby versions.

## Authenticated acceptance

Using a dedicated project and disposable files, verify these against the intended deployed service:

1. Upload a public and private file, persist their accepted IDs, wait for readiness and retrieve the public URL or generate a private link. Check delivery bytes and expiry.
2. Stop a wait and resume it using the saved ID; verify no duplicate upload is created.
3. List/filter assets and inspect managed-asset state. Delete the disposable files; inspect acceptance separately from completed deletion.
4. With appropriate project authority, create an identity and scoped key, perform permitted operations, then verify forbidden operations and cross-user access remain denied. An explicit empty scopes array must fail locally; omission must use the documented defaults.
5. Rotate/revoke the test key and suspend/reactivate the identity. Verify the corresponding access changes. Clean up the disposable resources.

Store credentials outside the checkout and pass them through your environment or secret store. Do not include returned keys, signed links or private account details in test logs. Local fixtures cannot establish deployed authorization or paid-plan entitlement.

## Publish the verified artifact

Authenticate to the intended RubyGems account using its current MFA/API-key workflow, then publish the exact artifact whose digest was reviewed:

```sh
gem push sdk-ruby/pkg/kompressr-sdk-0.1.0.gem --host https://rubygems.org
```

Run that command from the repository root, only after the release is authorized. RubyGems rejects replacement of an existing version; use a new version for subsequent fixes. The gem declares `rubygems_mfa_required` and restricts the push host to RubyGems.

## Verify anonymous installation

After publication, use a new directory with a minimal Gemfile:

```ruby
source 'https://rubygems.org'
gem 'kompressr-sdk', '= 0.1.0', require: 'kompressr'
```

Run `bundle install`, then:

```sh
bundle exec ruby -e 'require "kompressr"; puts Kompressr::VERSION'
gem fetch kompressr-sdk --version 0.1.0 --source https://rubygems.org
```

Compare the downloaded `.gem` SHA-256 with the verified artifact and repeat a basic disposable upload/readiness test from that installation. Confirm the public repository links and examples resolve. Record the released version, source revision and archive digest in the release notes.
