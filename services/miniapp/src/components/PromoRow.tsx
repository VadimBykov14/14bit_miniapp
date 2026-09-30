/** Акция строкой: в каталоге витрины и на странице поставщика. Название
 *  крупно сверху, условие ниже. Раньше мелкая подпись снизу терялась, а
 *  касание по акции ничего не делало. */

import { ChevronRight } from "./icons";

export function PromoRow({
  title,
  detail,
  tone,
  onOpen,
}: {
  title: string;
  detail: string;
  tone: "accent" | "danger";
  /** Есть — акция открывает карточку позиции */
  onOpen?: () => void;
}) {
  const colors =
    tone === "accent"
      ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
      : "bg-[var(--danger)]/10 text-[var(--danger)]";
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="t-title block">{title}</span>
        {detail && (
          <span
            className={`t-desc mt-[2px] block ${
              tone === "accent" ? "opacity-80" : "text-text-secondary"
            }`}
          >
            {detail}
          </span>
        )}
      </span>
      {onOpen && <ChevronRight className="shrink-0" />}
    </>
  );
  const box = `flex w-full items-center gap-2 rounded-2xl px-4 py-3 text-left ${colors}`;
  return (
    <li>
      {onOpen ? (
        <button type="button" onClick={onOpen} className={box}>
          {body}
        </button>
      ) : (
        <div className={box}>{body}</div>
      )}
    </li>
  );
}
