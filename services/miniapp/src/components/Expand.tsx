/** Раскрывающийся блок: выезжает по высоте и так же уезжает.
 *
 *  Раньше панель появлялась и пропадала целиком, и всё, что ниже, прыгало
 *  на её высоту. Здесь высота меняется плавно (сетка 0fr → 1fr), а
 *  содержимое живёт в DOM, только пока блок открыт или закрывается, —
 *  закрытая форма не держит ни состояния, ни фокуса.
 */

import { useEffect, useState } from "react";

const CLOSE_MS = 320;

export function Expand({
  open,
  className = "",
  children,
}: {
  open: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      // Два кадра: сначала блок встаёт в DOM закрытым, потом раскрывается —
      // иначе браузер сразу нарисует конечное состояние без перехода.
      let second = 0;
      const first = requestAnimationFrame(() => {
        second = requestAnimationFrame(() => setShown(true));
      });
      return () => {
        cancelAnimationFrame(first);
        cancelAnimationFrame(second);
      };
    }
    setShown(false);
    const timer = window.setTimeout(() => setMounted(false), CLOSE_MS);
    return () => window.clearTimeout(timer);
  }, [open]);

  if (!mounted) return null;
  return (
    <div className="expand" data-open={shown}>
      <div className={className}>{children}</div>
    </div>
  );
}
