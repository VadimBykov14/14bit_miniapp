/** «Пригласить клиента ссылкой» — в «Подключениях» (экран 21) и в
 *  «Клиентах» (экран 19).
 *
 *  Сначала — в какую витрину (просьба пользователя), как в «Кто запускал
 *  бота»: раньше ссылка без витрины подключала сразу ко всем. Витрина одна —
 *  выбирать нечего. Ссылкой зовут чаще, чем из списка бота, поэтому она —
 *  главная кнопка, а список — вторая, и только в «Подключениях».
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { createInvite, getOwnerStorefronts } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { InviteLink } from "./InviteLink";

export function ClientInvite({ audience = false }: {
  /** Второй кнопкой — «Пригласить из тех, кто запускал бота» */
  audience?: boolean;
}) {
  // Список нужен к первому нажатию, а не после него.
  const storefronts = useAsync(getOwnerStorefronts, [], "owner:storefronts");
  // Готовая ссылка и витрина, в которую она зовёт: подпись её называет.
  const [invite, setInvite] = useState<{ link: string; storefront: string } | null>(null);
  const [picking, setPicking] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function inviteTo(storefront: { id: number; name: string }) {
    setPicking(false);
    setInviting(true);
    setError(null);
    try {
      const created = await createInvite("client", storefront.id);
      setInvite({ link: created.link, storefront: storefront.name });
    } catch (err) {
      setError(`Ссылка не создалась: ${(err as Error).message}`);
    } finally {
      setInviting(false);
    }
  }

  function start() {
    setError(null);
    const rows = storefronts.data;
    if (!rows) {
      setError(`Витрины не загрузились: ${storefronts.error?.message ?? "нет ответа"}`);
      storefronts.reload();
    } else if (!rows.length) {
      setError("Сначала создайте витрину — приглашать пока некуда.");
    } else if (rows.length === 1) {
      void inviteTo(rows[0]);
    } else {
      setPicking(true);
    }
  }

  if (picking && storefronts.data) {
    // Выбор встаёт на место кнопок: вторая, того же цвета, что и варианты,
    // читалась бы как ещё одна витрина.
    return (
      <div className="anim-drop flex flex-col gap-2">
        <p className="t-desc text-text-secondary">В какую витрину пригласить клиента?</p>
        {storefronts.data.map((storefront) => (
          <button
            key={storefront.id}
            type="button"
            onClick={() => inviteTo(storefront)}
            className="h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                       font-semibold text-[var(--accent-soft-foreground)]"
          >
            {storefront.name}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setPicking(false)}
          className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                     font-semibold text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        disabled={inviting || (!storefronts.data && storefronts.loading)}
        onClick={start}
        className="h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                   text-[var(--accent-foreground)] disabled:opacity-60"
      >
        {inviting ? "Создаю ссылку…" : "Пригласить клиента ссылкой"}
      </button>
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      {invite && (
        <InviteLink
          key={invite.link}
          link={invite.link}
          shareText={`Приглашение в витрину «${invite.storefront}» — откройте ссылку в MAX`}
        >
          Одна ссылка — одно подключение. Ссылка откроет чат с ботом, бот пришлёт приглашение
          с кнопкой «Принять приглашение» — по ней клиент окажется в витрине «{invite.storefront}».
        </InviteLink>
      )}
      {audience && (
        <Link
          to="/owner/audience"
          className="mt-2 flex h-11 items-center justify-center rounded-xl bg-[var(--accent-soft)]
                     text-[15px]/[20px] font-semibold text-[var(--accent-soft-foreground)]"
        >
          Пригласить из тех, кто запускал бота
        </Link>
      )}
    </>
  );
}
