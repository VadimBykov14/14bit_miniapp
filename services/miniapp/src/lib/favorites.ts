/** Избранное на всё приложение.
 *
 *  Звёздочки стоят в каталоге, в карточке товара, в «Связаться» и в заявке,
 *  а список — в «Аккаунте»; владелец поставщика видит своих избранных
 *  клиентов отбором в «Клиентах». Отметки одни на всех: отметил витрину в
 *  каталоге — она сразу есть в «Избранном», без перезагрузки. Отметка на
 *  другом устройстве человека приходит по сокету.
 */

import { useEffect, useSyncExternalStore } from "react";

import { getFavoriteIds, setFavorite, type FavoriteIds, type FavoriteKind } from "./api";
import { subscribe as onLive } from "./live";

let ids: FavoriteIds | null = null;
let loading: Promise<void> | null = null;
let watching = false;
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((listener) => listener());

function load(force = false): Promise<void> {
  if (loading && !force) return loading;
  loading = getFavoriteIds()
    .then((next) => {
      ids = next;
      emit();
    })
    .catch(() => {
      // Звёздочки просто не загорятся, а следующий экран спросит снова;
      // отметить всё равно можно — ответ сервера принесёт свежий список.
      loading = null;
    });
  return loading;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!watching) {
    watching = true;
    onLive(["favorites"], () => void load(true));
  }
  return () => listeners.delete(listener);
}

function changed(kind: FavoriteKind, id: number, on: boolean): FavoriteIds {
  const base: FavoriteIds = ids ?? { storefront: [], item: [], employee: [], client: [] };
  const rest = base[kind].filter((value) => value !== id);
  return { ...base, [kind]: on ? [...rest, id] : rest };
}

/** Отметить или снять. Звёздочка меняется сразу, а не после ответа сервера;
 *  не вышло — возвращается как была, и ошибка уходит вызвавшему. */
export async function toggleFavorite(kind: FavoriteKind, id: number, on: boolean): Promise<void> {
  const before = ids;
  ids = changed(kind, id, on);
  emit();
  try {
    ids = await setFavorite(kind, id, on);
    emit();
  } catch (err) {
    ids = before;
    emit();
    throw err;
  }
}

/** Отмечено ли звёздочкой. Первый вызов подгружает отметки. */
export function useIsFavorite(kind: FavoriteKind, id: number): boolean {
  const current = useSyncExternalStore(subscribe, () => ids);
  useEffect(() => {
    void load();
  }, []);
  return Boolean(current?.[kind]?.includes(id));
}

/** Все отметки одного вида — для отбора «Избранные» в списке. Пока
 *  отметки не загрузились — null, а не пустой список: иначе отбор успел бы
 *  сказать «избранных нет». */
export function useFavoriteIds(kind: FavoriteKind): number[] | null {
  const current = useSyncExternalStore(subscribe, () => ids);
  useEffect(() => {
    void load();
  }, []);
  return current ? current[kind] : null;
}
