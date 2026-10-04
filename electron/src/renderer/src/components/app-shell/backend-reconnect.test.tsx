import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { FALLBACK_BACKEND_STATUS } from '@/hooks/use-backend-status';
import { BackendReconnect } from './backend-reconnect';

const restart = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('@/components/bridge', () => ({ getBridge: () => ({ backend: { restart } }) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

beforeEach(() => restart.mockClear());

const status = (patch: object) => ({ ...FALLBACK_BACKEND_STATUS, ...patch });

it('offers a reconnect for an unresponsive external backend', () => {
  render(
    <BackendReconnect
      status={status({ stage: 'unresponsive', managed: false, message: 'busy for a while' })}
    />,
  );
  expect(screen.getByText('busy for a while')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'backend.retry' }));
  expect(restart).toHaveBeenCalledOnce();
});

it('never offers a restart for a shell-owned child or a healthy backend', () => {
  const { container, rerender } = render(
    <BackendReconnect status={status({ stage: 'unresponsive', managed: true })} />,
  );
  expect(container.innerHTML).toBe('');
  rerender(<BackendReconnect status={status({ stage: 'ready', managed: false })} />);
  expect(container.innerHTML).toBe('');
});
