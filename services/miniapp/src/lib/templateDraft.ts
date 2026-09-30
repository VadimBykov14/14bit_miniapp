/** Правка шаблона заявки — логика шторки шаблона.
 *
 *  Отдельного запроса «изменить шаблон» у сервера нет, и он не нужен:
 *  шаблон с тем же названием сервер перезаписывает. Новое название — это
 *  новый шаблон; прежний после сохранения удаляем.
 */

import { useState } from "react";

import { deleteTemplate, saveTemplate, type Item, type OrderTemplate } from "./api";
import { haptic } from "./bridge";
import { minOrder } from "./items";

/** Название так, как его сохранит сервер: без пробелов по краям, до 80 знаков. */
const clean = (name: string): string => name.trim().slice(0, 80);

/** Строка шаблона в правке. */
export interface DraftRow {
  item_id: number;
  qty: number;
  name: string;
  unit: string;
  /** Позиция витрины; null — её больше нет в витрине, количество не поменять */
  item: Item | null;
}

export function useTemplateDraft(
  template: OrderTemplate | null,
  items: Item[],
  templates: OrderTemplate[],
) {
  const [name, setName] = useState("");
  const [lines, setLines] = useState<{ item_id: number; qty: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byId = new Map(items.map((item) => [item.id, item]));
  const rows: DraftRow[] = lines.map((line) => {
    const item = byId.get(line.item_id) ?? null;
    const was = template?.lines.find((row) => row.item_id === line.item_id);
    return {
      ...line,
      item,
      name: item?.name ?? was?.name ?? "Позиция",
      unit: item?.unit ?? was?.unit ?? "шт",
    };
  });

  const title = clean(name);
  // Ноль — «убрать из шаблона», как ноль в корзине — «не заказано».
  const kept = lines.filter((line) => line.qty > 0);
  // Одноимённый шаблон сервер перезаписал бы — чужой набор пропал бы молча.
  const taken =
    template !== null &&
    title !== template.name &&
    templates.some((row) => row.id !== template.id && row.name === title);
  const problem = !title
    ? "Назовите шаблон."
    : taken
      ? `Шаблон «${title}» уже есть — выберите другое название.`
      : !kept.length
        ? "Оставьте в шаблоне хотя бы одну позицию."
        : null;

  /** Начать правку с того, что в шаблоне сейчас. */
  function start() {
    if (!template) return;
    setName(template.name);
    setLines(template.lines.map((line) => ({ item_id: line.item_id, qty: line.qty })));
    setError(null);
  }

  const setQty = (itemId: number, qty: number) =>
    setLines((prev) => prev.map((line) => (line.item_id === itemId ? { ...line, qty } : line)));

  const remove = (itemId: number) =>
    setLines((prev) => prev.filter((line) => line.item_id !== itemId));

  /** Новая позиция — сразу с тем, меньше чего не заказать: с упаковкой или
   *  с минимумом поставщика. Ноль значил бы «не в шаблоне». */
  const add = (item: Item) =>
    setLines((prev) => [...prev, { item_id: item.id, qty: minOrder(item) }]);

  /** Что ещё можно добавить: позиции витрины, которых в шаблоне нет. */
  function candidates(query: string): Item[] {
    const inDraft = new Set(lines.map((line) => line.item_id));
    const needle = query.trim().toLowerCase();
    return items.filter(
      (item) => !inDraft.has(item.id) && (!needle || item.name.toLowerCase().includes(needle)),
    );
  }

  /** Сохранить. null — не получилось, причина — в error. */
  async function save(): Promise<{ saved: OrderTemplate; warning?: string } | null> {
    if (!template || problem) return null;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveTemplate({
        storefront_id: template.storefront_id,
        name: title,
        lines: kept,
      });
      let warning: string | undefined;
      if (saved.id !== template.id) {
        try {
          await deleteTemplate(template.id);
        } catch (err) {
          warning =
            `Шаблон сохранён как «${saved.name}», а прежний «${template.name}» удалить не ` +
            `получилось: ${(err as Error).message}. Удалите его крестиком в списке шаблонов.`;
        }
      }
      haptic("success");
      return { saved, warning };
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  return { name, setName, rows, problem, busy, error, start, setQty, remove, add, candidates, save };
}

/** Список шаблонов после сохранения: прежний заменён сохранённым, порядок —
 *  как у сервера, по номеру. */
export function withSaved(
  list: OrderTemplate[],
  previousId: number,
  saved: OrderTemplate,
): OrderTemplate[] {
  return [...list.filter((row) => row.id !== previousId && row.id !== saved.id), saved].sort(
    (a, b) => a.id - b.id,
  );
}
