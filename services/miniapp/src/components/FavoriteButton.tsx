/** Звёздочка «в избранное» — одна на витрину, товар, сотрудника и клиента.
 *
 *  Без подписи: звезда — знакомый знак, а подпись для озвучки называет,
 *  что именно добавится. Ошибку показывает экран, где стоит звёздочка, —
 *  своей плашки у маленькой кнопки нет.
 */

import { useState } from "react";

import type { FavoriteKind } from "../lib/api";
import { haptic } from "../lib/bridge";
import { toggleFavorite, useIsFavorite } from "../lib/favorites";
import { StarIcon } from "./icons";

export function FavoriteButton({
  kind,
  id,
  name,
  onNotice,
  className = "",
  onColor = false,
}: {
  kind: FavoriteKind;
  id: number;
  /** Что отмечаем — для озвучки: «Добавить «Пекарня» в избранное» */
  name: string;
  onNotice: (text: string) => void;
  className?: string;
  /** На цветной карточке витрины: белая звезда, серая там терялась */
  onColor?: boolean;
}) {
  const on = useIsFavorite(kind, id);
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? `Убрать «${name}» из избранного` : `Добавить «${name}» в избранное`}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        haptic("select");
        try {
          await toggleFavorite(kind, id, !on);
        } catch (err) {
          haptic("error");
          onNotice((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
      className={`flex size-10 shrink-0 items-center justify-center rounded-full transition-colors ${
        onColor
          ? `bg-white/20 ${on ? "text-white" : "text-white/85"}`
          : on
            ? "text-[var(--warning)]"
            : "text-[var(--muted)]"
      } ${className}`}
    >
      <StarIcon filled={on} className="size-[22px]" />
    </button>
  );
}
