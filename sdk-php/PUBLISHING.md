# Publishing the PHP SDK

Publish `kompressr/sdk` through Packagist using a public repository that contains the PHP package at its root. Create a [Packagist account](https://packagist.org/register/) and confirm publisher access to the package name. GitHub access and Packagist ownership are separate.

## Prepare and verify

1. Review source changes, update `VERSION` and `CHANGELOG.md`, and run `php scripts/verify.php` on supported runtimes.
2. From the clients repository root, run `node scripts/check-public-content.mjs`, then `node scripts/check-distribution.mjs sdk-php/dist/kompressr-sdk-0.1.0.tar`. Review the archive members and the clean consumer output.
3. Run authenticated smoke checks with a dedicated project: public/private upload, readiness, signing, listing, scoped access denial, rotation/revocation and deletion. Save accepted IDs; remove only test-owned assets. Local fixtures do not replace service checks.

## Create a package-root release repository

[Packagist](https://packagist.org/about) expects `composer.json` at the repository root. This package lives in a subdirectory of the clients monorepo, so it needs a separate public release mirror containing only `sdk-php` as its root. Keep development here; do not publish the entire clients repository as this Composer package.

Create an empty public GitHub repository for the mirror, for example `kompressrcdn/sdk-php`, without an initial README or license. The following commands use that example; substitute the actual mirror URL if you choose another name. Run the split from the clients repository root after committing the reviewed PHP files:

```sh
KOMPRESSR_PHP_SPLIT="$(git subtree split --prefix=sdk-php HEAD)"
git ls-tree --name-only "$KOMPRESSR_PHP_SPLIT"
git log --oneline "$KOMPRESSR_PHP_SPLIT"
```

Inspect the tree and history. The root must contain `composer.json`, `src`, `VERSION`, license, docs and examples. Uncommitted changes are not included. Publish the reviewed split to the mirror:

```sh
KOMPRESSR_PHP_MIRROR=git@github.com:kompressrcdn/sdk-php.git
git push "$KOMPRESSR_PHP_MIRROR" "$KOMPRESSR_PHP_SPLIT:refs/heads/main"
git push "$KOMPRESSR_PHP_MIRROR" "$KOMPRESSR_PHP_SPLIT:refs/tags/v0.1.0"
```

The second command creates `v0.1.0` **in the mirror** at the split commit. Do not tag the monorepo root as the PHP package or force-update a published tag. For subsequent releases, repeat the split from the new reviewed commit and use a new version tag.

In Packagist, choose **Submit** and enter the mirror's HTTPS repository URL, for example `https://github.com/kompressrcdn/sdk-php`. Review the package name, then submit. Enable the [GitHub auto-update hook](https://packagist.org/about#how-to-update-packages) or use the package's **Update** action after pushing a tag. Confirm Packagist lists version `0.1.0` at the expected commit. Versions come from tags; `composer.json` deliberately has no hard-coded `version` field.

## Verify the public release

Use a fresh application without local path/package repositories. Run these commands in a new directory:

```sh
composer init --name=example/kompressr-release-check --no-interaction
composer require kompressr/sdk:0.1.0 --no-interaction
composer show kompressr/sdk
```

Confirm that Composer resolved the expected public repository/tag and installed the reviewed files. Run public/private smoke checks from that installed package against a dedicated project. Check that source archives and documentation are accessible anonymously and contain no credentials or private endpoints. Keep production verification results separate from the local test report.

See [Composer libraries](https://getcomposer.org/doc/02-libraries.md) and [repository formats](https://getcomposer.org/doc/05-repositories.md) for version/tag and mirror configuration.
