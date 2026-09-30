/** «Связаться»: кнопки только переводят — в набор номера или в чат MAX.
 *
 *  Сообщений от имени человека они не шлют: каждое нажатие будило бы
 *  другую сторону уведомлением «перезвоните». «Написать» открывает профиль
 *  по нику, а без ника — присылает карточку контакта в чат с ботом.
 */

import { useState } from "react";

import { openMaxLink } from "../lib/bridge";
import { writeTo, type WriteTarget } from "../lib/reach";
import { FavoriteButton } from "./FavoriteButton";
import { ChatIcon, PhoneIcon } from "./icons";

export type ReachKind = "phone" | "max";

const BUTTON =
  "flex h-11 min-w-0 flex-1 items-center justify-center gap-2 rounded-xl px-3 " +
  "text-[15px]/[20px] font-semibold";
const ACTIVE = "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]";
/** «Написать» — главная кнопка связи: в MAX пишут чаще, чем звонят, и
 *  бледная кнопка рядом с «Позвонить» терялась. */
const PRIMARY = "bg-[var(--accent)] text-[var(--accent-foreground)]";

export function ReachButton({
  kind,
  href,
  children,
}: {
  kind: ReachKind;
  href: string;
  children: React.ReactNode;
}) {
  const icon = kind === "phone" ? <PhoneIcon /> : <ChatIcon />;
  if (kind === "phone") {
    // Ссылка, а не window.location: набор номера по tel: вебвью отдают
    // системе только на нажатие настоящей ссылки.
    return (
      <a href={href} className={`${BUTTON} ${ACTIVE}`}>
        {icon}
        <span className="truncate">{children}</span>
      </a>
    );
  }
  return (
    <button type="button" onClick={() => openMaxLink(href)} className={`${BUTTON} ${ACTIVE}`}>
      {icon}
      <span className="truncate">{children}</span>
    </button>
  );
}

/** «Написать» — всегда рабочая: по нику сразу в профиль, без ника —
 *  карточка контакта в чате с ботом. */
export function WriteButton({
  target,
  direct,
  onNotice,
  children = "Написать",
}: {
  target: WriteTarget;
  direct: string;
  onNotice: (text: string) => void;
  children?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await writeTo(target, direct, onNotice);
        } finally {
          setBusy(false);
        }
      }}
      className={`${BUTTON} ${PRIMARY} disabled:opacity-60`}
    >
      <ChatIcon />
      <span className="truncate">{busy ? "Открываю…" : children}</span>
    </button>
  );
}

/** Кнопка, которой некуда вести: остаётся на месте и объясняет почему —
 *  пропавшая кнопка выглядит как ошибка приложения. */
export function ReachDisabled({ children }: { children: React.ReactNode }) {
  return (
    <button type="button" disabled className={`${BUTTON} bg-[var(--default)] text-[var(--muted)]`}>
      <ChatIcon />
      <span className="truncate">{children}</span>
    </button>
  );
}

/** Карточка клиента в заявке у поставщика: кто оформил, куда везти и как
 *  связаться. «Написать» есть всегда — ник у клиента не обязателен. */
export function ClientContact({
  clientId,
  workerId = null,
  reachable = true,
  name,
  author,
  phoneHref,
  chatHref,
  address,
  comment,
  onNotice,
}: {
  clientId: number;
  /** Заявку оформил работник магазина — пишем ему, а не владельцу точки */
  workerId?: number | null;
  /** Разрешил ли писать себе в MAX */
  reachable?: boolean;
  name: string;
  author: string;
  phoneHref: string;
  chatHref: string;
  address: string;
  comment: string;
  onNotice: (text: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl bg-[var(--surface)] p-4">
      <div className="-my-2 -mr-2 flex items-center justify-between gap-2">
        <p className="t-title">Клиент</p>
        <FavoriteButton kind="client" id={clientId} name={name} onNotice={onNotice} />
      </div>
      {/* Сначала магазин, затем кто оформил. Имя с фамилией — одним блоком:
          не влезает в строку целиком — переносится целиком. Телефон не
          пишем: для звонка есть кнопка «Позвонить». */}
      <p className="t-desc text-text-secondary">
        {name}
        {author && (
          <>
            , <span className="inline-block">{author}</span>
          </>
        )}
      </p>
      {address && (
        <p className="t-detail">
          <span className="t-label block text-text-secondary">Адрес доставки</span>
          {address}
        </p>
      )}
      {comment && (
        <p className="t-detail">
          <span className="t-label block text-text-secondary">Комментарий клиента</span>
          {comment}
        </p>
      )}
      {(phoneHref || reachable) && (
        <div className="mt-1 flex gap-2">
          {phoneHref && (
            <ReachButton kind="phone" href={phoneHref}>
              Позвонить
            </ReachButton>
          )}
          {reachable && (
            <WriteButton
              target={workerId ? { worker_id: workerId } : { client_id: clientId }}
              direct={chatHref}
              onNotice={onNotice}
            />
          )}
        </div>
      )}
    </div>
  );
}
