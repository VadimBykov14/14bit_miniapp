import { useCallback, useEffect, useRef, useState } from "react";

import { readCache, writeCache } from "./cache";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** Загрузить заново с индикатором загрузки: «повторить» после ошибки. */
  reload: () => void;
  /** Тихо перечитать: сервер сообщил, что данные изменились. Экран не
   *  мигает скелетоном, а сбой сети не прячет уже показанное. */
  refresh: () => void;
  /** Показать новые данные сразу, без запроса: сервер уже ответил, что
   *  стало. Следом лучше тихо перечитать — refresh. */
  mutate: (next: T) => void;
}

/** Достаточно для наших экранов: загрузка, ошибка, повтор.
 *
 *  С ключом кэша экран сразу получает то, что видел в прошлый раз, и тихо
 *  перечитывает: без скелета на каждом переходе и без прыжка, когда
 *  приезжают данные. Ключ меняется вместе с параметрами — другая витрина
 *  берёт свой кэш, а не чужой.
 */
export function useAsync<T>(
  load: () => Promise<T>,
  deps: unknown[] = [],
  cacheKey?: string,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(() =>
    cacheKey ? (readCache<T>(cacheKey) ?? null) : null,
  );
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(() => !(cacheKey && readCache<T>(cacheKey) !== undefined));
  const [tick, setTick] = useState({ count: 0, quiet: false });
  const shown = useRef(data !== null);
  const lastCount = useRef(0);
  const lastKey = useRef(cacheKey);

  const reload = useCallback(() => setTick((prev) => ({ count: prev.count + 1, quiet: false })), []);
  const refresh = useCallback(() => setTick((prev) => ({ count: prev.count + 1, quiet: true })), []);
  const mutate = useCallback(
    (next: T) => {
      shown.current = true;
      setData(next);
      if (cacheKey) writeCache(cacheKey, next);
    },
    [cacheKey],
  );

  useEffect(() => {
    let cancelled = false;
    // Сменились параметры: показываем кэш нового ключа, если он есть, —
    // иначе скелет, как раньше.
    if (lastKey.current !== cacheKey) {
      lastKey.current = cacheKey;
      const cached = cacheKey ? readCache<T>(cacheKey) : undefined;
      shown.current = cached !== undefined;
      setData(cached ?? null);
    }
    // Тихо — если перечитывает refresh или на экране уже есть что показать
    // из кэша. Смена витрины без кэша грузится со скелетом, как раньше.
    const byRefresh = tick.quiet && tick.count !== lastCount.current;
    const quiet = shown.current && (byRefresh || (cacheKey !== undefined && tick.count === lastCount.current));
    lastCount.current = tick.count;
    if (!quiet) setLoading(true);
    load()
      .then((result) => {
        if (cancelled) return;
        shown.current = true;
        setData(result);
        setError(null);
        if (cacheKey) writeCache(cacheKey, result);
      })
      .catch((err) => {
        if (!cancelled && !quiet) setError(err as Error);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, cacheKey, tick]);

  return { data, error, loading, reload, refresh, mutate };
}
