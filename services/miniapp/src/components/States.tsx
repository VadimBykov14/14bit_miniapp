/** Пустое, загрузка и ошибка. Их забывают, а теряют на них больше,
 *  чем на основном потоке. */

import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import { isInsideMax } from "../lib/bridge";

/** Заглушка на время загрузки: по ней пробегает блик, а не мигает вся
 *  карточка — мигание читается как «что-то сломалось». Появляется с
 *  короткой задержкой: быстрый ответ сервера не успевает её показать, и
 *  экран не дёргается туда-обратно. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton rounded-2xl ${className}`} />;
}

/** Несколько заглушек списком — столько, сколько строк обычно на экране. */
export function SkeletonList({
  count = 3,
  className = "h-[88px]",
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div role="status" aria-label="Загрузка" className="flex flex-col gap-3 px-4">
      {Array.from({ length: count }, (_, index) => (
        <Skeleton key={index} className={className} />
      ))}
    </div>
  );
}

/** Пустой экран: что здесь будет и куда идти сейчас.
 *
 *  Без действия человек упирается в сообщение и закрывает приложение —
 *  поэтому кнопка живёт внутри карточки и по одной оси с текстом, а не
 *  отдельной полосой под ней.
 */
export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: { to: string; label: string };
}) {
  return (
    <div className="anim-rise mx-4 flex flex-col items-center rounded-2xl bg-[var(--surface)]
                    px-4 py-8 text-center">
      <p className="t-title">{title}</p>
      {hint && <p className="t-desc mt-2 max-w-[300px] text-text-secondary">{hint}</p>}
      {action && (
        <Link
          to={action.to}
          className="mt-5 flex h-11 w-full max-w-[280px] items-center justify-center rounded-xl
                     bg-[var(--accent)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-foreground)]"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}

export function Failure({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const unauthorized = error instanceof ApiError && error.status === 401;
  return (
    <div className="anim-rise mx-4 rounded-2xl bg-[var(--surface)] px-4 py-8 text-center">
      <p className="t-title">
        {!unauthorized
          ? "Не удалось загрузить"
          : isInsideMax()
            ? "Откройте приложение заново"
            : "Откройте витрину из MAX"}
      </p>
      <p className="t-desc mt-2 text-text-secondary">
        {/* В MAX отказ в подписи — почти всегда прошедшие сутки с запуска:
            приложение долго висело свёрнутым. Помогает только новый запуск. */}
        {!unauthorized
          ? error.message
          : isInsideMax()
            ? "С запуска прошли сутки. Закройте мини-приложение и откройте его снова из чата с ботом."
            : "Приложение узнаёт вас по подписанным данным MAX. В обычном браузере их нет."}
      </p>
      {!unauthorized && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 h-11 rounded-xl bg-[var(--accent)] px-5 text-[15px]/[20px]
                     font-semibold text-[var(--accent-foreground)]"
        >
          Повторить
        </button>
      )}
    </div>
  );
}
