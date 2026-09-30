/** Несохранённые правки: уйти с экрана — только спросив.
 *
 *  Раньше «назад» из создания витрины молча выбрасывал всё набранное.
 *  Теперь форма сообщает, что в ней есть правки, и любой уход — своя
 *  стрелка, стрелка MAX, вкладка меню — сначала спрашивает: сохранить,
 *  не сохранять или остаться. Крестик самого MAX, пока правки есть,
 *  переспрашивает силами мессенджера.
 *
 *  Сторож один на приложение: маршрутизатор держит только одного, и так
 *  форма не знает ничего о том, куда и как от неё уходят.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import { useBlocker } from "react-router-dom";

import { Sheet } from "../components/Sheet";
import { haptic, holdClosing } from "./bridge";

interface Entry {
  /** Что правили — «витрину», «предприятие»: для вопроса */
  label: string;
  /** Сохранить; false — не получилось, и уходить нельзя */
  save: () => Promise<boolean>;
}

interface Registry {
  set: (key: string, entry: Entry | null) => void;
}

const Context = createContext<Registry | null>(null);

export function UnsavedProvider({ children }: { children: React.ReactNode }) {
  const entries = useRef(new Map<string, Entry>());
  const [dirty, setDirty] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      entries.current.size > 0 && currentLocation.pathname !== nextLocation.pathname,
  );

  const registry = useMemo<Registry>(
    () => ({
      set(key, entry) {
        const had = entries.current.has(key);
        if (entry) entries.current.set(key, entry);
        else entries.current.delete(key);
        if (had !== Boolean(entry)) setDirty(entries.current.size);
      },
    }),
    [],
  );

  // Пока правки не сохранены, крестик MAX спросит, закрывать ли приложение.
  useEffect(() => (dirty > 0 ? holdClosing() : undefined), [dirty]);

  const open = blocker.state === "blocked";
  useEffect(() => {
    if (open) {
      setError(null);
      haptic("warning");
    }
  }, [open]);

  const labels = [...new Set([...entries.current.values()].map((entry) => entry.label))];

  const stay = () => {
    if (blocker.state === "blocked") blocker.reset();
  };

  async function saveAndGo() {
    setBusy(true);
    setError(null);
    try {
      for (const [key, entry] of [...entries.current.entries()]) {
        const ok = await entry.save();
        if (!ok) {
          setError("Не получилось сохранить — поправьте поля на экране.");
          haptic("error");
          stay();
          return;
        }
        entries.current.delete(key);
      }
      setDirty(entries.current.size);
      haptic("success");
      if (blocker.state === "blocked") blocker.proceed();
    } finally {
      setBusy(false);
    }
  }

  function discard() {
    entries.current.clear();
    setDirty(0);
    if (blocker.state === "blocked") blocker.proceed();
  }

  return (
    <Context.Provider value={registry}>
      {children}
      <Sheet open={open} onClose={stay} label="Сохранить изменения?">
        <div className="flex flex-col gap-3 px-4 pb-2">
          <div>
            <p className="t-subheader">Сохранить изменения?</p>
            <p className="t-desc mt-1 text-text-secondary">
              {labels.length
                ? `Вы изменили ${labels.join(", ")} и не сохранили.`
                : "На экране есть несохранённые правки."}{" "}
              Если уйти без сохранения, они пропадут.
            </p>
          </div>
          {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}
          <button
            type="button"
            disabled={busy}
            onClick={saveAndGo}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
          >
            {busy ? "Сохраняю…" : "Сохранить"}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={discard}
              className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--danger)]"
            >
              Не сохранять
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={stay}
              className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--default-foreground)]"
            >
              Остаться
            </button>
          </div>
        </div>
      </Sheet>
    </Context.Provider>
  );
}

/** Форма сообщает о правках. Возвращает release — снять сторожа сразу,
 *  до перерисовки: после успешной отправки форма уходит сама, и спрашивать
 *  «сохранить?» уже незачем. */
export function useUnsaved(
  key: string,
  dirty: boolean,
  label: string,
  save: () => Promise<boolean>,
): () => void {
  const registry = useContext(Context);
  const latest = useRef(save);
  latest.current = save;

  useEffect(() => {
    if (!registry) return;
    registry.set(key, dirty ? { label, save: () => latest.current() } : null);
    return () => registry.set(key, null);
  }, [registry, key, dirty, label]);

  return useCallback(() => registry?.set(key, null), [registry, key]);
}
