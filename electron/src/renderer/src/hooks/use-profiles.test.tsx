import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Profile } from '@/lib/api/types';
import { queryKeys } from '@/lib/query';
import { cloneSettingsStore, patchCloneSettings } from '@/lib/store/clone-settings';

const mock = vi.hoisted(() => ({
  replace: vi.fn(),
  remove: vi.fn(),
  list: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}));
vi.mock('@/lib/api/profiles', () => ({
  createCloneProfile: vi.fn(),
  deleteProfile: mock.remove,
  listProfiles: mock.list,
  replaceProfileAudio: mock.replace,
}));
vi.mock('./use-backend-status', () => ({ useBackendStatus: () => ({ stage: 'ready' }) }));
import { useDeleteProfile, useReplaceProfileAudio } from './use-profiles';
import { readDraft, writeDraft } from '@/features/design/design-draft';

vi.mock('sonner', () => ({ toast: { error: mock.error, success: mock.success } }));
vi.mock('@/lib/i18n-text', () => ({
  tr: (key: string, options?: { message?: string }) => `${key}: ${options?.message ?? ''}`,
}));

const profile = (patch: Partial<Profile>): Profile =>
  ({ id: 'v1', name: 'Voice', kind: 'clone', ref_text: 'old words', ...patch }) as Profile;

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData<Profile[]>(queryKeys.profiles, [
    profile({ audio_url: '/profiles/v1/audio?v=1' }),
    profile({ id: 'v2', name: 'Other' }),
  ]);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useReplaceProfileAudio(), { wrapper }) };
}

afterEach(() => {
  vi.clearAllMocks();
  patchCloneSettings({ selectedProfileId: null, refText: '' });
  localStorage.clear();
});

it('writes the replaced clip back into the cached profile and the selected transcript', async () => {
  const updated = profile({ ref_text: 'new words', audio_url: '/profiles/v1/audio?v=2' });
  mock.replace.mockResolvedValue(updated);
  patchCloneSettings({ selectedProfileId: 'v1', refText: 'old words' });
  const { client, result } = setup();
  const clip = new File(['audio'], 'take.wav', { type: 'audio/wav' });

  await act(() => result.current.mutateAsync({ id: 'v1', refAudio: clip, refText: '' }));

  expect(mock.replace).toHaveBeenCalledWith('v1', { refAudio: clip, refText: '' });
  const cached = client.getQueryData<Profile[]>(queryKeys.profiles)!;
  expect(cached[0]).toEqual(updated);
  expect(cached[1].id).toBe('v2');
  expect(cloneSettingsStore.state.refText).toBe('new words');
});

it('leaves the composer alone when another voice is selected', async () => {
  mock.replace.mockResolvedValue(profile({ ref_text: 'new words' }));
  patchCloneSettings({ selectedProfileId: 'v2', refText: 'keep me' });
  const { result } = setup();

  await act(() => result.current.mutateAsync({ id: 'v1', refAudio: new Blob(['a']) }));

  expect(cloneSettingsStore.state.refText).toBe('keep me');
});

function setupDelete() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData<Profile[]>(queryKeys.profiles, [profile({}), profile({ id: 'v2' })]);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useDeleteProfile(), { wrapper }) };
}

it('clears deleted clone and design references after cleanup fails and the list confirms deletion', async () => {
  const detail = 'The profile record was deleted, but asset cleanup is incomplete for: ref.wav.';
  mock.remove.mockRejectedValue(new Error(detail));
  mock.list.mockResolvedValue([profile({ id: 'v2' })]);
  patchCloneSettings({ selectedProfileId: 'v1' });
  writeDraft({ ...readDraft(), profileId: 'v1' });
  const { client, result } = setupDelete();

  await act(async () => {
    await expect(result.current.mutateAsync('v1')).rejects.toThrow(detail);
  });

  expect(cloneSettingsStore.state.selectedProfileId).toBeNull();
  expect(readDraft().profileId).toBeNull();
  expect(client.getQueryData<Profile[]>(queryKeys.profiles)?.map((p) => p.id)).toEqual(['v2']);
  expect(mock.error).toHaveBeenCalledWith(expect.stringContaining(detail));
  expect(mock.success).not.toHaveBeenCalled();
});

it.each(['rollback', 'unreachable'])(
  'preserves selected voices when deletion cannot be confirmed: %s',
  async (failure) => {
    mock.remove.mockRejectedValue(new Error('database commit failed'));
    if (failure === 'rollback') mock.list.mockResolvedValue([profile({}), profile({ id: 'v2' })]);
    else mock.list.mockRejectedValue(new Error('backend unavailable'));
    patchCloneSettings({ selectedProfileId: 'v1' });
    writeDraft({ ...readDraft(), profileId: 'v1' });
    const { client, result } = setupDelete();

    await act(async () => {
      await expect(result.current.mutateAsync('v1')).rejects.toThrow('database commit failed');
    });

    expect(cloneSettingsStore.state.selectedProfileId).toBe('v1');
    expect(readDraft().profileId).toBe('v1');
    expect(client.getQueryData<Profile[]>(queryKeys.profiles)?.map((p) => p.id)).toEqual([
      'v1',
      'v2',
    ]);
    expect(mock.error).toHaveBeenCalledWith(expect.stringContaining('database commit failed'));
  },
);

it('preserves another selected voice after a confirmed partial deletion', async () => {
  mock.remove.mockRejectedValue(new Error('cleanup incomplete'));
  mock.list.mockResolvedValue([profile({ id: 'v2' })]);
  patchCloneSettings({ selectedProfileId: 'v2' });
  writeDraft({ ...readDraft(), profileId: 'v2' });
  const { result } = setupDelete();

  await act(async () => {
    await expect(result.current.mutateAsync('v1')).rejects.toThrow('cleanup incomplete');
  });

  expect(cloneSettingsStore.state.selectedProfileId).toBe('v2');
  expect(readDraft().profileId).toBe('v2');
});

it('clears selected voices after an ordinary successful deletion', async () => {
  mock.remove.mockResolvedValue(undefined);
  patchCloneSettings({ selectedProfileId: 'v1' });
  writeDraft({ ...readDraft(), profileId: 'v1' });
  const { result } = setupDelete();

  await act(() => result.current.mutateAsync('v1'));

  expect(cloneSettingsStore.state.selectedProfileId).toBeNull();
  expect(readDraft().profileId).toBeNull();
  expect(mock.success).toHaveBeenCalled();
  expect(mock.error).not.toHaveBeenCalled();
});
