/** Пометка «Тестовые данные» — требование брифа (стр. 7 п. 10, стр. 18 п. 4):
 *  демо-контент стенда не должен выдавать себя за настоящий. */
export function TestBadge({ className = "", squeeze = false }: {
  className?: string;
  /** Рядом с названием: на узком телефоне — «Тест», иначе обрезалось бы название */
  squeeze?: boolean;
}) {
  return (
    <span
      className={`t-label shrink-0 rounded-lg bg-[var(--test-soft)] px-2 py-[2px] text-[var(--test)]
                  ${className}`}
    >
      {squeeze ? (
        <>
          <span className="max-[379px]:hidden">Тестовые данные</span>
          <span className="hidden max-[379px]:inline">Тест</span>
        </>
      ) : (
        "Тестовые данные"
      )}
    </span>
  );
}
