/** Сбой отрисовки не должен оставлять пустой экран.
 *
 *  Без этого ошибка в одном экране снимает всё дерево: пропадает и шапка
 *  со стрелкой «назад», и выйти из экрана нечем — приложение выглядит
 *  зависшим. Здесь человек видит, что случилось, и может уйти назад.
 */

import { Component } from "react";

import { useGoBack } from "./Back";

class Boundary extends Component<
  { children: React.ReactNode; onBack: () => void },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="min-h-dvh bg-[var(--background)] px-4 pt-10">
        <div className="anim-rise rounded-2xl bg-[var(--surface)] px-4 py-8 text-center">
          <p className="t-title">Экран не открылся</p>
          <p className="t-desc mt-2 text-text-secondary">{error.message}</p>
          <div className="mt-5 flex gap-2">
            {/* Назад — шагом по экранам приложения: экран со сбоем уходит
                вместе с этой заглушкой. */}
            <button
              type="button"
              onClick={this.props.onBack}
              className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--default-foreground)]"
            >
              Назад
            </button>
            <button
              type="button"
              onClick={() => window.location.replace("/")}
              className="h-11 flex-1 rounded-xl bg-[var(--accent)] text-[15px]/[20px]
                         font-semibold text-[var(--accent-foreground)]"
            >
              На главную
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export function ErrorBoundary({ children }: { children: React.ReactNode }) {
  const goBack = useGoBack("/");
  return <Boundary onBack={goBack}>{children}</Boundary>;
}
