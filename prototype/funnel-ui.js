"use strict";

const funnelView = {report: null, filter: null, stage: "cart", loading: false, waiting: false, study: null};
const funnelStages = {
  license: "Выбор лицензии", cart: "Корзина", order: "Самостоятельный заказ", paid: "Оплата",
};
const checksByModel = {
  event: "Сверить действие и событие", reproduce: "Воспроизвести шаг", join: "Проверить общий идентификатор",
};

function selectField(label, key, choices, value, attrs = "") {
  return `<label>${esc(label)}<select name="${key}" ${attrs}>${Object.entries(choices).map(([id, text]) =>
    `<option value="${esc(id)}" ${id === value ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
}

async function loadFunnel() {
  if (funnelView.loading || !state.data.funnel) return;
  funnelView.loading = true;
  funnelView.filter ||= {...state.data.funnel.defaults};
  try {
    funnelView.report = await api("funnel?" + new URLSearchParams(funnelView.filter));
  } catch (error) {
    if (error.status === 401) return boot();
    state.error = error.message;
  } finally {
    funnelView.loading = false;
  }
  if (route()[0] === "funnel") render();
}

function changeFunnelFilter(key, value) {
  if (funnelView.loading || funnelView.waiting) return;
  funnelView.filter[key] = value;
  const {windows} = state.data.funnel;
  if (key === "before" || key === "after") {
    const slot = key === "before" ? "after" : "before";
    if (windows[funnelView.filter[slot]].weeks !== windows[value].weeks)
      funnelView.filter[slot] = Object.keys(windows).find(id => windows[id].slot === slot && windows[id].weeks === windows[value].weeks);
  }
  funnelView.study = null;
  funnelView.report = null;
  state.error = "";
  void loadFunnel();
  render();
}

function ratio(pair) {
  if (!pair) return "";
  return pair.d ? `${number(pair.n)} / ${number(pair.d)} · ${number(100*pair.n/pair.d)}%` :
                  `${number(pair.n)} / 0 · доля недоступна`;
}

function cellRatio(pair) {
  return ratio(pair) + (pair.rows < pair.expected_rows ? " · неполное покрытие" : "");
}

function evidencePeriod(rows, report, key, caption) {
  const results = Object.entries(rows);
  if (!results.length) return "";
  const window = state.data.funnel.windows[report.filter[key]];
  return `<section><h3>${esc(window.label)} · ${esc(caption)}</h3>${results.map(([metric, value]) => `<div class="funnel-metric">
    <strong>${esc(metric)}</strong><span>${ratio(value)}</span>
    ${value.rows < value.expected_rows ? `<small>Неполное покрытие · ${value.rows} из ${value.expected_rows} строк периода</small>` : ""}
  </div>`).join("")}</section>`;
}

function measuredDetails(r) {
  const columns = ["before", "after"].map(key => {
    const pairs = r.pairs[key] || {};
    const display = {};
    if (pairs.cfg_reach_rate) display["Визиты из карточки семейства в конфигуратор"] = pairs.cfg_reach_rate;
    if (pairs.cfg_add_to_cart_rate) display["Визиты с добавлением / визиты с открытием"] = pairs.cfg_add_to_cart_rate;
    return evidencePeriod(display, r, key, r.filter.device === "all" ? "все устройства" : state.data.funnel.devices[r.filter.device]);
  }).join("");
  const stepColumns = ["before", "after"].map(key => evidencePeriod(
    Object.fromEntries(r.steps[key].map(item => [`Шаг ${item.from} → ${item.to}`, item])), r, key, "Астра · все устройства"
  )).join("");
  return `<details class="panel funnel-details"><summary>Счётчики и источники</summary>
     ${r.tracking_break ? '<p class="muted">29.09 поменялся вход. Для визитных долей показан поздний период.</p>' : ""}
     ${columns ? `<div class="funnel-detail-grid">${columns}</div>
        <p class="by">${esc(r.metric_source)} · cfg_reach_rate, cfg_add_to_cart_rate. Каждая метрика использует свой знаменатель.</p>` : ""}
     ${stepColumns ? `<div class="funnel-detail-grid">${stepColumns}</div>
        <p class="by">${esc(r.metric_source)} · cfg_step_dropoff. Каждый переход учитывает недели с обоими шагами.</p>` :
        r.filter.family === "astra" && r.filter.device !== "all"
        ? '<p class="muted">Пошаговые числа Astra в v17 собраны по всем устройствам. Поля устройства у них нет.</p>' : ""}
     ${!columns && !stepColumns ? `<p class="muted">${r.jury ? "Для этого среза нет согласованных счётчиков в демовыборке." : "В выбранных периодах нет пары счётчиков."}</p>` : ""}
     <p class="by">${esc(r.order_source)}. BI индекс не связывает этапы покупки и не содержит оплаты.</p>
     <p class="by">Ветки самостоятельного счёта, менеджера и повторной покупки требуют собственной связки событий.</p>
  </details>`;
}

function showFunnel() {
  const model = state.data.funnel;
  const r = funnelView.report;
  const f = funnelView.filter || model.defaults;
  const windows = Object.entries(model.windows);
  const periodOptions = slot => Object.fromEntries(windows.filter(([, item]) => item.slot === slot).map(([id, item]) =>
    [id, `${item.label} · ${item.weeks === 1 ? "1 неделя" : item.weeks + " недель"}`]));
  const chosen = r?.orders[f.family];
  const other = f.family === "kes" ? "astra" : "kes";
  const comparator = r?.orders[other];
  const cart = r?.pairs.after?.cfg_add_to_cart_rate;
  const step = r?.steps.after[0];
  const reach = r?.pairs.after?.cfg_reach_rate;
  const unavailable = r?.audience_gap;
  const status = chosen ? (chosen.change < 0 ? ["Падение", "down"] : chosen.change > 0 ? ["Рост", "up"] : ["Без изменения", "neutral"]) :
                          ["Пробел учёта", "gap"];
  const gate = funnelView.loading || funnelView.waiting || !r || unavailable;
  const lock = funnelView.loading || funnelView.waiting ? "disabled" : "";
  const headline = `<div class="funnel-title"><div><p class="eyebrow">${r?.jury ? "Агрегаты для жюри" : "История магазина · Softline v17"}</p>
    <h1>Воронка покупок</h1></div><p class="muted">Приоритет разработки после релиза</p></div>`;
  const filter = `<form id="funnel-filters" class="funnel-filters panel" aria-label="Фильтры воронки">
    ${selectField("Товарное семейство", "family", model.families, f.family, lock)}
    ${selectField("Первый период", "before", periodOptions("before"), f.before, lock)}
    ${selectField("Второй период", "after", periodOptions("after"), f.after, lock)}
    ${selectField("Устройство", "device", model.devices, f.device, lock)}
    ${selectField("Покупатели", "audience", model.audiences, f.audience, lock)}
  </form>`;
  if (!r || funnelView.loading) return `${headline}${filter}${messages()}${!state.error ? '<p class="feedback" role="status">Читаю счётчики…</p>' : ""}`;
  const cells = {
    license: [unavailable ? "Пробел учёта" : step || reach ? "Есть счётчики" : "Пробел учёта",
              step ? `Шаг 1 → 2 · ${cellRatio(step)}` : reach ? `Вход в конфигуратор · ${cellRatio(reach)}` :
              "Нет счётчиков шагов выбора для этого среза.", step || reach ? "neutral" : "gap"],
    cart: [cart ? "Есть счётчики" : "Пробел учёта",
           cart ? `Визиты с добавлением / с открытием · ${cellRatio(cart)}` : r.cart_gap, cart ? "neutral" : "gap"],
    order: [status[0], chosen ? `Индекс · ${number(chosen.before)} → ${number(chosen.after)}` : r.orders_gap, status[1]],
    paid: ["Пробел учёта", r.payment_gap, "gap"],
  };
  const subject = funnelView.stage === "cart" ? "Связь с корзиной" : funnelStages[funnelView.stage];
  const context = f.family === "kes"
    ? "После релиза подбора возможны сбой шага, потеря события или изменение состава визитов после смены входа."
    : "Динамика заказов может отражать состав покупателей. События конфигуратора и заказы живут в отдельных источниках.";
  const next = {
    license: "Пройти шаги выбора и сверить, где прерывается путь.",
    cart: "Сверить фактическое добавление с событием корзины.",
    order: "Проверить корзину и наличие общего идентификатора заказа.",
    paid: "Запросить связку заказа, счёта и факта оплаты.",
  }[funnelView.stage];
  return `${headline}${filter}
    ${unavailable ? `<p class="note" role="status">${esc(unavailable)}</p>` : ""}
    <ol class="funnel-stages" aria-label="Путь покупки">
      ${Object.entries(funnelStages).map(([key, label]) => `<li><button type="button" data-funnel-stage="${key}"
          aria-pressed="${funnelView.stage === key}" ${funnelView.waiting ? "disabled" : ""}>
        <span class="funnel-badge ${unavailable ? "gap" : cells[key][2]}">${esc(unavailable ? "Пробел учёта" : cells[key][0])}</span>
        <strong>${esc(label)}</strong><span class="funnel-cell-detail">${esc(unavailable ? "Нет поля сегмента." : cells[key][1])}</span>
      </button></li>`).join("")}
    </ol>
    <p class="by funnel-map-note">Карта пути покупки. Сквозной выборки от выбора лицензии до оплаты в v17 нет.</p>
    <section class="panel funnel-priority"><div class="funnel-observation">
      <span class="label">${esc(subject)} · ${esc(r.family_name)}</span>
      <h2>${funnelView.stage === "cart" && !cart ? "Где теряется корзина?" : esc(next)}</h2>
      ${chosen ? `<p><strong class="funnel-delta ${status[1]}">${signed(chosen.change)}%</strong>
            <span class="by"> средний индекс самостоятельных заказов · ${number(chosen.before)} → ${number(chosen.after)}</span></p>
         ${comparator ? `<p class="by">За те же недели ${esc(model.families[other])} ${signed(comparator.change)}% · ${number(comparator.before)} → ${number(comparator.after)}</p>` : ""}` :
        `<p class="muted">${esc(r.orders_gap)}</p>`}
      <p class="by">${esc(r.order_gap)}</p>
    </div><div class="funnel-hypothesis"><p><strong>Альтернативное объяснение</strong> · ${esc(context)}</p>
      <p><strong>Следующий шаг</strong> · ${esc(next)}</p>
      <button type="button" data-funnel-study class="primary" ${gate ? "disabled" : ""}>
        ${funnelView.waiting ? "Модель разбирает…" : "Исследовать"}</button>
    </div></section>
    ${funnelView.waiting ? '<p class="waiting feedback" role="status">Передаю локальной Qwen этап, сегмент и два периода.</p>' : ""}
    ${messages()}
    ${funnelView.study ? funnelStudyResult(funnelView.study) : ""}
    ${!unavailable ? measuredDetails(r) : ""}`;
}

function currentStudy() {
  const [page, id] = route();
  return page === "funnel" ? funnelView.study : state.data.tasks.find(t => t.id === id)?.study_data;
}

function shownRelated(item) {
  if (item.related) return button(item.related.id + " · " + item.related.title, "related", item.related.id, "link");
  if (item.candidate) return `<p class="by">В бэклоге есть ${esc(item.candidate.id)}. Модель не отметила связь.</p>`;
  return "";
}

function funnelStudyResult(item) {
  return `<section id="funnel-analysis" class="recommend">
    <div class="section-heading"><h2>Разбор выбранного этапа</h2>${chip(item.model)}</div>
    <p class="by">${esc(Object.values(item.scope).flat().join(" · "))}</p>
    <div class="grid funnel-study-grid">
      ${item.evidence.map((fact, i) => `<div><h3>${i ? "Ограничение вывода" : "Наблюдение в пользу проверки"}</h3>${sourceCard(fact)}</div>`).join("")}
    </div>
    <p>${esc(item.confirmation)}</p>
    ${shownRelated(item)}
    ${item.recommended_check ? `<p><strong>Модель предложила</strong> · ${esc(checksByModel[item.recommended_check])}</p>` : ""}
    <details><summary>Расход модели</summary>${usageSummary(item.usage)}</details>
  </section><form id="funnel-task" class="panel fields">
    <div><h2>Утвердить связанную задачу</h2><p class="by">PM утверждает критерий проверки и решает, когда данных достаточно для отката.</p></div>
    ${field("Название", "title", item.action, 'required maxlength="180"')}
    ${area("Критерий приёмки", "criterion", item.criterion, 1200, "required")}
    <div class="row"><button class="primary">Сохранить в бэклог</button>${chip(state.data.tag)}</div>
  </form>`;
}

async function runFunnelStudy() {
  if (funnelView.waiting || funnelView.loading || !funnelView.report || funnelView.report.audience_gap) return;
  funnelView.waiting = true;
  funnelView.study = null;
  state.error = "";
  render();
  try {
    funnelView.study = await api("funnel/study", {...funnelView.report.filter, stage: funnelView.stage});
  } catch (error) {
    if (error.status === 401) return boot();
    state.error = error.message;
  } finally { funnelView.waiting = false; }
  if (route()[0] === "funnel") {
    render();
    document.querySelector("#funnel-analysis")?.scrollIntoView({block:"start"});
  }
}

function eventCheck(task) {
  const p = task.plan;
  const outcomes = state.data.event_results;
  return `<div class="wide">${button("← " + taskLabel(task.id), "task", task.id, "link")}
    <p class="eyebrow">Проверка после релиза · ${taskLabel(task.id)}</p>
    <h1>Сверка действия и события</h1><p class="lede">${esc(task.title)}</p>
    <section class="panel"><h2>Правило проверки</h2><p>${esc(task.criterion)}</p>${shownRelated(task.study_data)}</section>
    <section class="panel" id="result">
      <h2>Статус данных</h2><p>${esc(task.study_data.historical_result)}</p>
      <p class="by">Фактический результат заносит PM по журналу тестовых действий.</p>
      <div class="chips">${chip("Компьютер · " + outcomes[p.desktop])}${chip("Телефон · " + outcomes[p.mobile])}</div>
      ${p.evidence ? `<p><strong>Источник сверки</strong> · ${esc(p.evidence)}</p>` : ""}
      ${p.decision ? `<p><strong>Решение PM</strong> · ${esc(p.decision)}</p>` : ""}
      ${messages()}
    </section>
    <form id="event-check-form" class="panel fields"><h2>Записать результат</h2>
      <div class="form-grid">
        ${selectField("Компьютер", "desktop", outcomes, p.desktop)}
        ${selectField("Телефон", "mobile", outcomes, p.mobile)}
      </div>
      ${field("Источник сверки", "evidence", p.evidence, 'maxlength="700"')}
      ${area("Решение PM", "decision", p.decision, 700)}
      <div><button class="primary">Сохранить результат проверки</button></div>
    </form></div>`;
}
