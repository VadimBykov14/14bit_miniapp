/** «Точно?» перед необратимым: отмена заявки, отмена поставки, удаление
 *  шаблона.
 *
 *  Шторка, а не системный confirm(): в вебвью MAX системное окно выглядит
 *  чужим, а на части телефонов не показывается вовсе. Раньше такие действия
 *  срабатывали с одного касания или «вторым касанием по тому же крестику» —
 *  его легко сделать случайно, а понять, что произошло, трудно.
 *
 *  Ошибку показываем здесь же и шторку не закрываем: человек видит причину
 *  и может повторить, не начиная заново.
 */

import { useEffect, useState } from "react";

import { haptic } from "../lib/bridge";
import { Sheet } from "./Sheet";

export function ConfirmSheet({
  open,
  title,
  text,
  action,
  busyLabel,
  tone = "danger",
  disabled = false,
  cancel = "Не сейчас",
  children,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  text?: React.ReactNode;
  /** Надпись на главной кнопке: «Отменить заявку», «Удалить шаблон» */
  action: string;
  /** Пока идёт запрос: «Отменяю…» */
  busyLabel: string;
  tone?: "danger" | "accent";
  /** Главная кнопка недоступна — например, пока не написана причина */
  disabled?: boolean;
  /** Надпись на второй кнопке: «Не сейчас», у удаления шаблона — «Отмена» */
  cancel?: string;
  /** Поле причины, выбор даты — то, что нужно для действия */
  children?: React.ReactNode;
  /** Бросает ошибку — шторка остаётся открытой с причиной */
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Прошлая ошибка не должна встречать человека при следующем открытии.
  useEffect(() => {
    if (open) setError(null);
  }, [open]);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      haptic("success");
      onClose();
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={() => !busy && onClose()} label={title}>
      <div className="flex flex-col gap-3 px-4 pb-2">
        <div>
          <p className="t-subheader">{title}</p>
          {text && <p className="t-desc mt-1 text-text-secondary">{text}</p>}
        </div>
        {children}
        {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={busy || disabled}
            onClick={confirm}
            className={`h-[52px] w-full rounded-xl text-[16px]/[20px] font-semibold
                        disabled:opacity-60 ${
                          tone === "danger"
                            ? "bg-[var(--danger)] text-[var(--danger-foreground)]"
                            : "bg-[var(--accent)] text-[var(--accent-foreground)]"
                        }`}
          >
            {busy ? busyLabel : action}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            {cancel}
          </button>
        </div>
      </div>
    </Sheet>
  );
}
