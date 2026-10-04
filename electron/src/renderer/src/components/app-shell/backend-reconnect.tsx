import { useTranslation } from 'react-i18next';
import { getBridge } from '@/components/bridge';
import type { BackendStatus } from '@/hooks/use-backend-status';

/**
 * The way back for an external or remote backend that stopped answering.
 *
 * Such a backend is never declared dead from timeouts alone (a long job can
 * hold it for hours), so the user needs a recovery action while it is merely
 * `unresponsive`. A shell-owned child recovers by itself and must never be
 * restarted from here: that would kill the job it is busy with.
 */
export function BackendReconnect({ status }: { status: BackendStatus }) {
  const { t } = useTranslation();
  if (status.stage !== 'unresponsive' || status.managed) return null;
  return (
    <div className="space-y-2 rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-xs">
      {status.message && <p className="text-foreground/85">{status.message}</p>}
      <button
        type="button"
        onClick={() => void getBridge()?.backend.restart()}
        className="w-full rounded-md border border-border/55 bg-muted/20 px-3 py-1.5 text-left text-xs outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t('backend.retry')}
      </button>
    </div>
  );
}
