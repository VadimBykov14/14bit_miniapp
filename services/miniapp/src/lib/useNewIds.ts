/** Какие строки появились после первого показа списка.
 *
 *  Заявка, пришедшая по сокету, пока менеджер смотрит список, коротко
 *  подсвечивается — иначе новая строка просто возникает среди прочих, и
 *  её легко не заметить. Первый показ не подсвечивается: там новое всё.
 */

import { useRef } from "react";

export function useNewIds(ids: number[] | null | undefined, scope = ""): Set<number> {
  const known = useRef<Set<number> | null>(null);
  const fresh = useRef<Set<number>>(new Set());
  const signature = useRef("");
  const lastScope = useRef(scope);

  // Другой список — «В работе» сменили на «Историю»: там новое всё, и
  // подсвечивать нечего.
  if (lastScope.current !== scope) {
    lastScope.current = scope;
    known.current = null;
    signature.current = "";
    fresh.current = new Set();
  }

  if (!ids) return fresh.current;
  const next = ids.join(",");
  if (next === signature.current) return fresh.current;
  signature.current = next;

  if (known.current === null) {
    known.current = new Set(ids);
    fresh.current = new Set();
  } else {
    const seen = known.current;
    fresh.current = new Set(ids.filter((id) => !seen.has(id)));
    ids.forEach((id) => seen.add(id));
  }
  return fresh.current;
}
