import { useState, type ReactNode } from "react";

import { haptic } from "../lib/bridge";

const CODE = "7532";
const KEY = "max26:access";

function passedBefore(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function AccessCode({ children }: { children: ReactNode }) {
  const [passed, setPassed] = useState(passedBefore);
  const [code, setCode] = useState("");
  const [wrong, setWrong] = useState(false);

  if (passed) return <>{children}</>;

  function submit() {
    if (code !== CODE) {
      haptic("error");
      setWrong(true);
      return;
    }
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      // Хранилище недоступно — пускаем на этот запуск, в следующий спросим снова.
    }
    haptic("success");
    setPassed(true);
  }

  return (
    <div className="min-h-dvh bg-[var(--background)]">
      <header className="flex flex-col gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <h1 className="t-header">Код подтверждения</h1>
        <p className="t-desc text-text-secondary">Введите код, чтобы продолжить.</p>
      </header>

      <form
        className="flex flex-col gap-3 px-4 pt-2 pb-7"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="rounded-2xl bg-[var(--surface)] p-4">
          <input
            value={code}
            inputMode="numeric"
            autoComplete="off"
            autoFocus
            maxLength={4}
            placeholder="••••"
            aria-label="Код подтверждения"
            aria-invalid={wrong}
            enterKeyHint="done"
            onChange={(event) => {
              setCode(event.target.value.replace(/\D/g, "").slice(0, 4));
              setWrong(false);
            }}
            className="h-14 w-full rounded-xl bg-[var(--surface-secondary)] px-3 text-center
                       indent-[0.5em] text-[24px]/[28px] tracking-[0.5em] text-[var(--foreground)]
                       outline-none placeholder:text-[var(--muted)]"
          />
          {wrong && (
            <p className="anim-fade t-desc mt-2 text-[var(--danger)]">
              Код не подходит — проверьте и введите ещё раз.
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={code.length < 4}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          Продолжить
        </button>
      </form>
    </div>
  );
}
