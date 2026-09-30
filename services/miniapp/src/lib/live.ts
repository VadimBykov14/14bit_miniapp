/** Живые обновления по веб-сокету.
 *
 *  Раньше экран узнавал о новой заявке или изменившемся остатке опросом
 *  раз в 20 секунд, а многие экраны — только после перехода. Теперь сервер
 *  сам говорит «изменилось»: `orders`, `order:57`, `storefront:3`, `badges`,
 *  `feed`, `connections`, — и открытый экран перечитывает своё сразу.
 *
 *  По сокету идут только названия тем. Данные экран берёт обычным
 *  запросом, с проверкой прав, поэтому сокет ничего не раскрывает.
 *
 *  Связь рвётся — в мобильной сети это обычное дело. Переподключаемся с
 *  нарастающей паузой, а после восстановления просим все экраны
 *  перечитать данные: пока связи не было, события могли пройти мимо.
 */

import { useEffect, useRef } from "react";

import { authInitData } from "./api";

type Handler = () => void;

/** Особая тема: связь восстановилась — перечитать всё. */
const RESYNC = "*";

const listeners = new Map<string, Set<Handler>>();
let socket: WebSocket | null = null;
let started = false;
let attempt = 0;
let everReady = false;
let reconnectTimer: number | undefined;
let watchdog: number | undefined;
let lastSeen = 0;

/** Для разработки вне MAX: адрес боевого сокета, если вёрстка открыта
 *  с локального сервера, который сам сокет не проксирует. */
const devUrl = import.meta.env.DEV
  ? (import.meta.env.VITE_LIVE_URL as string | undefined)
  : undefined;

function address(): string {
  if (devUrl) return devUrl;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/live`;
}

function emit(topics: string[]): void {
  // Один обработчик на сообщение, даже если он подписан на несколько тем
  // из него: экран перечитывается один раз, а не три.
  const due = new Set<Handler>();
  for (const topic of topics) {
    if (topic === RESYNC) {
      for (const set of listeners.values()) set.forEach((handler) => due.add(handler));
      continue;
    }
    listeners.get(topic)?.forEach((handler) => due.add(handler));
  }
  due.forEach((handler) => {
    try {
      handler();
    } catch {
      // сбой одного экрана не должен глушить остальные
    }
  });
}

function schedule(): void {
  window.clearTimeout(reconnectTimer);
  // 1, 2, 4, 8 … 30 секунд: сервер на перезапуске не заваливаем попытками.
  const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
  attempt += 1;
  reconnectTimer = window.setTimeout(connect, delay);
}

function connect(): void {
  window.clearTimeout(reconnectTimer);
  const init = authInitData();
  if (!init || typeof WebSocket === "undefined") return;
  if (socket && socket.readyState <= WebSocket.OPEN) return;

  let ws: WebSocket;
  try {
    ws = new WebSocket(address());
  } catch {
    schedule();
    return;
  }
  socket = ws;

  ws.onopen = () => {
    ws.send(JSON.stringify({ init_data: init }));
  };
  ws.onmessage = (event) => {
    lastSeen = Date.now();
    let message: { type?: string; topics?: string[] };
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (message.type === "ready") {
      attempt = 0;
      // Первое подключение — экраны и так только что загрузились.
      if (everReady) emit([RESYNC]);
      everReady = true;
    } else if (message.type === "changed" && message.topics) {
      emit(message.topics);
    }
  };
  ws.onclose = (event) => {
    if (socket === ws) socket = null;
    // 4401 — подпись не принята: с той же подписью пробовать бессмысленно.
    if (event.code === 4401) return;
    schedule();
  };
  ws.onerror = () => {
    try {
      ws.close();
    } catch {
      // уже закрыт
    }
  };
}

/** Сервер пингует раз в 25 секунд. Тишина дольше минуты — соединение
 *  умерло молча (мобильная сеть так умеет): переподключаемся сами. */
function watch(): void {
  window.clearInterval(watchdog);
  watchdog = window.setInterval(() => {
    if (document.visibilityState === "hidden") return;
    if (socket && socket.readyState === WebSocket.OPEN && Date.now() - lastSeen > 60_000) {
      socket.close();
    }
  }, 15_000);
}

/** Запускается один раз, когда человек вошёл в приложение. */
export function startLive(): void {
  if (started) return;
  started = true;
  lastSeen = Date.now();
  connect();
  watch();
  // Вернулись в приложение — сокет мог умереть, пока вебвью спал. Если
  // приложение было скрыто дольше минуты-другой, сокет, даже «открытый»,
  // мог пропустить события: переподключаемся, и после «ready» все экраны
  // перечитают своё — остатки в витрине не висят старыми до следующего
  // события.
  let hiddenAt = 0;
  const wake = () => {
    if (document.visibilityState === "hidden") {
      hiddenAt = hiddenAt || Date.now();
      return;
    }
    const slept = hiddenAt > 0 && Date.now() - hiddenAt > 20_000;
    hiddenAt = 0;
    if (!socket) {
      attempt = 0;
      connect();
    } else if (slept) {
      attempt = 0;
      socket.close();
    }
  };
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
  window.addEventListener("focus", wake);
}

/** Сокет на связи — опрос можно делать реже. */
export const isLive = (): boolean => Boolean(socket && socket.readyState === WebSocket.OPEN);

export function subscribe(topics: string[], handler: Handler): () => void {
  for (const topic of topics) {
    if (!listeners.has(topic)) listeners.set(topic, new Set());
    listeners.get(topic)!.add(handler);
  }
  return () => {
    for (const topic of topics) {
      const set = listeners.get(topic);
      set?.delete(handler);
      if (set && !set.size) listeners.delete(topic);
    }
  };
}

/** Перечитать данные экрана, когда сервер скажет, что они изменились.
 *  Обработчик берётся свежий, подписка — одна на время жизни экрана. */
export function useLive(topics: string | string[] | null, handler: Handler): void {
  const latest = useRef(handler);
  latest.current = handler;
  const key = topics === null ? "" : Array.isArray(topics) ? topics.join("|") : topics;

  useEffect(() => {
    if (!key) return;
    return subscribe(key.split("|"), () => latest.current());
  }, [key]);
}
