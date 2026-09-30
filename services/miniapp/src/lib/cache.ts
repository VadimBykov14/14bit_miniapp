/** Кэш ответов: экран открывается сразу с тем, что видели в прошлый раз.
 *
 *  Раньше каждая вкладка при каждом переходе начинала со скелета и
 *  дёргалась, когда приезжали данные. Теперь показываем последнее
 *  известное и тихо перечитываем: свежие данные подменяют старые без
 *  мигания, а сокет всё равно сообщает об изменениях.
 *
 *  Живёт в памяти и в sessionStorage: смена роли перезагружает страницу,
 *  и без хранилища после неё снова были бы скелеты. Ключ включает
 *  человека и роль — у владельца пекарни, который ещё и клиент базы, два
 *  разных списка заявок.
 */

import { getActiveRole } from "./api";

const PREFIX = "max26:cache:";
/** Крупные ответы в хранилище не кладём: квота маленькая, а память и так есть. */
const STORE_LIMIT = 150_000;

const memory = new Map<string, unknown>();

function scope(key: string): string {
  const user = window.WebApp?.initDataUnsafe?.user?.id ?? "dev";
  return `${user}:${getActiveRole() ?? "-"}:${key}`;
}

export function readCache<T>(key: string): T | undefined {
  const full = scope(key);
  if (memory.has(full)) return memory.get(full) as T;
  try {
    const raw = sessionStorage.getItem(PREFIX + full);
    if (!raw) return undefined;
    const value = JSON.parse(raw) as T;
    memory.set(full, value);
    return value;
  } catch {
    return undefined;
  }
}

export function writeCache(key: string, value: unknown): void {
  const full = scope(key);
  memory.set(full, value);
  try {
    const raw = JSON.stringify(value);
    if (raw.length <= STORE_LIMIT) sessionStorage.setItem(PREFIX + full, raw);
    else sessionStorage.removeItem(PREFIX + full);
  } catch {
    // квота или приватный режим — хватит памяти
  }
}

/** Забыть всё: смена человека или роли, сброс аккаунта. */
export function clearCache(): void {
  memory.clear();
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(PREFIX)) sessionStorage.removeItem(key);
    }
  } catch {
    // нечего чистить
  }
}
