// Plain-node check of entrypoint/40-phw-glyphs.sh, the startup script that
// turns the two switches into glyphs.json: every state, and that a value
// never reaches its output, its log or the file. Runs a copy with the two
// fixed paths pointed into a temp folder, under the system's POSIX sh (the
// image's is busybox ash). The page's reading of the file is site/glyphs.js,
// used here too. No packages:
// node images/glyph-rain/tools/entrypoint.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseRuntime } from '../site/glyphs.js';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../entrypoint/40-phw-glyphs.sh'), 'utf8');
const tmp = mkdtempSync(join(tmpdir(), 'phw-glyphs-'));
const secretDir = join(tmp, 'etc-phw');
const secret = join(secretDir, 'glyphs');
const out = join(tmp, 'tmp-phw');

// The shipped paths, each exactly once, swapped for the temp ones.
const swap = (text, from, to) => {
  assert.equal(text.split(from).length - 1, 1, `${from.trim()} once in the script`);
  return text.replace(from, to);
};
let script = swap(source, 'SECRET_FILE=/etc/phw/glyphs\n', `SECRET_FILE='${secret}'\n`);
script = swap(script, 'OUT_DIR=/tmp/phw\n', `OUT_DIR='${out}'\n`);
const scriptPath = join(tmp, '40-phw-glyphs.sh');
writeFileSync(scriptPath, script);

const SENTINEL = 'hunter2-not-for-the-log'; // stands for a value nobody may see

// env: PHW_GLYPHS (undefined: not set); file: its content, 'dir' for a
// folder in its place, undefined for none; prepare: last changes by hand.
function run({ env, file, quiet = false, prepare } = {}) {
  rmSync(secretDir, { recursive: true, force: true });
  rmSync(out, { recursive: true, force: true });
  mkdirSync(secretDir);
  if (file === 'dir') mkdirSync(secret);
  else if (file !== undefined) writeFileSync(secret, file);
  prepare?.();
  const e = { PATH: process.env.PATH };
  if (env !== undefined) e.PHW_GLYPHS = env;
  if (quiet) e.NGINX_ENTRYPOINT_QUIET_LOGS = '1';
  const r = spawnSync('sh', [scriptPath], { env: e, encoding: 'utf8' });
  const path = join(out, 'glyphs.json');
  const json = existsSync(path) ? readFileSync(path, 'utf8') : null;
  return { stdout: r.stdout, stderr: r.stderr, status: r.status, json, data: json && JSON.parse(json) };
}

const cases = [
  ['nothing set', {}, ['hieroglyphs'], 'unset', 'absent'],
  ['env music', { env: 'music' }, ['music'], 'match', 'absent'],
  ['env empty = unset', { env: '' }, ['hieroglyphs'], 'unset', 'absent'],
  ['env other value', { env: SENTINEL }, ['hieroglyphs'], 'other', 'absent'],
  ['env case differs', { env: 'Music' }, ['hieroglyphs'], 'other', 'absent'],
  ['file runes', { file: 'runes' }, ['runes'], 'unset', 'match'],
  ['file runes + LF', { file: 'runes\n' }, ['runes'], 'unset', 'match'],
  ['file runes + CRLF', { file: 'runes\r\n' }, ['runes'], 'unset', 'match'],
  ['file runes + space', { file: 'runes \n' }, ['hieroglyphs'], 'unset', 'other'],
  ['file other content', { file: `${SENTINEL}\n` }, ['hieroglyphs'], 'unset', 'other'],
  ['file runes, then more', { file: `runes${'x'.repeat(100)}` }, ['hieroglyphs'], 'unset', 'other'],
  ['file empty', { file: '' }, ['hieroglyphs'], 'unset', 'other'],
  ['file is a folder', { file: 'dir' }, ['hieroglyphs'], 'unset', 'directory'],
  ['both', { env: 'music', file: 'runes\n' }, ['music', 'runes'], 'match', 'match'],
  ['env other, file runes', { env: SENTINEL, file: 'runes' }, ['runes'], 'other', 'match'],
];
if (process.getuid?.() !== 0) {
  // Meaningless as root, who reads anything.
  cases.push(['file unreadable', { file: 'runes', prepare: () => chmodSync(secret, 0o000) }, ['hieroglyphs'], 'unset', 'unreadable']);
}
for (const [name, input, sets, envState, fileState] of cases) {
  const r = run(input);
  assert.equal(r.status, 0, `${name}: exit 0`);
  assert.equal(r.stderr, '', `${name}: nothing on stderr`);
  assert.deepEqual(r.data, { glyphs: sets, env: envState, file: fileState }, name);
  assert.deepEqual(parseRuntime(r.data), { sets, env: envState, file: fileState, loaded: true }, `${name}: the page reads it`);
  for (const text of [r.stdout, r.json]) assert.ok(!text.includes(SENTINEL), `${name}: the value stays out`);
  assert.match(r.stdout, new RegExp(`glyphs: ${sets.join(', ')}\\n$`), `${name}: the log names the sets`);
}
console.log(`ok ${cases.length} switch states: the page reads each, no value in the log or the file`);

{
  const r = run({ file: 'dir' });
  assert.match(r.stdout, /is a directory: mount the volume at \S+etc-phw, the folder/);
  console.log('ok a folder in the file\'s place: the log says where to mount');
}

{
  const r = run({ env: 'music', quiet: true });
  assert.equal(r.stdout, '');
  assert.deepEqual(r.data.glyphs, ['music']);
  console.log('ok NGINX_ENTRYPOINT_QUIET_LOGS silences the log, the file is still written');
}

{
  // A file where the output folder should be: mkdir fails.
  const r = run({ prepare: () => writeFileSync(out, 'not a folder') });
  assert.equal(r.status, 0);
  assert.match(r.stderr, /can't write .*glyphs\.json: the page shows the default/);
  console.log('ok output not writable: exit 0 (the start goes on), said on stderr');
  rmSync(out, { force: true });
}

rmSync(tmp, { recursive: true, force: true });
