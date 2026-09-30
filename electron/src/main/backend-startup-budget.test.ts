// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, expect, it, vi } from 'vitest';

/**
 * #2445 — "Backend did not answer on port 3900 within 300 s".
 *
 * The readiness budget covers the backend. The launch that precedes it — the
 * per-candidate interpreter import probe, staging the bundled sources and port
 * selection — all run before the process exists, so charging that time to the
 * backend left it seconds of its own window and then killed it.
 */
const mocks = vi.hoisted(() => ({
  spawn: vi.fn(),
  listen: vi.fn(),
  close: vi.fn(),
  /** Fake-clock milliseconds each pre-spawn step burns. */
  prespawnMs: 0,
}));

vi.mock('electron', () => ({ app: { isPackaged: true, getPath: () => '/unused-budget-test' } }));
vi.mock('node:child_process', () => ({ spawn: mocks.spawn }));
vi.mock('node:net', () => ({
  createServer: () => {
    const server = Object.assign(new EventEmitter(), {
      listen: (_options: { port: number }, done: () => void) => {
        mocks.listen();
        queueMicrotask(done);
        return server;
      },
      address: () => ({ port: 49152 }),
      close: (done: () => void) => {
        mocks.close();
        done();
      },
    });
    return server;
  },
}));

vi.mock('./runtime-project', () => {
  // Both pre-spawn steps are genuinely slow on a cold, scanner-contended
  // install, and both complete before the backend process exists.
  const burn = async (): Promise<void> => {
    if (mocks.prespawnMs > 0) await vi.advanceTimersByTimeAsync(mocks.prespawnMs);
  };
  return {
    runtimeReady: async () => true,
    runtimeCompatible: async () => true,
    runtimeDependenciesReady: async () => {
      await burn();
      return true;
    },
    stageRuntimeSources: burn,
    runtimePython: () => '/runtime/python',
  };
});

import { BackendSupervisor } from './backend';

const BUDGET_S = '10';

/** A spawned process that is alive but not answering yet — a cold backend boot. */
function fakeChild() {
  const stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} });
  return {
    child: Object.assign(new EventEmitter(), {
      stdin: null,
      stdout,
      stderr: null,
      stdio: [],
    }),
    stdout,
  };
}

function stubBackend(ready: () => boolean): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (!ready()) throw new Error('not listening yet');
      return new Response(JSON.stringify({ status: 'ok', version: 'test' }), {
        headers: { 'x-omnivoice-backend': 'test' },
      });
    }),
  );
}

function stubEnv(): void {
  vi.stubEnv('OMNIVOICE_PORT', '');
  vi.stubEnv('OMNIVOICE_BACKEND_CMD', '');
  vi.stubEnv('VOICESTUDIO_SKIP_BACKEND', '');
  vi.stubEnv('OMNIVOICE_STARTUP_BUDGET_S', BUDGET_S);
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  mocks.prespawnMs = 0;
});

it('gives a freshly spawned backend its whole budget after slow pre-launch work', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
  stubEnv();
  // Two pre-spawn steps at 25 s each against a 10 s budget: the launch alone is
  // 5x the entire readiness window, and it finishes before the process exists.
  mocks.prespawnMs = 25_000;
  let ready = false;
  stubBackend(() => ready);
  const { child } = fakeChild();
  mocks.spawn.mockReturnValue(child);
  const supervisor = new BackendSupervisor();
  try {
    await supervisor.start();
    expect(mocks.spawn).toHaveBeenCalledTimes(1);
    // The backend was spawned moments ago; the elapsed launch must not have
    // already spent its budget and killed it.
    await vi.advanceTimersByTimeAsync(0);
    expect(supervisor.status.stage).toBe('starting');
    await vi.advanceTimersByTimeAsync(9_000);
    expect(supervisor.status.stage).toBe('starting');
    ready = true;
    await vi.advanceTimersByTimeAsync(500);
    expect(supervisor.status.stage).toBe('ready');
  } finally {
    (supervisor as unknown as { child: null }).child = null;
    await supervisor.shutdown();
  }
});

it('still fails the backend once it has had its full budget', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
  stubEnv();
  let ready = false;
  stubBackend(() => ready);
  const { child } = fakeChild();
  mocks.spawn.mockReturnValue(child);
  const supervisor = new BackendSupervisor();
  try {
    await supervisor.start();
    await vi.advanceTimersByTimeAsync(9_000);
    expect(supervisor.status.stage).toBe('starting');
    await vi.advanceTimersByTimeAsync(2_000);
    expect(supervisor.status.stage).toBe('failed');
    expect(supervisor.status.message).toContain('did not answer on port 3900');
  } finally {
    (supervisor as unknown as { child: null }).child = null;
    await supervisor.shutdown();
  }
});

it.each([
  ['silent', null, 'It printed no output.'],
  [
    'noisy',
    'RuntimeError: no module named torch\r\n',
    'Last output: RuntimeError: no module named torch',
  ],
])('carries the backend %s into the budget-expiry message', async (_label, line, expected) => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
  stubEnv();
  stubBackend(() => false);
  const { child, stdout } = fakeChild();
  mocks.spawn.mockReturnValue(child);
  const supervisor = new BackendSupervisor();
  try {
    await supervisor.start();
    if (line) stdout.emit('data', line);
    await vi.advanceTimersByTimeAsync(11_000);
    expect(supervisor.status.stage).toBe('failed');
    expect(supervisor.status.message).toContain(expected);
  } finally {
    (supervisor as unknown as { child: null }).child = null;
    await supervisor.shutdown();
  }
});
