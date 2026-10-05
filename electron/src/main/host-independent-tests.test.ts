// @vitest-environment node
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';

/**
 * The rehearsal's Intel-Mac leg failed a supervisor test that passes on every
 * other host: setupRuntime() refuses a real darwin/x64 process outright
 * (#2365), so a fixture that drives it never spawned there. Normal PR CI is
 * Linux-only, so this class has to be caught statically: a test that drives the
 * install entry points through the real supervisor must pin its architecture.
 */
it('pins the host architecture in every test that drives the real runtime installer', () => {
  const dir = __dirname;
  const offenders = readdirSync(dir)
    .filter((name) => name.endsWith('.test.ts') && name !== 'host-independent-tests.test.ts')
    .filter((name) => {
      const source = readFileSync(join(dir, name), 'utf8');
      const drivesInstaller =
        /new BackendSupervisor\(/.test(source) &&
        /\.(?:setupRuntime|cleanSetupRuntime)\(/.test(source);
      const pinsArch = /(?:spyOn\(process, 'arch'|defineProperty\(process, 'arch')/.test(source);
      return drivesInstaller && !pinsArch;
    });
  expect(offenders).toEqual([]);
});
