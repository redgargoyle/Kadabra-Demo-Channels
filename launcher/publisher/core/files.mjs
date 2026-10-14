import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
export async function atomicJson(file, value) {
  await fs.mkdir(path.dirname(file), {recursive:true, mode:0o700});
  const tmp = file + '.' + randomUUID() + '.tmp';
  const handle = await fs.open(tmp, 'wx', 0o600);
  try { await handle.writeFile(JSON.stringify(value, null, 2) + '\n'); await handle.sync(); } finally { await handle.close(); }
  await fs.rename(tmp, file);
  if (process.platform !== 'win32') { const dir = await fs.open(path.dirname(file), 'r'); try { await dir.sync(); } finally { await dir.close(); } }
}
export async function readJson(file, fallback) { try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch(e) { if (e.code === 'ENOENT') return fallback; throw e; } }
export async function spaceAt(directory) { await fs.mkdir(directory, {recursive:true}); const resolved = await fs.realpath(directory); const s = await fs.statfs(resolved, {bigint:true}); return {path:resolved, availableBytes:Number(s.bavail * s.bsize), filesystem:String(s.type)}; }
export async function requireSpace(directory, needed, reserve = 512 * 1024 ** 2) { const s = await spaceAt(directory); if (s.availableBytes < needed + reserve) throw new Error('Not enough free space. Need ' + Math.ceil((needed + reserve)/1024**2) + ' MiB on ' + s.path); return s; }
export function inside(root, candidate) { const rel = path.relative(root, candidate); return rel === '' || !rel.startsWith('..' + path.sep) && rel !== '..' && !path.isAbsolute(rel); }
