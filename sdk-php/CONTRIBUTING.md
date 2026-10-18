# Contributing to the PHP SDK

Use 64-bit PHP 8.1+ with `ext-curl` (asynchronous DNS), Composer 2, and standard JSON/Phar support. Verification uses local loopback sockets and process creation. No account or live credentials are required.

From this directory:

```sh
composer install --no-interaction --no-scripts --no-plugins
php scripts/verify.php
```

`composer test` runs only the HTTP regressions. Full verification lints source/examples, validates the manifest, runs those regressions, builds a Composer TAR and installs the actual archive in a new consumer directory. The installed package repeats the HTTP suite, including a 32 MiB streaming-memory check. The archive remains in `dist/`; the temporary consumer is removed. Set `KOMPRESSR_COMPOSER` to the path of a Composer PHAR if Composer is not on `PATH`.

Run the verifier across PHP 8.1–8.5, as configured in CI, when changing transport behavior. Keep fixtures synthetic and public-safe. Update [API](API.md) and [parity](PARITY.md) when adding or changing behavior. Preserve mutation uncertainty and the distinction between upload acceptance and deliverability.

The shared public-content and archive guards must also pass before release. Built distributions, `vendor/` and the development `composer.lock` are not source files for this dependency-free library. The release version is recorded in `VERSION`; Packagist derives versions from release tags.
