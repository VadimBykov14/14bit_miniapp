/** Корзины — своя у каждой витрины.
 *
 *  Хранятся в localStorage: клиент начал заявку у пекарни, закрыл MAX и
 *  вернулся вечером — набранное на месте. Заглянув к другому поставщику,
 *  он тоже ничего не теряет: раньше переход на другую витрину начинал
 *  заявку заново. Ключ — человек и роль: владелец точки и работник чужого
 *  магазина на одном телефоне не должны видеть корзины друг друга.
 *
 *  Пока корзина лежала, позиции могли раскупить: сверка с остатком — в
 *  ./stockGuard, она и говорит, что поменялось.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

type Lines = Record<number, number>;

interface Stored {
  lines: Lines;
  /** Когда корзину трогали последний раз — старые выбрасываем */
  at: number;
}

interface CartApi {
  linesOf: (storefrontId: number) => Lines;
  countOf: (storefrontId: number) => number;
  setQty: (storefrontId: number, itemId: number, qty: number) => void;
  replace: (storefrontId: number, lines: Lines) => void;
  clear: (storefrontId: number) => void;
}

const PREFIX = "max26:carts:";
// Недельный ритм заявок: корзина старше двух недель — уже не эта заявка.
const TTL = 14 * 24 * 60 * 60 * 1000;
const NONE: Lines = {};

const Context = createContext<CartApi | null>(null);

function read(key: string): Record<number, Stored> {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    const all = raw ? (JSON.parse(raw) as Record<number, Stored>) : {};
    const now = Date.now();
    return Object.fromEntries(
      Object.entries(all).filter(
        ([, cart]) => cart && now - cart.at < TTL && Object.keys(cart.lines ?? {}).length,
      ),
    );
  } catch {
    return {};
  }
}

export function CartProvider({ owner, children }: { owner: string; children: React.ReactNode }) {
  const [carts, setCarts] = useState<Record<number, Stored>>(() => read(owner));

  useEffect(() => {
    try {
      localStorage.setItem(PREFIX + owner, JSON.stringify(carts));
    } catch {
      // приватный режим — корзины живут только в памяти, это допустимо
    }
  }, [owner, carts]);

  const replace = useCallback((storefrontId: number, lines: Lines) => {
    setCarts((prev) => {
      const next = { ...prev };
      if (Object.keys(lines).length) next[storefrontId] = { lines, at: Date.now() };
      else delete next[storefrontId];
      return next;
    });
  }, []);

  const setQty = useCallback((storefrontId: number, itemId: number, qty: number) => {
    setCarts((prev) => {
      const lines = { ...(prev[storefrontId]?.lines ?? {}) };
      if (qty > 0) lines[itemId] = qty;
      else delete lines[itemId];
      const next = { ...prev };
      if (Object.keys(lines).length) next[storefrontId] = { lines, at: Date.now() };
      else delete next[storefrontId];
      return next;
    });
  }, []);

  const clear = useCallback((storefrontId: number) => replace(storefrontId, {}), [replace]);

  const value = useMemo<CartApi>(
    () => ({
      linesOf: (storefrontId) => carts[storefrontId]?.lines ?? NONE,
      countOf: (storefrontId) => Object.keys(carts[storefrontId]?.lines ?? {}).length,
      setQty,
      replace,
      clear,
    }),
    [carts, setQty, replace, clear],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useCart(): CartApi {
  const api = useContext(Context);
  if (!api) throw new Error("useCart вне CartProvider");
  return api;
}
