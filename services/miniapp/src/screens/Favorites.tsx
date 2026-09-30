/** «Избранное» в «Аккаунте»: то, что человек отметил звёздочкой.
 *
 *  У магазина — витрины, товары и контакты поставщиков, у менеджера
 *  поставщика — клиенты. Владелец видит избранных клиентов в «Клиентах»
 *  отбором «Избранные», и в его «Аккаунте» строки нет. Снятая здесь
 *  звёздочка не убирает строку сразу: пока экран открыт, её можно
 *  поставить обратно — случайное касание не стоит поиска заново.
 */

import { Link } from "react-router-dom";

import { Back } from "../components/Back";
import { Brand } from "../components/Brand";
import { ReachButton, WriteButton } from "../components/Contact";
import { FavoriteButton } from "../components/FavoriteButton";
import { ItemTile } from "../components/ItemTile";
import { Empty, Failure, Skeleton } from "../components/States";
import { Toast, useToast } from "../components/Toast";
import { ChevronRight } from "../components/icons";
import {
  getFavorites, isBuyer, type FavoriteKind, type FavoritePerson, type Favorites as Data,
} from "../lib/api";
import { useAsync } from "../lib/useAsync";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <p className="t-desc px-1 text-text-secondary">{title}</p>
      {children}
    </section>
  );
}

/** Человек: звонок и «Написать» — как в «Связаться». */
function Person({
  kind,
  person,
  to,
  onNotice,
}: {
  kind: FavoriteKind;
  person: FavoritePerson;
  /** Карточка человека, если она есть у этой роли */
  to?: string;
  onNotice: (text: string) => void;
}) {
  const head = (
    <span className="min-w-0 flex-1">
      <span className="t-detail block truncate font-semibold">{person.name}</span>
      <span className="t-desc block truncate text-text-secondary">
        {[person.note, person.phone].filter(Boolean).join(" · ") || "контакт не указан"}
      </span>
    </span>
  );
  return (
    <li className="rounded-2xl bg-[var(--surface)] p-3">
      <div className="flex items-center gap-2">
        {to ? (
          <Link to={to} className="flex min-w-0 flex-1 items-center gap-2">
            {head}
            <ChevronRight className="shrink-0 text-[var(--muted)]" />
          </Link>
        ) : (
          head
        )}
        <FavoriteButton kind={kind} id={person.id} name={person.name} onNotice={onNotice} />
      </div>
      {(person.phone_href || person.reachable) && (
        <div className="mt-2 flex gap-2">
          {person.phone_href && (
            <ReachButton kind="phone" href={person.phone_href}>
              Позвонить
            </ReachButton>
          )}
          {person.reachable && (
            <WriteButton
              target={kind === "client" ? { client_id: person.id } : { employee_id: person.id }}
              direct={person.chat_href}
              onNotice={onNotice}
            />
          )}
        </div>
      )}
    </li>
  );
}

function BuyerLists({ data, onNotice }: { data: Data; onNotice: (text: string) => void }) {
  return (
    <>
      {data.storefronts.length > 0 && (
        <Section title="Витрины">
          <ul className="stagger flex flex-col gap-2">
            {data.storefronts.map((front) => (
              <li key={front.id} className="flex items-center gap-2 rounded-2xl bg-[var(--surface)] p-3">
                <Link to={`/s/${front.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                  <Brand
                    name={front.name}
                    logo={front.logo_url}
                    color={front.color}
                    height={44}
                    className="w-11 shrink-0 rounded-xl"
                    short
                  />
                  <span className="min-w-0 flex-1">
                    <span className="t-detail block truncate font-semibold">{front.name}</span>
                    <span className="t-desc block truncate text-text-secondary">{front.supplier}</span>
                  </span>
                </Link>
                <FavoriteButton kind="storefront" id={front.id} name={front.name} onNotice={onNotice} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.items.length > 0 && (
        <Section title="Товары">
          <ul className="stagger flex flex-col gap-2">
            {data.items.map((item) => (
              <li key={item.id} className="flex items-center gap-2 rounded-2xl bg-[var(--surface)] p-3">
                {/* Карточка товара открывается шторкой в своей витрине. */}
                <Link
                  to={`/s/${item.storefront_id}?item=${item.id}`}
                  className="flex min-w-0 flex-1 items-center gap-3"
                >
                  <ItemTile name={item.name} size={44} photo={item.photo_url} />
                  <span className="min-w-0 flex-1">
                    <span className="t-detail block truncate">{item.name}</span>
                    <span className="t-desc block truncate text-text-secondary">
                      {item.storefront_name} · за {item.unit}
                    </span>
                  </span>
                </Link>
                <FavoriteButton kind="item" id={item.id} name={item.name} onNotice={onNotice} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.contacts.length > 0 && (
        <Section title="Контакты поставщиков">
          <ul className="stagger flex flex-col gap-2">
            {data.contacts.map((person) => (
              <Person key={person.id} kind="employee" person={person} onNotice={onNotice} />
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

export default function Favorites({ role }: { role: string | null }) {
  const favorites = useAsync(getFavorites, [], "favorites");
  const toast = useToast();
  const buyer = isBuyer(role);
  const data = favorites.data;
  const empty =
    data &&
    !data.storefronts.length &&
    !data.items.length &&
    !data.contacts.length &&
    !data.clients.length;

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback="/me" />
        <h1 className="t-subheader">Избранное</h1>
      </header>

      {favorites.error ? (
        <Failure error={favorites.error} onRetry={favorites.reload} />
      ) : !data ? (
        <div className="flex flex-col gap-2 px-4">
          <Skeleton className="h-[68px]" />
          <Skeleton className="h-[68px]" />
        </div>
      ) : empty ? (
        <Empty
          title="Пока пусто"
          hint={
            buyer
              ? "Отмечайте звёздочкой витрины, товары и контакты в разделе «Связаться» — они соберутся здесь."
              : "Отмечайте звёздочкой клиентов в заявке или в их карточке — они соберутся здесь."
          }
        />
      ) : (
        <div className="flex flex-col gap-4 px-4">
          {buyer ? (
            <BuyerLists data={data} onNotice={(text) => toast.show(text)} />
          ) : (
            <Section title="Клиенты">
              <ul className="stagger flex flex-col gap-2">
                {data.clients.map((person) => (
                  <Person
                    key={person.id}
                    kind="client"
                    person={person}
                    // Карточка клиента — у владельца, в списке клиентов.
                    to={role === "owner" ? `/owner/clients?client=${person.id}` : undefined}
                    onNotice={(text) => toast.show(text)}
                  />
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}
      <Toast message={toast.message} onClose={toast.hide} />
    </div>
  );
}
