/** Подключение витрины к 1С: тестовая база по ключу или своя база.
 *
 *  Своя база — адрес публикации, служебный пользователь и пароль. Пароль
 *  уходит на сервер и обратно не возвращается: поле пустое, а подпись
 *  говорит, что он сохранён.
 *
 *  Реквизиты заказа — организация, склад, вид цен, валюта, контрагент —
 *  в 1С ссылки, поэтому их не вписывают, а выбирают из списков, которые
 *  «Проверить подключение» прочитает из самой базы. Без них «Заказ
 *  клиента» в УТ не проведётся.
 */

import { useState } from "react";

import { CabinetLink } from "../components/CabinetLink";
import { Chip } from "../components/Chip";
import { Segmented } from "../components/Segmented";
import { SwitchRow } from "../components/SwitchRow";
import {
  getOneCLists, updateStorefront, type OneCLists, type OneCOption, type StorefrontSettings,
} from "../lib/api";
import { haptic } from "../lib/bridge";

/** Версии конфигурации — те же, что знает сервер (app/onec/settings.py). */
const PRESETS = [
  { value: "ut11_4", label: "УТ 11.4, КА 2.4, ERP 2.4" },
  { value: "ut11_5", label: "УТ 11.5, КА 2.5, ERP 2.5 — до 11.5.7" },
  { value: "ut11_5_7", label: "УТ 11.5.7 и новее, ERP 2.5.7 и новее" },
];

/** Что выбирается из справочников и откуда берутся варианты. */
const FIELDS: { key: string; list: keyof OneCLists; label: string; optional?: boolean }[] = [
  { key: "organization", list: "organizations", label: "Организация" },
  { key: "warehouse", list: "warehouses", label: "Склад — отсюда остатки и резерв" },
  { key: "price_kind", list: "price_kinds", label: "Вид цен" },
  { key: "currency", list: "currencies", label: "Валюта" },
  { key: "contractor", list: "contractors", label: "Контрагент по умолчанию" },
  { key: "agreement", list: "agreements", label: "Соглашение", optional: true },
];

const input = `h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
               text-[var(--foreground)] outline-none placeholder:text-[var(--muted)]`;

function describe(storefront: StorefrontSettings): string {
  switch (storefront.onec_mode) {
    case "own":
      return `своя база 1С · ${storefront.onec_url}`;
    case "key":
      return `тестовая база «${storefront.onec_base}»`;
    case "stand":
      return "база стенда (демо)";
    default:
      return "вручную — позиции заводятся в приложении";
  }
}

export function OnecConnection({
  storefront,
  onSaved,
}: {
  storefront: StorefrontSettings;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"key" | "own">(storefront.onec_mode === "own" ? "own" : "key");
  const [key, setKey] = useState("");
  const [url, setUrl] = useState(storefront.onec_url);
  const [user, setUser] = useState(storefront.onec_user);
  const [password, setPassword] = useState("");
  const [preset, setPreset] = useState(storefront.onec_preset || "ut11_4");
  const [reserve, setReserve] = useState(storefront.onec_reserve_now);
  const [lists, setLists] = useState<OneCLists | null>(null);
  const [chosen, setChosen] = useState<Record<string, OneCOption>>(() =>
    Object.fromEntries(
      Object.entries(storefront.onec_refs).map(([field, ref]) => [field, { key: ref.key, name: ref.name }]),
    ),
  );
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const linked = storefront.onec_mode !== "";

  if (!open) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <span className="t-detail min-w-0">
            Источник данных
            <span className="t-label block break-all text-text-secondary">{describe(storefront)}</span>
          </span>
          <Chip onClick={() => setOpen(true)}>{linked ? "Настроить 1С" : "Подключить 1С"}</Chip>
        </div>
        {storefront.onec_missing.length > 0 && (
          <p className="t-label text-[var(--warning-soft-foreground)]">
            Заказы не проведутся в 1С: не выбраны {storefront.onec_missing.join(", ")}.
          </p>
        )}
      </div>
    );
  }

  /** Подключение в том виде, в каком его ввели, — для проверки и сохранения. */
  const connection = () =>
    kind === "own"
      ? { onec_url: url.trim(), onec_user: user.trim(), onec_password: password || undefined }
      : key.trim()
        ? { onec_key: key.trim() }
        : {};

  async function check() {
    setBusy("check");
    setError(null);
    try {
      setLists(await getOneCLists(storefront.id, { ...connection(), onec_preset: preset }));
      haptic("success");
    } catch (err) {
      haptic("error");
      setLists(null);
      setError(`Подключиться не удалось: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function save(off = false) {
    setBusy("save");
    setError(null);
    try {
      await updateStorefront(
        storefront.id,
        off
          ? { onec_key: "", onec_url: "", onec_user: "" }
          : {
              ...connection(),
              onec_preset: preset,
              onec_reserve_now: reserve,
              // Реквизиты — только если их выбирали из прочитанных списков.
              ...(lists
                ? {
                    onec_refs: Object.fromEntries(
                      FIELDS.map((field) => [
                        field.key,
                        chosen[field.key] ?? { key: "", name: "" },
                      ]),
                    ),
                  }
                : {}),
            },
      );
      haptic("success");
      setOpen(false);
      setPassword("");
      setKey("");
      onSaved();
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Segmented<"key" | "own">
        label="Какая база 1С"
        value={kind}
        options={[
          { value: "key", label: "Тестовая база" },
          { value: "own", label: "Своя база 1С" },
        ]}
        onChange={(next) => {
          setKind(next);
          setLists(null);
        }}
      />

      {kind === "key" ? (
        <label className="flex flex-col gap-1">
          <span className="t-label text-text-secondary">Ключ базы</span>
          <input
            value={key}
            placeholder={storefront.onec_mode === "key" ? "оставьте пустым, чтобы не менять" : "demo.xxxxxxxx"}
            onChange={(event) => setKey(event.target.value)}
            className={input}
          />
          <span className="t-label text-text-secondary">
            Ключ выдаёт <CabinetLink />.
          </span>
        </label>
      ) : (
        <>
          <label className="flex flex-col gap-1">
            <span className="t-label text-text-secondary">Адрес публикации базы</span>
            <input
              value={url}
              inputMode="url"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              placeholder="https://1c.example.ru/trade"
              onChange={(event) => setUrl(event.target.value)}
              className={input}
            />
          </label>
          <div className="flex gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="t-label text-text-secondary">Пользователь</span>
              <input
                value={user}
                autoCapitalize="off"
                autoCorrect="off"
                placeholder="Обмен_MAX"
                onChange={(event) => setUser(event.target.value)}
                className={input}
              />
            </label>
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="t-label text-text-secondary">Пароль</span>
              <input
                type="password"
                value={password}
                autoComplete="new-password"
                placeholder={storefront.onec_has_password ? "сохранён" : ""}
                onChange={(event) => setPassword(event.target.value)}
                className={input}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="t-label text-text-secondary">Конфигурация</span>
            <select
              value={preset}
              onChange={(event) => {
                setPreset(event.target.value);
                setLists(null);
              }}
              className={input}
            >
              {PRESETS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <span className="t-label text-text-secondary">
            Как опубликовать базу и какие права дать пользователю — в инструкции «Подключение
            реальной базы 1С».
          </span>
        </>
      )}

      <Chip tone="neutral" disabled={busy !== null} onClick={() => void check()}>
        {busy === "check" ? "Проверяю…" : lists ? "Прочитать списки заново" : "Проверить подключение"}
      </Chip>

      {lists && (
        <div className="anim-drop flex flex-col gap-2">
          <p className="t-label text-[var(--success)]">База отвечает. Выберите реквизиты заказа:</p>
          {FIELDS.map((field) => (
            <label key={field.key} className="flex flex-col gap-1">
              <span className="t-label text-text-secondary">
                {field.label}
                {field.optional ? " — если ведёте соглашения" : ""}
              </span>
              <select
                value={chosen[field.key]?.key ?? ""}
                onChange={(event) => {
                  const option = lists[field.list].find((row) => row.key === event.target.value);
                  setChosen((prev) => ({
                    ...prev,
                    [field.key]: option ?? { key: "", name: "" },
                  }));
                }}
                className={input}
              >
                <option value="">{field.optional ? "не указывать" : "— выберите —"}</option>
                {lists[field.list].map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      <SwitchRow
        label="Резервировать в 1С сразу"
        hint={
          reserve
            ? "Заказ сразу в работе и держит товар в 1С — ещё до вашего подтверждения."
            : "Заказ ждёт «На согласовании» без резерва в 1С, резерв держит приложение. В 1С товар резервируется при подтверждении."
        }
        checked={reserve}
        onChange={setReserve}
      />

      {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void save()}
          className="h-10 flex-1 rounded-xl bg-[var(--accent)] text-[13px]/[16px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          {busy === "save" ? "Сохраняю…" : "Сохранить"}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => setOpen(false)}
          className="h-10 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>
      {linked && (
        <Chip tone="danger" disabled={busy !== null} onClick={() => void save(true)}>
          Отключить 1С — вести витрину вручную
        </Chip>
      )}
    </div>
  );
}
