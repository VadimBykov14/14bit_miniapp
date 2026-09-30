/** Работники магазина: кто заказывает от имени точки.
 *
 *  Как «Сотрудники» у поставщика, только со стороны клиента. Владелец
 *  точки зовёт работника ссылкой — тот сам открывает её в MAX, и его
 *  личность подтверждает мессенджер. Убрать работника может только
 *  владелец; работник видит команду, но не меняет её.
 */

import { useState } from "react";

import { Back } from "../components/Back";
import { InviteLink } from "../components/InviteLink";
import { Empty, Failure, SkeletonList } from "../components/States";
import { createWorkerInvite, getShopWorkers, removeWorker, type ShopPerson } from "../lib/api";
import { haptic } from "../lib/bridge";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";

function Invite() {
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const invite = await createWorkerInvite();
      setLink(invite.link);
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 px-4">
      <button
        type="button"
        disabled={busy}
        onClick={create}
        className="h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                   text-[var(--accent-foreground)] disabled:opacity-60"
      >
        {busy ? "Создаю ссылку…" : "Пригласить работника"}
      </button>
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      {link && (
        <InviteLink key={link} link={link} shareText="Приглашение в команду магазина — откройте ссылку в MAX">
          Одна ссылка — один работник. Ссылка откроет чат с ботом, бот пришлёт приглашение с
          кнопкой «Принять приглашение» — по ней работник укажет телефон и график и сможет
          заказывать от имени магазина.
        </InviteLink>
      )}
    </div>
  );
}

function Row({
  person,
  canRemove,
  onRemoved,
  onError,
}: {
  person: ShopPerson;
  canRemove: boolean;
  onRemoved: () => void;
  onError: (text: string | null) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <li className="flex items-center gap-3 border-b border-[var(--separator)] px-4 py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="t-body truncate">{person.name}</p>
        <p className="t-desc text-text-secondary">
          {[
            person.role === "client" ? "владелец" : "работник",
            person.role === "worker" ? person.hours || "график не указан" : "",
            person.phone,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {person.on_shift !== null && (
        <span
          className={`t-label shrink-0 rounded-lg px-2 py-1 transition-colors ${
            person.on_shift
              ? "bg-[var(--success)]/18 text-[var(--success)]"
              : "bg-[var(--default)] text-[var(--muted)]"
          }`}
        >
          {person.on_shift ? "на месте" : "не на месте"}
        </span>
      )}
      {canRemove && person.worker_id !== null && (
        <button
          type="button"
          disabled={busy}
          aria-label={confirming ? "Подтвердить: убрать работника" : "Убрать работника"}
          onBlur={() => setConfirming(false)}
          onClick={async () => {
            if (!confirming) {
              setConfirming(true);
              return;
            }
            setBusy(true);
            onError(null);
            try {
              await removeWorker(person.worker_id!);
              haptic("success");
              onRemoved();
            } catch (err) {
              haptic("error");
              onError(`«${person.name}» не убран: ${(err as Error).message}`);
            } finally {
              setBusy(false);
              setConfirming(false);
            }
          }}
          className={`h-9 shrink-0 rounded-xl px-3 text-[13px]/[16px] font-semibold ${
            confirming ? "bg-[var(--danger)] text-[var(--danger-foreground)]" : "bg-[var(--default)] text-[var(--danger)]"
          }`}
        >
          {busy ? "…" : confirming ? "Точно?" : "Убрать"}
        </button>
      )}
    </li>
  );
}

export default function ShopWorkers({ owner, shop }: { owner: boolean; shop: string }) {
  const people = useAsync(getShopWorkers, [], "shop:workers");
  useLive("workers", people.refresh);
  const workers = (people.data ?? []).filter((person) => person.role === "worker");
  const [removeError, setRemoveError] = useState<string | null>(null);

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback="/me" />
        <div className="min-w-0 flex-1">
          <h1 className="t-subheader truncate">Работники</h1>
          <p className="t-desc truncate text-text-secondary">{shop}</p>
        </div>
      </header>

      {owner && <Invite />}

      {people.error ? (
        <Failure error={people.error} onRetry={people.reload} />
      ) : !people.data ? (
        <SkeletonList count={2} className="h-[64px]" />
      ) : (
        <>
          {removeError && (
            <p className="anim-fade t-desc mx-4 mb-2 text-[var(--danger)]">{removeError}</p>
          )}
          <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
            {people.data.map((person) => (
              <Row
                key={person.worker_id ?? "owner"}
                person={person}
                canRemove={owner}
                onRemoved={people.refresh}
                onError={setRemoveError}
              />
            ))}
          </ul>
          {!workers.length && owner && (
            <div className="mt-3">
              <Empty
                title="Работников пока нет"
                hint="Работник заказывает у ваших поставщиков и принимает товар, но не приглашает людей и не меняет сведения о магазине."
              />
            </div>
          )}
          <p className="t-desc mx-4 mt-3 text-text-secondary">
            Поставщик видит, кто из вас сейчас на месте, — по графику, который каждый указывает у
            себя в «Аккаунте». Заявку ведёт тот, кто её оформил: ему и придут подтверждение и
            отгрузка.
          </p>
        </>
      )}
    </div>
  );
}
