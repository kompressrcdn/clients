import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve, relative, dirname, isAbsolute } from 'node:path';

const publicHosts = new Set(['kompressr.com', 'uploads.kompressr.com', 'cdn.kompressr.com', 'api.kompressr.com']);

export function checkPublicContent(content, label) {
  for (const hostname of content.match(/\b(?:[a-z0-9-]+\.)*kompressr\.com\b/gi) ?? []) {
    assert(publicHosts.has(hostname.toLowerCase()), `Undeclared service hostname in ${label}`);
  }
  assert(!/(?:\/home\/|\/Users\/)[^\s'"`]+|\/tmp\/[A-Za-z0-9_-]+/.test(content), `Machine-specific path in ${label}`);
  assert(!/\bnpm_[A-Za-z0-9]{30,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/.test(content), `Credential-like token in ${label}`);
  assert(!/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(content), `Private key in ${label}`);
}

export function checkPublicPath(path) {
  assert(!/(?:^|\/)(?:\.env(?:\..*)?|\.npmrc|CLIENT_CONTEXT\.md|[^/]+\.(?:pem|p12|pfx))$/.test(path), `Private configuration or record in ${path}`);
  assert(!/(?:^|\/)docs\/(?:plans|reviews)\//.test(path), `Operational record directory in ${path}`);
}

export function checkPublicFile(file, root, label = relative(root, file)) {
  checkPublicPath(label);
  const content = readFileSync(file, 'utf8');
  checkPublicContent(content, label);
  for (const match of content.matchAll(/["'`(]((?:\.\.\/)+[^\s"'`)]+)/g)) {
    const target = resolve(dirname(file), match[1]);
    const local = relative(root, target);
    assert(local !== '..' && !local.startsWith('../') && !isAbsolute(local), `Reference leaves repository in ${label}`);
  }
}

export function checkPackedFiles(files, packageRoot, repositoryRoot) {
  for (const file of files) {
    checkPublicPath(file.path);
    checkPublicFile(resolve(packageRoot, file.path), repositoryRoot, file.path);
  }
}
