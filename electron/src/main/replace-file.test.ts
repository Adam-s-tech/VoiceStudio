// @vitest-environment node
import {
  chmod,
  lstat,
  mkdtemp,
  open,
  readdir,
  readFile,
  rename,
  rm,
  stat,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { replaceFile, type ReplaceFileSystem } from './replace-file';

let directory: string;
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), 'voicestudio-replace-'));
});
afterEach(async () => {
  await rm(directory, { recursive: true, force: true });
});

/** A disk that accepts the first half of a write and then fails (ENOSPC). */
const partialWrite: ReplaceFileSystem = {
  rename,
  open: (async (...args: Parameters<typeof open>) => {
    const handle = await open(...args);
    const write = handle.writeFile.bind(handle);
    handle.writeFile = (async (data: string | Uint8Array) => {
      const bytes = typeof data === 'string' ? Buffer.from(data) : data;
      await write(bytes.subarray(0, bytes.length >> 1));
      throw Object.assign(new Error('no space left on device'), { code: 'ENOSPC' });
    }) as typeof handle.writeFile;
    return handle;
  }) as typeof open,
};

describe('replaceFile', () => {
  it('creates a new destination', async () => {
    const target = join(directory, 'take.wav');
    await replaceFile(target, new Uint8Array([1, 2, 3]));
    expect([...(await readFile(target))]).toEqual([1, 2, 3]);
    expect(await readdir(directory)).toEqual(['take.wav']);
  });

  it('replaces an existing export completely', async () => {
    const target = join(directory, 'take.wav');
    await writeFile(target, 'old export that is longer');
    await replaceFile(target, 'new');
    expect(await readFile(target, 'utf8')).toBe('new');
    expect(await readdir(directory)).toEqual(['take.wav']);
  });

  it('keeps an existing export intact when the write fails partway', async () => {
    const target = join(directory, 'take.wav');
    await writeFile(target, 'complete previous export');
    await expect(replaceFile(target, 'replacement bytes', partialWrite)).rejects.toThrow(
      'no space left',
    );
    expect(await readFile(target, 'utf8')).toBe('complete previous export');
    expect(await readdir(directory)).toEqual(['take.wav']);
  });

  it('keeps an existing export intact when the final replacement fails', async () => {
    const target = join(directory, 'take.wav');
    await writeFile(target, 'complete previous export');
    const failingRename: ReplaceFileSystem = {
      open,
      rename: async () => {
        throw Object.assign(new Error('resource busy'), { code: 'EBUSY' });
      },
    };
    await expect(replaceFile(target, 'replacement', failingRename)).rejects.toThrow('busy');
    expect(await readFile(target, 'utf8')).toBe('complete previous export');
    expect(await readdir(directory)).toEqual(['take.wav']);
  });

  it.skipIf(process.platform === 'win32')('keeps the permissions of a replaced file', async () => {
    const target = join(directory, 'take.wav');
    await writeFile(target, 'old');
    await chmod(target, 0o640);
    await replaceFile(target, 'new');
    expect((await stat(target)).mode & 0o777).toBe(0o640);
  });

  it.skipIf(process.platform === 'win32')('writes through a working symlink', async () => {
    const real = join(directory, 'real.wav');
    const link = join(directory, 'link.wav');
    await writeFile(real, 'old');
    await symlink(real, link);
    await replaceFile(link, 'new');
    expect(await readFile(real, 'utf8')).toBe('new');
    expect((await lstat(link)).isSymbolicLink()).toBe(true);
  });
});
