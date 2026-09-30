/** Широкий экран: боковое меню вместо нижнего, шторки — окнами по центру. */

import { useEffect, useState } from "react";

export const WIDE = "(min-width: 960px)";

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}
