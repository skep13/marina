// Runs the renderer checks one after another and fails if any of them does.
// Most print a report rather than an exit code, so their output is also
// scanned for the words they use when something is wrong.
//   npm test                  the checks that need nothing else running
//   npm test -- --bridge      also the ones that talk to a running bridge
const { spawnSync } = require('child_process');
const path = require('path');

const electron = require('electron');

const SELF_CONTAINED = ['cue-check', 'mouth-check', 'idle-check', 'mood-check', 'render-check'];
const NEED_BRIDGE = ['stream-check'];
const BAD = [/NO EFFECT/, /\bFAIL\b/, /^errors:/m, /renderer errors\s+[1-9]/, /UNCOUPLED/,
  /"webgl": false/, /bridge not ready/];

const checks = process.argv.includes('--bridge') ? [...SELF_CONTAINED, ...NEED_BRIDGE] : SELF_CONTAINED;
const failed = [];

for (const name of checks) {
  process.stdout.write(`${name} … `);
  const run = spawnSync(electron, [path.join(__dirname, `${name}.js`)], {
    encoding: 'utf8', timeout: 180000,
  });
  const out = `${run.stdout || ''}${run.stderr || ''}`;
  const why = run.status !== 0 ? `exited ${run.status ?? run.signal}`
    : BAD.find((re) => re.test(run.stdout || ''))?.toString();
  if (why) {
    failed.push(name);
    console.log(`FAILED (${why})\n${out.split('\n').map((l) => `    ${l}`).join('\n')}`);
  } else {
    console.log('ok');
  }
}

console.log(failed.length ? `\n${failed.length} failed: ${failed.join(', ')}` : '\nall passed');
process.exit(failed.length ? 1 : 0);
