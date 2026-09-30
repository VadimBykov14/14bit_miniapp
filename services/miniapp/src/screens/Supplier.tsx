/** Страница поставщика с полки — для витрины, к которой магазин ещё не
 *  подключён.
 *
 *  Каталог и цены до подключения закрыты: так решил поставщик, открывая
 *  витрину городу. Поэтому здесь то, по чему решают, стоит ли просить
 *  подключение: как возит, до которого часа принимает заявки и сколько
 *  доезжает из обещанного. Акции — только подключённым, в каталоге
 *  (решение пользователя). Данные — с полки: отдельной ручки для страницы
 *  не нужно, и открывается она сразу из кэша.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BottomBar } from "../components/BottomBar";
import { Back, BackHeader } from "../components/Back";
import { Empty, Failure, Skeleton } from "../components/States";
import { HeroChip, StorefrontHero } from "../components/StorefrontHero";
import { Toast, useToast } from "../components/Toast";
import { CalendarIcon, CheckIcon, Clock, LockIcon, ShieldIcon } from "../components/icons";
import { getHome, joinStorefront, type ShelfItem } from "../lib/api";
import { haptic } from "../lib/bridge";
import { deliveryDays, positions } from "../lib/format";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";

/** Цена без копеек: «от 22 ₽» читается, «от 22,00 ₽» — нет. */
const rubles = (price: number): string =>
  `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(price)} ₽`;

/** Кто это, как возит и сколько доезжает — по этому решают, просить ли
 *  подключение. */
function Hero({ row }: { row: ShelfItem }) {
  const where = [
    row.enterprise !== row.name ? row.enterprise : "",
    row.mode === "stock" ? "Со склада" : "Под заказ",
    row.city,
  ].filter(Boolean);
  return (
    <StorefrontHero
      name={row.name}
      logo={row.logo_url}
      color={row.color}
      cover={row.cover_url}
      subtitle={where.join(" · ")}
      chips={
        <>
          {row.is_demo && <HeroChip tone="test">Тестовые данные</HeroChip>}
          {row.mode === "preorder" && row.cutoff_at && (
            <HeroChip icon={<Clock className="size-4" />}>Отсечка {row.cutoff_at}</HeroChip>
          )}
          <HeroChip icon={<CalendarIcon />}>{deliveryDays(row.delivery_days)}</HeroChip>
          {row.shipping_accuracy !== null && (
            <HeroChip icon={<ShieldIcon />}>Довозит {row.shipping_accuracy} %</HeroChip>
          )}
        </>
      }
    />
  );
}

export default function Supplier() {
  const { id } = useParams();
  const storefrontId = Number(id);
  const home = useAsync(getHome, [], "home");
  // Поставщик ответил, пока страница открыта, — внизу сразу «Открыть каталог».
  useLive("storefronts", home.refresh);
  const [busy, setBusy] = useState(false);
  // Ответ на запрос, пока полка не перечитана: «request» или «blocked»
  const [answer, setAnswer] = useState<string | null>(null);
  const toast = useToast();

  if (home.error) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader />
        <Failure error={home.error} onRetry={home.reload} />
      </div>
    );
  }
  if (!home.data) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader />
        <div role="status" aria-label="Загрузка" className="flex flex-col gap-3 px-4">
          <Skeleton className="h-[200px] rounded-3xl" />
          <Skeleton className="h-[76px]" />
        </div>
      </div>
    );
  }

  const row = home.data.storefronts.find((storefront) => storefront.id === storefrontId);
  if (!row) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader />
        <Empty
          title="Витрины нет в городе"
          hint="Поставщик закрыл её для города или удалил. Подключиться можно по его приглашению."
          action={{ to: "/", label: "Открыть витрины города" }}
        />
      </div>
    );
  }

  const asked = row.pending || answer === "request";
  const declined = !row.connected && !asked && answer === "blocked";

  async function ask() {
    setBusy(true);
    try {
      const result = await joinStorefront(storefrontId);
      haptic(result.status === "blocked" ? "warning" : "success");
      setAnswer(result.status);
      // Полка и «Мои витрины» читают этот же кэш: плитка сменит бейдж на «Запрос».
      home.refresh();
    } catch (err) {
      haptic("error");
      toast.show(`Не удалось отправить запрос: ${(err as Error).message}`, {
        tone: "warning",
        duration: 8000,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+16px)]">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back />
      </header>

      <Hero row={row} />

      {row.about && (
        <p className="t-body px-4 pt-4 break-words whitespace-pre-line">{row.about}</p>
      )}

      {/* Подключённой витрине замок ни к чему: внизу уже «Открыть каталог». */}
      {!row.connected && (
        <div className="mx-4 mt-4 flex items-start gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <LockIcon className="shrink-0 text-[var(--muted)]" />
          <div className="min-w-0">
            <p className="t-title">
              {row.items ? `Ассортимент — ${positions(row.items)}` : "Ассортимент ещё не заполнен"}
            </p>
            <p className="t-desc mt-1 text-text-secondary">
              {row.price_from !== null
                ? `Цены от ${rubles(row.price_from)}. Каталог откроется, когда поставщик одобрит запрос.`
                : "Каталог и цены откроются, когда поставщик одобрит запрос."}
            </p>
          </div>
        </div>
      )}

      <BottomBar>
        {row.connected ? (
          <Link
            to={`/s/${row.id}`}
            replace
            className="flex h-[52px] items-center justify-center rounded-xl bg-[var(--accent)]
                       text-[16px]/[20px] font-semibold text-[var(--accent-foreground)]"
          >
            Открыть каталог
          </Link>
        ) : asked ? (
          <div className="anim-fade rounded-xl bg-[var(--success)]/12 px-4 py-3 text-center">
            <p className="flex items-center justify-center gap-2 text-[16px]/[20px] font-semibold">
              <CheckIcon className="text-[var(--success)]" />
              Запрос отправлен
            </p>
            <p className="t-desc mt-1 text-text-secondary">Об одобрении сообщим в MAX</p>
          </div>
        ) : declined ? (
          <div className="anim-fade rounded-xl bg-[var(--default)] px-4 py-3 text-center">
            <p className="text-[16px]/[20px] font-semibold">Поставщик отказал в подключении</p>
            <p className="t-desc mt-1 text-text-secondary">
              Подключиться можно по его приглашению.
            </p>
          </div>
        ) : (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={ask}
              className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                         text-[var(--accent-foreground)] disabled:opacity-60"
            >
              {busy ? "Отправляю…" : "Запросить подключение"}
            </button>
            <p className="t-desc pt-2 text-center text-text-secondary">Об одобрении сообщим в MAX</p>
          </>
        )}
      </BottomBar>

      <Toast message={toast.message} onClose={toast.hide} bottom={140} />
    </div>
  );
}
