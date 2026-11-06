// Read-only artifact inventory. No Git, network, payload reads, or persistence.
import { lstat, readdir, realpath } from 'node:fs/promises';
import { isAbsolute, join, relative, sep } from 'node:path';

async function directory(path) {
  let info;
  try { info = await lstat(path); }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
  if (info.isSymbolicLink() || !info.isDirectory()) {
    throw new Error('Artifact directory must be a real directory: ' + path);
  }
  return true;
}

async function children(path) {
  if (!await directory(path)) return [];
  const entries = await readdir(path, { withFileTypes: true });
  const result = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.isSymbolicLink()) throw new Error('Aliased artifact directory: ' + join(path, entry.name));
    if (entry.isDirectory()) result.push(join(path, entry.name));
  }
  return result;
}

export async function checkLocalPage(input, repoRoot) {
  if (!input || Object.keys(input).length !== 1 ||
      typeof input.page_id !== 'string' || !/^[0-9a-f]{64}$/.test(input.page_id)) {
    throw new Error('Supply exactly page_id as a lowercase SHA-256 identifier');
  }
  if (typeof repoRoot !== 'string' || !isAbsolute(repoRoot) ||
      await realpath(repoRoot) !== repoRoot) throw new Error('Repository root must be canonical and absolute');
  const groups = {};
  const data = join(repoRoot, 'data');
  const hasData = await directory(data);
  for (const [name, expected] of Object.entries({
    articles: ['article.md', 'meta.md'],
    bookmark: ['bookmark.md', 'meta.md'],
    index: ['utterances.md', 'meta.md'],
  })) {
    const group = groups[name] = { status: 'absent', files: [], artifacts: [] };
    let domains = hasData ? await children(join(data, name)) : [];
    if (name === 'index') {
      const nested = [];
      for (const entity of domains) nested.push(...await children(entity));
      domains = nested;
    }
    for (const domain of domains) {
      const page = join(domain, input.page_id);
      if (!await directory(page)) continue;
      const files = [];
      for (const filename of expected) {
        const path = join(page, filename);
        let info;
        try { info = await lstat(path); }
        catch (error) { if (error.code === 'ENOENT') continue; throw error; }
        if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
          throw new Error('Artifact must be a regular, unaliased file: ' + path);
        }
        files.push(relative(data, path).split(sep).join('/'));
      }
      if (files.length) {
        group.files.push(...files);
        group.artifacts.push({ directory: relative(data, page).split(sep).join('/'),
          files, status: files.length === expected.length ? 'complete' : 'partial' });
      }
    }
    if (group.artifacts.length) {
      group.status = group.artifacts.every(a => a.status === 'complete') ? 'complete' : 'partial';
    }
  }
  return { status: 'ok', page_id: input.page_id, source: 'local-filesystem',
    found: Object.values(groups).some(group => group.files.length > 0), groups };
}
