/** Кнопка «назад».
 *
 *  Ведёт на шаг назад по экранам приложения, а не на главную: заявка,
 *  открытая из списка заявок, должна возвращать в список, а не выбрасывать
 *  в витрины. Если шагов нет — приложение открыли сразу по ссылке из
 *  бота, — уходим на запасной адрес, иначе кнопка не сделала бы ничего.
 *
 *  Нажатие видно: стрелка коротко уходит влево, и только потом экран
 *  уезжает. Переход снимает старый экран снимком, поэтому без паузы
 *  движение стрелки не успело бы попасть в кадр.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { haptic } from "../lib/bridge";
import { canGoBack } from "../lib/nav";
import { ChevronRight } from "./icons";

/** Сколько играет стрелка перед переходом: заметно, но не тормозит. */
const NUDGE_MS = 140;

/** Шаг назад по экранам приложения; шагов нет — на запасной адрес. */
export function useGoBack(fallback = "/"): () => void {
  const navigate = useNavigate();
  return useCallback(() => {
    if (canGoBack()) navigate(-1);
    else navigate(fallback, { replace: true });
  }, [navigate, fallback]);
}

/** Сама стрелка — без знания о маршрутах: её же ставит первый вход,
 *  где маршрутизатора ещё нет. */
export function BackButton({ onBack, label = "Назад" }: { onBack: () => void; label?: string }) {
  const [going, setGoing] = useState(false);
  const timer = useRef<number | null>(null);
  const latest = useRef(onBack);
  latest.current = onBack;

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  return (
    <button
      type="button"
      aria-label={label}
      data-going={going}
      onClick={() => {
        if (going) return;
        setGoing(true);
        haptic("tap");
        timer.current = window.setTimeout(() => {
          timer.current = null;
          setGoing(false);
          latest.current();
        }, NUDGE_MS);
      }}
      className="back-btn flex size-11 shrink-0 items-center justify-center"
    >
      <ChevronRight className="rotate-180 text-[var(--link)]" />
    </button>
  );
}

export function Back({
  fallback = "/",
  onBack,
}: {
  fallback?: string;
  /** Свой обработчик: например, спросить про несохранённые правки */
  onBack?: () => void;
}) {
  const goBack = useGoBack(fallback);
  return <BackButton onBack={onBack ?? goBack} />;
}

/** Шапка экрана вглубь, пока он грузится или не загрузился: стрелка
 *  «назад» есть всегда. Раньше экран с ошибкой рисовался без шапки, и уйти
 *  с него было нечем — человек застревал на «Не удалось загрузить». */
export function BackHeader({ fallback = "/", title = "" }: { fallback?: string; title?: string }) {
  return (
    <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
      <Back fallback={fallback} />
      <h1 className="t-subheader min-w-0 flex-1 truncate">{title}</h1>
    </header>
  );
}
