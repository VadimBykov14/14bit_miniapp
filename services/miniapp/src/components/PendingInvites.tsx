/** Приглашения, которые ждут ответа.
 *
 *  Поставщик позвал человека из списка «Кто запускал бота» — подключения ещё
 *  нет, оно появится, только когда человек сам примет приглашение. Главный
 *  путь — кнопка в сообщении бота, но если MAX его не доставил, приглашение
 *  ждёт здесь: на главной и на первом входе. Принять — открыть витрину,
 *  отклонить — тот, кто звал, узнает ответ.
 */

import { useState } from "react";

import { acceptInvite, declineInvite, getMyInvites, setActiveRole } from "../lib/api";
import { haptic } from "../lib/bridge";
import { clearCache } from "../lib/cache";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";

export function PendingInvites() {
  const invites = useAsync(getMyInvites, []);
  // Позвали, пока приложение открыто, — приглашение появляется сразу.
  useLive("invites", invites.refresh);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gone, setGone] = useState<string[]>([]);

  const rows = (invites.data ?? []).filter((row) => !gone.includes(row.code));
  if (!rows.length) return null;

  async function accept(code: string) {
    setBusy(code);
    setError(null);
    try {
      const result = await acceptInvite(code);
      haptic("success");
      // Появилась роль или витрина — приложение открывается заново, сразу
      // в витрине, куда позвали.
      setActiveRole(result.role);
      clearCache();
      window.location.replace(result.storefront_id ? `/s/${result.storefront_id}` : "/");
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      setBusy(null);
    }
  }

  async function decline(code: string) {
    setBusy(code);
    setError(null);
    try {
      await declineInvite(code);
      setGone((prev) => [...prev, code]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <ul className="flex flex-col gap-3 px-4 pb-3">
      {rows.map((row) => (
        <li key={row.code} className="anim-rise rounded-2xl bg-[var(--accent-soft)] p-4">
          <p className="t-title text-[var(--accent-soft-foreground)]">Вас пригласили</p>
          <p className="t-desc mt-1 text-[var(--accent-soft-foreground)]">{row.text}</p>
          {error && busy === null && (
            <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => accept(row.code)}
              className="h-11 min-w-0 flex-1 rounded-xl bg-[var(--accent)] px-3 text-[15px]/[20px]
                         font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
            >
              {busy === row.code ? "Принимаю…" : "Принять приглашение"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => decline(row.code)}
              className="h-11 shrink-0 rounded-xl bg-[var(--default)] px-4 text-[15px]/[20px]
                         font-semibold text-[var(--default-foreground)] disabled:opacity-60"
            >
              Отклонить
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
