# Publishing the Python SDK

The distribution name is `kompressr-sdk`, imported as `kompressr`.

## Set up PyPI access

Create or sign in to the publishing account at [PyPI](https://pypi.org/account/register/) and enable two-factor authentication. For a first release, confirm the package name is available and create an account-wide API token; after creating the project, replace it with a project-scoped token. For an existing project, the account needs owner or maintainer access.

Twine accepts `__token__` as the username and the API token as the password. Enter these through its prompt or your credential manager. Keep the token outside the repository. See [PyPI API tokens](https://pypi.org/help/#apitoken).

## Build and verify

From `sdk-python`, create an isolated environment and verify:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/verify.py
```

The verifier builds a wheel and source distribution in `dist/`, validates metadata/archive contents, and exercises a fresh wheel installation through local HTTP fixtures. Run the verifier across Python 3.11–3.15, as configured in CI. Review README/API/parity documentation and the changelog, and complete agreed authenticated lifecycle and scope checks before release. Changes to the shared contract or sibling packages also require their verification.

Set the agreed version in `pyproject.toml` and `src/kompressr/__init__.py`, update the changelog, then rerun verification. Check the produced artifact names and hashes printed by the verifier. Use only those reviewed files for publication; do not upload stale artifacts or an editable checkout.

A maintainer with publication authorization can upload the two exact artifacts:

```sh
python -m twine upload dist/kompressr_sdk-0.1.0-py3-none-any.whl dist/kompressr_sdk-0.1.0.tar.gz
```

Use your registry's trusted publishing or interactive credential mechanism. Never paste tokens into repository files, shell arguments or examples. The command above publishes to PyPI and should only be run once authorization and namespace control are confirmed. TestPyPI is a separate registry with separate credentials and name ownership; use it only if intentionally testing a release there.

After publication, install the exact registry version in a fresh environment, verify the downloaded distribution hashes against the reviewed artifacts and run a public/private lifecycle using a dedicated test project. Confirm upload, saved-ID readiness, signing, listing, scoped permission denial and deletion status. Issue/rotate/revoke test keys only in that test project. Successful local fixtures do not replace these authenticated checks.

From a new directory, check the public wheel independently of the source checkout:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --no-cache-dir --index-url https://pypi.org/simple kompressr-sdk==0.1.0
python -c 'import kompressr; print(kompressr.__version__)'
python -m pip download --no-deps --only-binary=:all: --index-url https://pypi.org/simple kompressr-sdk==0.1.0
```

Compare the downloaded wheel's SHA-256 with the uploaded wheel. See the [Python packaging guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/). Verification scripts never publish automatically.
