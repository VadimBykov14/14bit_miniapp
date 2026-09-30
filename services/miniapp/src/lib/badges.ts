/** Счётчики на вкладках: непрочитанные уведомления и заявки.
 *
 *  Число приходит сразу, как только что-то случилось: сервер шлёт по
 *  веб-сокету «badges изменились», и значок перечитывается. Опрос остался
 *  страховкой — раз в минуту, пока сокет на связи, и раз в 20 секунд без
 *  него, — плюс чтение при возвращении в приложение и смене раздела.
 */

import { useEffect, useState } from "react";

import { getBadges, type Badges } from "./api";
import { isLive, subscribe } from "./live";

const EVENT = "badges:refresh";
const FAST_MS = 20_000;
const SLOW_MS = 60_000;

/** Действие поменяло счётчик — перечитать сразу, не дожидаясь опроса. */
export const refreshBadges = (): void => {
  window.dispatchEvent(new Event(EVENT));
};

export function useBadges(enabled: boolean, initialUnread: number): Badges {
  const [badges, setBadges] = useState<Badges>({
    unread: initialUnread,
    orders: 0,
    connections: 0,
    last_notification: 0,
  });

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let last = 0;
    // Число из /me уже есть — показываем его, пока не пришёл свежий ответ.
    setBadges((prev) => ({ ...prev, unread: initialUnread }));

    const load = () => {
      last = Date.now();
      getBadges()
        .then((next) => alive && setBadges(next))
        .catch(() => undefined);
    };
    // Фоновый опрос свёрнутого приложения не нужен: число никто не видит.
    // А первое чтение и явные обновления — всегда: вебвью мессенджера
    // бывает «скрытым» в момент запуска, и значок не появлялся вовсе.
    const poll = () => {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - last < (isLive() ? SLOW_MS : FAST_MS) - 1000) return;
      load();
    };

    // Вернулись в приложение — читаем сразу: пока вебвью спал, сокет мог
    // пропустить события.
    const wake = () => {
      if (document.visibilityState !== "hidden") load();
    };

    load();
    const timer = window.setInterval(poll, FAST_MS);
    const unsubscribe = subscribe(["badges"], load);
    window.addEventListener(EVENT, load);
    window.addEventListener("focus", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      alive = false;
      window.clearInterval(timer);
      unsubscribe();
      window.removeEventListener(EVENT, load);
      window.removeEventListener("focus", wake);
      document.removeEventListener("visibilitychange", wake);
    };
    // initialUnread нужен только как стартовое значение.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return badges;
}
