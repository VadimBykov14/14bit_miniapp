/** «Кабинет базы» ссылкой: без неё поставщик не знал, где взять ключ 1С. */

import { openExternal } from "../lib/bridge";

export function CabinetLink() {
  return (
    <button
      type="button"
      onClick={() => openExternal(`${window.location.origin}/1c`)}
      className="text-[var(--link)] underline underline-offset-2"
    >
      кабинет базы
    </button>
  );
}
