// Generated package outputs and dependency caches are checked through package
// verification, not as repository source. Keep language exclusions scoped.
export function isGeneratedDirectory(relativePath) {
  const parts = relativePath.split('/');
  if (parts.some(part => ['.git', 'node_modules', 'dist'].includes(part) || part.startsWith('.local-sdk-install-'))) return true;
  if (parts[0] === 'scripts' && parts[1] === 'release' && parts[2] === '__pycache__') return true;
  const [pkg, ...inside] = parts;
  if (pkg === 'sdk-python') return inside.some(part => ['.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'build'].includes(part) || part.endsWith('.egg-info'));
  if (pkg === 'sdk-java') return inside.includes('target');
  if (pkg === 'sdk-dotnet') return inside.some(part => ['bin', 'obj', 'artifacts'].includes(part));
  if (pkg === 'sdk-php') return inside.includes('vendor');
  if (pkg === 'sdk-ruby') return inside.some(part => ['vendor', '.bundle', 'pkg', 'coverage'].includes(part));
  return false;
}
