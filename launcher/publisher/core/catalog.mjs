const idPattern = /^[a-z0-9][a-z0-9-]{0,79}$/;
const platforms = new Set(['linux', 'windows', 'macos']);
export function assert(condition, message) { if (!condition) throw new Error(message); }
export function validId(id) { assert(typeof id === 'string' && idPattern.test(id), 'Invalid identifier'); return id; }
export function relativePath(value) {
  assert(typeof value === 'string' && value.length > 0 && value.length < 1024, 'Invalid package path');
  assert(!value.includes('\\') && !value.includes('\0') && !value.startsWith('/'), 'Unsafe package path');
  const parts = value.split('/');
  assert(parts.every(p => p && p !== '.' && p !== '..' && !/[<>:"|?*\x00-\x1f]/.test(p) && !/[ .]$/.test(p) && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p)), 'Unsafe package path');
  return value;
}
export function validatePackage(p) {
  assert(p && typeof p === 'object', 'Missing package');
  validId(p.id); validId(p.gameId);
  assert(platforms.has(p.platform) && ['x64', 'arm64', 'any'].includes(p.arch), 'Unsupported target');
  assert(['zip', 'tar.gz'].includes(p.format), 'Unsupported archive format');
  assert(['native', 'web'].includes(p.kind), 'Runtime is not yet packaged');
  assert(typeof p.version === 'string' && p.version.length < 160, 'Invalid version');
  assert(/^[a-f0-9]{64}$/.test(p.sha256), 'Invalid SHA-256');
  for (const field of ['sizeBytes', 'unpackedBytes', 'maxFiles']) assert(Number.isSafeInteger(p[field]) && p[field] > 0, 'Invalid ' + field);
  assert(p.sizeBytes <= 10 * 1024 ** 3 && p.unpackedBytes <= 40 * 1024 ** 3 && p.maxFiles <= 100000, 'Package exceeds limits');
  relativePath(p.entrypoint);
  if (p.cwd) relativePath(p.cwd);
  assert(!p.args || Array.isArray(p.args) && p.args.length < 24 && p.args.every(a => typeof a === 'string' && a.length < 1024 && !a.includes('\0')), 'Invalid arguments');
  assert(typeof p.url === 'string', 'Missing package URL');
  const url = new URL(p.url);
  assert(url.protocol === 'https:' && !url.username && !url.password && !url.hash, 'Package URL must be HTTPS');
  assert(Array.isArray(p.allowedHosts) && p.allowedHosts.length > 0 && p.allowedHosts.length < 10 && p.allowedHosts.every(h => /^[a-z0-9.-]+$/.test(h) && !h.includes('..')), 'Invalid download hosts');
  assert(p.allowedHosts.includes(url.hostname), 'Package host is not approved');
  assert(p.qualification === 'qualified', 'Package has not been qualified');
  assert(typeof p.savePolicy === 'string' && p.savePolicy.length > 0, 'Missing save policy');
  return p;
}
export function validateCatalog(c) {
  assert(c?.schemaVersion === 1 && Number.isSafeInteger(c.revision) && c.revision > 0, 'Unsupported catalog');
  if(c.validUntil) assert(Number.isFinite(Date.parse(c.validUntil)), 'Invalid catalog expiry');
  assert(Array.isArray(c.games) && c.games.length <= 300 && Array.isArray(c.packages) && c.packages.length <= 2000, 'Catalog too large');
  const games = new Set(); const packages = new Set();
  for (const g of c.games) { validId(g.id); assert(!games.has(g.id), 'Duplicate game'); games.add(g.id); assert(typeof g.title === 'string' && g.title.length < 180, 'Invalid title'); }
  for (const p of c.packages) { validatePackage(p); assert(games.has(p.gameId) && !packages.has(p.id), 'Invalid package reference'); packages.add(p.id); }
  return c;
}
export function targetPlatform() { return process.platform === 'win32' ? 'windows' : process.platform === 'darwin' ? 'macos' : 'linux'; }
export function packageForGame(catalog, gameId, platform = targetPlatform(), arch = process.arch) {
  return catalog.packages.filter(p => p.gameId === gameId && p.platform === platform && (p.arch === arch || p.arch === 'any')).sort((a,b) => (b.sequence || 0) - (a.sequence || 0))[0];
}
