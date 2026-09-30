/** Всплывающее сообщение внизу экрана: «уже нет в наличии», «убрано из
 *  заявки — вернуть», «контакт в чате с ботом».
 *
 *  Внизу, над панелью действий, а не вверху страницы: человек в этот
 *  момент листает каталог, и карточку наверху он бы не увидел. Уезжает
 *  само, но важное держится дольше — его успевают прочитать.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ToastMessage {
  /** Новый id — новое сообщение, даже если текст тот же */
  id: number;
  text: React.ReactNode;
  tone?: "neutral" | "warning";
  action?: { label: string; run: () => void };
  /** Сколько держать, мс. 0 — пока не закроют. */
  duration?: number;
}

const OUT_MS = 200;

export function Toast({
  message,
  onClose,
  bottom = 16,
}: {
  message: ToastMessage | null;
  onClose: () => void;
  /** Отступ снизу: над панелью действий, если она есть */
  bottom?: number;
}) {
  const [shown, setShown] = useState<ToastMessage | null>(message);
  const [leaving, setLeaving] = useState(false);
  const latestClose = useRef(onClose);
  latestClose.current = onClose;

  useEffect(() => {
    if (message) {
      setShown(message);
      setLeaving(false);
      const duration = message.duration ?? 5000;
      if (!duration) return;
      const timer = window.setTimeout(() => latestClose.current(), duration);
      return () => window.clearTimeout(timer);
    }
    if (!shown) return;
    setLeaving(true);
    const timer = window.setTimeout(() => {
      setShown(null);
      setLeaving(false);
    }, OUT_MS);
    return () => window.clearTimeout(timer);
    // shown нужен только чтобы знать, есть ли что прятать
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message]);

  if (!shown) return null;

  return createPortal(
    <div
      className="toast-layer pointer-events-none fixed inset-x-0 z-[60] mx-auto w-full max-w-[var(--app-width,560px)] px-4"
      style={{ bottom: `calc(${bottom}px + env(safe-area-inset-bottom))` }}
    >
      <div
        key={shown.id}
        role="status"
        className={`pointer-events-auto flex items-center gap-3 rounded-2xl px-4 py-3 shadow-lg ${
          leaving ? "toast-out" : "toast-in"
        } ${
          shown.tone === "warning"
            ? "bg-[var(--warning)] text-[#1c1300]"
            : "bg-[var(--foreground)] text-[var(--background)]"
        }`}
      >
        <div className="t-detail min-w-0 flex-1">{shown.text}</div>
        {shown.action ? (
          <button
            type="button"
            onClick={() => {
              shown.action?.run();
              latestClose.current();
            }}
            className="shrink-0 text-[15px]/[20px] font-semibold underline-offset-2"
          >
            {shown.action.label}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => latestClose.current()}
            className="shrink-0 text-[15px]/[20px] font-semibold opacity-80"
          >
            Понятно
          </button>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Одно сообщение за раз: новое заменяет старое. */
export function useToast(): {
  message: ToastMessage | null;
  show: (text: React.ReactNode, options?: Omit<ToastMessage, "id" | "text">) => void;
  hide: () => void;
} {
  const [message, setMessage] = useState<ToastMessage | null>(null);
  const counter = useRef(0);
  const show = useCallback(
    (text: React.ReactNode, options: Omit<ToastMessage, "id" | "text"> = {}) => {
      counter.current += 1;
      setMessage({ id: counter.current, text, ...options });
    },
    [],
  );
  const hide = useCallback(() => setMessage(null), []);
  return { message, show, hide };
}
