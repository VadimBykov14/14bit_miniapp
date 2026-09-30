/* Кабинет эмулятора 1С: скрипт страницы ui.html. */

const api = (path, options) => fetch("/1c/api" + path, {
  headers: { "Content-Type": "application/json" }, ...options,
}).then(async (response) => {
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.status);
  return response.json();
});

let current = null;
let detail = null;
// Что уже показано: новое после обновления подсвечивается.
let seen = null;
let pending = false;

const escape = (text) => String(text ?? "").replace(/[&<>"']/g, (ch) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const ref = (item) => escape(item.Ref_Key);

async function loadBases() {
  const { bases } = await api("/bases");
  current = current && bases.some((b) => b.slug === current) ? current : bases[0]?.slug;
  document.getElementById("tabs").innerHTML = bases.map((base) =>
    `<button aria-current="${base.slug === current}" data-act="select" data-slug="${escape(base.slug)}">
       ${escape(base.name)} <span class="muted">· ${base.items}</span>
     </button>`).join("");
  if (current) await loadBase();
}

async function select(slug) { current = slug; await loadBases(); }

async function createBase() {
  const name = document.getElementById("new-base").value.trim();
  if (!name) return;
  const base = await api("/bases", { method: "POST", body: JSON.stringify({
    name, copy_items: document.getElementById("copy-items").checked }) });
  document.getElementById("new-base").value = "";
  current = base.slug;
  await loadBases();
}

async function loadBase() {
  detail = await api("/bases/" + current);
  render();
}

/** Отпечаток базы: перерисовываем, только если что-то изменилось. */
const fingerprint = (base) => JSON.stringify([
  base.items.map((item) => [item.Ref_Key, item.Description, item.Цена, item.Остаток]),
  (base.contractors || []).map((row) => row.Ref_Key),
  base.documents.map((doc) => [doc.Number, doc.Статус, doc.DeletionMark, doc.Проведён,
                               JSON.stringify(doc.Товары)]),
  base.corrections.map((doc) => doc.Number),
  base.writeoffs.length,
  base.key,
]);

/** Пока человек правит поле, страницу не перерисовываем — иначе ввод
 *  пропал бы. Обновление дождётся, когда он уйдёт из поля. */
const editing = () => {
  const active = document.activeElement;
  return active && document.getElementById("base").contains(active) && active.tagName === "INPUT";
};

async function poll() {
  if (document.hidden || !current) return;
  try {
    const fresh = await api("/bases/" + current);
    if (fingerprint(fresh) === fingerprint(detail)) return;
    if (editing()) { pending = true; return; }
    detail = fresh;
    render();
  } catch (error) { /* сеть моргнула — попробуем в следующий раз */ }
}

document.addEventListener("focusout", () => {
  if (pending) { pending = false; setTimeout(poll, 50); }
});
setInterval(poll, 3000);

const money = (value) =>
  new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";

const total = (doc) => (doc.Товары || []).reduce(
  (sum, line) => sum + Number(line.Сумма ?? (line.Количество || 0) * (line.Цена || 0)), 0);

const goods = (doc) => (doc.Товары || [])
  .map((line) => `${escape(line.Номенклатура)} × ${line.Количество}`)
  .join("; ");

/** Дата отгрузки заказа: поставщик мог перенести доставку. */
const shipDate = (doc) => doc.ДатаОтгрузки
  ? `<div class="lines">отгрузка ${escape(doc.ДатаОтгрузки).slice(0, 10).split("-").reverse().join(".")}</div>`
  : "";

/** Что с заказом: ждёт поставщика, в работе или отменён. «На согласовании»
 *  в УТ товар не резервирует — резерв держит приложение. */
const state = (doc) => doc.DeletionMark
  ? '<span class="tag off">отменён · резерв снят</span>'
  : doc.Статус === "НеСогласован"
    ? '<span class="tag wait">на согласовании · без резерва</span>'
    : doc.Проведён === false
      ? '<span class="tag wait">не проведён</span>'
      : '<span class="tag ok">в работе · товар в резерве</span>';

function render() {
  const previous = seen && seen.slug === detail.slug ? seen : null;
  const fresh = (kind, key) => previous && !previous[kind].has(key) ? "flash" : "";
  const docKey = (doc) => `${doc.Number}:${doc.Статус}:${doc.ДатаОтгрузки}:${doc.DeletionMark}:${JSON.stringify(doc.Товары)}`;
  const moved = (item) => previous && previous.stock.has(item.Ref_Key)
    && previous.stock.get(item.Ref_Key) !== item.Остаток ? "flash" : "";

  const rows = detail.items.map((item) => `
    <tr class="${moved(item)}">
      <td><input value="${escape(item.Description)}" data-ref="${ref(item)}" data-field="Description"></td>
      <td><input class="num" value="${escape(item.ЕдиницаИзмерения)}" data-ref="${ref(item)}" data-field="ЕдиницаИзмерения"></td>
      <td><input class="num" value="${escape(item.Цена)}" data-ref="${ref(item)}" data-field="Цена"></td>
      <td><input class="num" value="${escape(item.Остаток)}" data-ref="${ref(item)}" data-field="Остаток"></td>
      <td class="row">
        <input class="num" placeholder="списать" id="off-${ref(item)}">
        <button class="ghost" data-act="write-off" data-ref="${ref(item)}">Списать</button>
        <button class="bad" data-act="drop-item" data-ref="${ref(item)}">×</button>
      </td>
    </tr>`).join("");

  const docs = detail.documents.map((doc) => `
    <tr class="${fresh("docs", docKey(doc))} ${doc.DeletionMark ? "gone" : ""}"><td>${escape(doc.Number)}
          <div class="lines">${state(doc)}</div></td><td>${escape(doc.Контрагент)}</td>
        <td>${escape(doc.Комментарий)}<div class="lines">${goods(doc)}</div></td>
        <td class="sum">${money(total(doc))}</td>
        <td class="muted">${escape(doc.Date).slice(0, 16).replace("T", " ")}${shipDate(doc)}</td></tr>`).join("");

  const corrections = detail.corrections.map((doc) => `
    <tr class="${fresh("corrections", doc.Number)}"><td>${escape(doc.Number)}
          ${doc.Основание ? `<div class="lines">по ${escape(doc.Основание)}</div>` : ""}</td>
        <td>${escape(doc.Контрагент)}</td>
        <td>${escape(doc.Комментарий)}<div class="lines">принято: ${goods(doc)}</div></td>
        <td class="sum">${money(total(doc))}</td>
        <td class="muted">${escape(doc.Date).slice(0, 16).replace("T", " ")}</td></tr>`).join("");

  const contractors = (detail.contractors || []).map((row) => `
    <tr class="${fresh("contractors", row.Ref_Key)}"><td>${escape(row.Description)}</td></tr>`).join("");

  seen = {
    slug: detail.slug,
    contractors: new Set((detail.contractors || []).map((row) => row.Ref_Key)),
    docs: new Set(detail.documents.map(docKey)),
    corrections: new Set(detail.corrections.map((doc) => doc.Number)),
    stock: new Map(detail.items.map((item) => [item.Ref_Key, item.Остаток])),
  };

  const offs = detail.writeoffs.map((row) => `
    <tr><td>${escape(row.Номенклатура)}</td><td>${row.Количество}</td>
        <td class="muted">${escape(row.Причина)}</td>
        <td class="muted">${escape(row.at).slice(0, 16).replace("T", " ")}</td></tr>`).join("");

  document.getElementById("base").innerHTML = `
    <div class="card">
      <h2 style="margin-top:0">Ключ для витрины</h2>
      <p class="muted">
        Скопируйте и вставьте при создании витрины в мини-приложении —
        поле «Ключ базы 1С». Адрес базы зашит в самом ключе, больше ничего
        вводить не нужно. Один ключ — одна база: чужим ключом чужую
        номенклатуру не открыть. Пользователь обмена — «${escape(detail.user)}».
      </p>
      <p><span class="key" id="key">${escape(detail.key)}</span></p>
      <div class="row">
        <button data-act="copy-key">Скопировать ключ</button>
        <button class="ghost" data-act="rotate">Сменить ключ</button>
        <button class="bad" data-act="drop-base">Удалить базу</button>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Номенклатура</h2>
      <table>
        <thead><tr><th>Наименование</th><th>Ед.</th><th>Цена</th>
                   <th>Остаток</th><th></th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="muted">Пусто</td></tr>'}</tbody>
      </table>
      <div class="row" style="margin-top:12px">
        <input class="grow" id="item-name" placeholder="Наименование">
        <input class="num" id="item-unit" placeholder="шт" value="шт">
        <input class="num" id="item-price" placeholder="цена">
        <input class="num" id="item-stock" placeholder="остаток" value="0">
        <button data-act="add-item">Добавить</button>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Контрагенты</h2>
      <p class="muted">На кого оформляются заказы клиентов. У каждой базы свой список.
        Поставщик выбирает контрагента магазина в приложении — когда подключает клиента
        к витрине на 1С или позже в карточке клиента. Новый контрагент появится там сразу.</p>
      <table>
        <thead><tr><th>Наименование</th></tr></thead>
        <tbody>${contractors || '<tr><td class="muted">Пусто</td></tr>'}</tbody>
      </table>
      <div class="row" style="margin-top:12px">
        <input class="grow" id="contractor-name" maxlength="150"
               placeholder="Например, ИП Смирнова (магазин «Ромашка»)">
        <button data-act="add-contractor">Добавить</button>
      </div>
      <p id="contractor-note" class="muted" role="status"></p>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Журнал списаний</h2>
      <table>
        <thead><tr><th>Позиция</th><th>Кол-во</th><th>Причина</th><th>Когда</th></tr></thead>
        <tbody>${offs || '<tr><td colspan="4" class="muted">Списаний не было</td></tr>'}</tbody>
      </table>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Заказы клиентов из приложения</h2>
      <p class="muted">Заказ появляется здесь, как только клиент оформил заявку. «На согласовании»
        он товар не резервирует — если поставщик не выбрал «резервировать сразу». Подтверждение
        переводит заказ в работу и проводит — остаток уменьшается; отказ или отмена снимают
        проведение, и товар возвращается на склад.</p>
      <table>
        <thead><tr><th>Документ</th><th>Контрагент</th><th>Комментарий и товары</th><th>Сумма</th><th>Дата</th></tr></thead>
        <tbody>${docs || '<tr><td colspan="5" class="muted">Документов ещё нет</td></tr>'}</tbody>
      </table>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Корректировки по приёмке</h2>
      <p class="muted">Прежние документы. Теперь расхождения приёмки приходят комментарием к
        заказу, а корректировку по реализации оформляет учётчик — как в УТ.</p>
      <table>
        <thead><tr><th>Документ</th><th>Контрагент</th><th>Комментарий</th><th>Сумма</th><th>Дата</th></tr></thead>
        <tbody>${corrections || '<tr><td colspan="5" class="muted">Корректировок не было</td></tr>'}</tbody>
      </table>
    </div>`;
}

async function save(ref, field, value) {
  const numeric = ["Цена", "Остаток"].includes(field);
  await api(`/bases/${current}/items/${ref}`, {
    method: "PATCH",
    body: JSON.stringify({ [field]: numeric ? Number(String(value).replace(",", ".")) : value }),
  });
  await loadBase();
}

async function addItem() {
  const name = document.getElementById("item-name").value.trim();
  if (!name) return;
  await api(`/bases/${current}/items`, { method: "POST", body: JSON.stringify({
    Description: name,
    ЕдиницаИзмерения: document.getElementById("item-unit").value || "шт",
    Цена: Number(document.getElementById("item-price").value || 0),
    Остаток: Number(document.getElementById("item-stock").value || 0),
  }) });
  document.getElementById("item-name").value = "";
  document.getElementById("item-price").value = "";
  await loadBase();
}

/** Контрагент базы: пустое не отправляем, отказ сервера — под полем. */
async function addContractor() {
  const field = document.getElementById("contractor-name");
  const note = document.getElementById("contractor-note");
  const name = field.value.trim();
  if (!name) { field.focus(); return; }
  note.className = "muted";
  note.textContent = "Добавляю…";
  try {
    await api(`/bases/${current}/contractors`, { method: "POST", body: JSON.stringify({ name }) });
    field.value = "";
    await loadBase();
  } catch (error) {
    const text = String(error.message);
    note.className = "error";
    note.textContent = `Не добавлен: ${text}`;
  }
}

async function dropItem(ref) {
  await api(`/bases/${current}/items/${ref}`, { method: "DELETE" });
  await loadBase();
}

async function writeOff(ref) {
  const field = document.getElementById("off-" + ref);
  const qty = Number(String(field.value).replace(",", "."));
  if (!qty) return;
  const reason = prompt("Причина списания", "бой") ?? "";
  await api(`/bases/${current}/items/${ref}/write-off`, {
    method: "POST", body: JSON.stringify({ qty, reason }),
  });
  field.value = "";
  await loadBase();
}

async function rotate() {
  if (!confirm("Старый ключ перестанет работать. Сменить?")) return;
  await api(`/bases/${current}/key`, { method: "POST" });
  await loadBase();
}

async function dropBase() {
  if (!confirm("Удалить базу вместе с номенклатурой и документами?")) return;
  try {
    await api(`/bases/${current}`, { method: "DELETE" });
    current = null;
    await loadBases();
  } catch (error) { alert(error.message); }
}

function copyKey() {
  navigator.clipboard?.writeText(detail.key);
}

// Обработчики — здесь, а не атрибутами в разметке: политика безопасности
// кабинета запрещает встроенные скрипты, и такой атрибут браузер не
// выполнит. По той же причине ничего не запустит и разметка, пришедшая
// в названии магазина или позиции.
const actions = {
  "create-base": () => createBase(),
  select: (el) => select(el.dataset.slug),
  "write-off": (el) => writeOff(el.dataset.ref),
  "drop-item": (el) => dropItem(el.dataset.ref),
  "copy-key": () => copyKey(),
  rotate: () => rotate(),
  "drop-base": () => dropBase(),
  "add-item": () => addItem(),
  "add-contractor": () => addContractor(),
};

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-act]");
  if (target && actions[target.dataset.act]) actions[target.dataset.act](target);
});

// Enter в поле контрагента — то же, что «Добавить»: формы на странице нет.
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.id === "contractor-name") addContractor();
});

document.addEventListener("change", (event) => {
  const field = event.target.closest("[data-field]");
  if (field) save(field.dataset.ref, field.dataset.field, field.value);
});

loadBases();
