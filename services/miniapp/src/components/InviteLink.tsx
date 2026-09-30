/** Готовая ссылка-приглашение: «Отправить в MAX» и «Скопировать».
 *
 *  Одна на менеджера, работника и клиента: раньше у клиентской ссылки не было
 *  «Отправить в MAX», а неудачное копирование везде молчало — человек
 *  вставлял в чат пустоту.
 */

import { useState } from "react";

import { isInsideMax, shareInMax } from "../lib/bridge";

export function InviteLink({
  link,
  shareText,
  children,
}: {
  link: string;
  /** Подпись к ссылке в чате MAX */
  shareText: string;
  /** Как ссылка работает — одна строка под кнопками */
  children: React.ReactNode;
}) {
  const [copied, setCopied] = useState<boolean | null>(null);

  return (
    <div className="anim-drop mt-2 rounded-2xl bg-[var(--surface)] p-3">
      <p className="t-desc break-all text-text-secondary select-all">{link}</p>
      <div className="mt-2 flex gap-2">
        {isInsideMax() && (
          <button
            type="button"
            onClick={() => shareInMax(shareText, link)}
            className="h-9 flex-1 rounded-xl bg-[var(--accent-soft)] text-[13px]/[16px]
                       font-semibold text-[var(--accent-soft-foreground)]"
          >
            Отправить в MAX
          </button>
        )}
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(link);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
          className="h-9 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px] font-semibold
                     text-[var(--default-foreground)]"
        >
          {copied ? "Скопировано" : "Скопировать"}
        </button>
      </div>
      {copied === false && (
        <p className="anim-fade t-desc mt-2 text-[var(--danger)]">
          Не скопировалось: MAX не дал доступ к буферу. Выделите ссылку выше и скопируйте вручную.
        </p>
      )}
      <p className="t-label mt-2 text-text-secondary">{children}</p>
    </div>
  );
}
