"use strict";

const funnelView = {report: null, filter: null, stage: "order", loading: false, waiting: false};
const funnelStages = {
  license: "Выбор лицензии", cart: "Корзина", order: "Самостоятельный заказ", paid: "Оплата",
};

function selectField(label, key, choices, value, attrs = "") {
  return `<label>${esc(label)}<select name="${key}" aria-label="${esc(label)}" ${attrs}>${Object.entries(choices).map(([id, text]) =>
    `<option value="${esc(id)}" ${id === value ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
}

async function loadFunnel() {
  if (funnelView.loading || !state.data.funnel) return;
  funnelView.loading = true;
  funnelView.filter ||= {...state.data.funnel.defaults};
  const query = new URLSearchParams(funnelView.filter).toString();
  const current = () => new URLSearchParams(funnelView.filter).toString() === query;
  try {
    const [report, storeData] = await Promise.all([
      api("funnel?" + query), state.data.store ? api("radar/orders?" + query) : null
    ]);
    if (current()) funnelView.report = {...report, storeData};
  } catch (error) {
    if (error.status === 401) return boot();
    if (current()) state.error = error.message;
  } finally {
    funnelView.loading = false;
  }
  if (route()[0] === "funnel") render();
}

function changeFunnelFilter(key, value) {
  if (funnelView.loading || funnelView.waiting) return;
  funnelView.filter[key] = value;
  const f = funnelView.filter;
  if (key === "before" && (value === "oct12") !== (f.after === "oct19")) f.after = value === "oct12" ? "oct19" : "oct";
  if (key === "after" && (value === "oct19") !== (f.before === "oct12")) f.before = value === "oct19" ? "oct12" : "aug";
  rememberFunnelView();
  funnelView.report = null;
  state.error = "";
  void loadFunnel();
  render();
}

function rememberFunnelView() {
  if (state.data.store) history.replaceState(null,"","#funnel/"+deviationRef(funnelView.filter)+"~"+funnelView.stage);
}

function restoreFunnelView(ref) {
  if (!ref || !state.data.store) return;
  const [raw,stage] = ref.split("~");
  const choice=deviationArgs(raw);
  const model=state.data.funnel;
  if (!Object.hasOwn(model.families,choice.family) || !model.windows[choice.before] || !model.windows[choice.after] ||
      !model.devices[choice.device] || !model.audiences[choice.audience]) return;
  if (funnelStages[stage]) funnelView.stage=stage;
  if (deviationRef(funnelView.filter || model.defaults) !== raw) {
    funnelView.filter=choice;
    funnelView.report=null;
  }
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
     ${state.data.store ? Object.values(state.data.store.definitions).filter(d=>/cfg_/.test(d.source) || /корзин|конфигуратор/i.test(d.title))
       .slice(0,6).map(d=>sourceLink(d)).join(" · ") : ""}
     <p class="by">Ветки самостоятельного счёта, менеджера и повторной покупки требуют собственной связки событий.</p>
  </details>`;
}

function ordersDetail(report) {
  const entries = Object.entries(report.orders).filter(([,item])=>item);
  if (!entries.length) return "";
  const windows = state.data.funnel.windows;
  const {before,after} = report.filter;
  const weekly = [...report.series.before,...report.series.after];
  const max = weekly.length ? Math.ceil(Math.max(...weekly.map(row=>row.value))/100)*100 : 100;
  return `<details class="panel"><summary>Сравнение семейств и недельный ряд</summary>
    <div class="table-wrap"><table><thead><tr><th>Семейство</th><th>${esc(windows[before].label)}</th>
      <th>${esc(windows[after].label)}</th><th>Изменение</th></tr></thead><tbody>
      ${entries.map(([family,item])=>`<tr><td>${esc(state.data.funnel.families[family])}</td>
      <td>${number(item.before)}</td><td>${number(item.after)}</td><td>${signed(item.change)}%</td></tr>`).join("")}
    </tbody></table></div><p class="by">${esc(report.order_source)}. База 100 · 04.05–28.06.2026 для каждого семейства.</p>
    ${report.storeData ? `<p class="by">${report.storeData.evidence.map((row,i)=>sourceLink(row,"Открыть основание · "+["Kaspersky","Astra"][i])).join(" · ")}</p>` :
      weekly.length ? `<div class="radar-weekly">${weekly.map(row=>`<div><span>${esc(prettyDate(row.date).slice(0,5))}</span>
      <meter min="0" max="${max}" value="${row.value}" aria-label="Индекс заказов"></meter><strong>${number(row.value)}</strong></div>`).join("")}</div>` :
      "<p class='muted'>Недельный ряд остаётся в закрытой книге. В демо доступны средние индексы согласованных окон.</p>"}
  </details>`;
}

function stageSummary(r, chosen, comparator, other, status, gate) {
  const stage = funnelView.stage;
  const pair = r.pairs.after?.cfg_add_to_cart_rate;
  const step = r.steps.after[0];
  const reach = r.pairs.after?.cfg_reach_rate;
  const model = state.data.funnel;
  const defaultAction = label => `<button type="button" data-funnel-study class="primary" ${gate ? "disabled" : ""}>${label}</button>`;
  if (stage === "order" && chosen) {
    const direction = chosen.change < 0 ? "↓" : chosen.change > 0 ? "↑" : "·";
    const label = `Самостоятельные заказы ${r.family_name} ${direction} ${number(Math.abs(chosen.change))}%`;
    return `<section class="panel radar-signal ${status[1]}"><div>
      <p class="label">Самостоятельный заказ · ${esc(status[0])}</p><h2>${esc(label)}</h2>
      <p>Индекс BI <strong>${number(chosen.before)} → ${number(chosen.after)}</strong>.
        ${comparator ? `${esc(model.families[other])} ${signed(comparator.change)}% за те же недели.` : ""}</p>
      <p class="by">${esc(model.windows[r.filter.before].label)} и ${esc(model.windows[r.filter.after].label)}.
        Покрытие: ${r.coverage.before} и ${r.coverage.after} недель${r.coverage.partial ? ", последняя неполная":""}. Индексы двух семейств.</p>
    </div><div>${r.filter.family==="kes" ? button("Открыть отклонение", "deviation", deviationRef(r.filter), "primary") :
      button("Где меняется прохождение?", "page", "astra", "secondary")}</div></section>`;
  }
  const stageInfo = {
    license: {title:"Используют ли подбор?", text:step ? `Шаг 1 → 2 · ${cellRatio(step)}` :
      reach ? `Выбрали хотя бы одну опцию / визиты страниц семейства · ${cellRatio(reach)}.` : "Нет счётчиков шагов выбора.",
      note:r.filter.family==="kes" ? "У Kaspersky фильтры без последовательных шагов. Сравнение использования до запуска недоступно." :
        "Проверить вход в подбор и переходы отдельно.", action:`<div class="row">
          ${r.filter.family==="kes" ? defaultAction("Проверить использование фильтров") : ""}
          ${r.filter.family==="astra" ? button("Где меняется прохождение?", "page", "astra", "secondary") : ""}</div>`},
    cart: {title:"Добавляли ли товар в корзину?", text:pair ? `Визиты с добавлением / визиты с открытием · ${cellRatio(pair)}` : r.cart_gap,
      note:r.filter.family==="kes" ? "Связанная T-08 касается передачи событий. Первый шаг — сверить действие и запись." :
        "Доля относится к открытиям конфигуратора в доступных строках.", action:defaultAction("Сверить события корзины")},
    order: {title:"Самостоятельные заказы", text:r.orders_gap, note:r.order_gap, action:""},
    paid: {title:"Дошёл ли заказ до оплаты?", text:r.payment_gap,
      note:"Для измерения нужны исход оплаты, канал и общее связывающее поле.", action:defaultAction("Проверить связь с оплатой")},
  }[stage];
  return `<section class="panel funnel-priority"><div><h2>${esc(stageInfo.title)}</h2>
    <p>${esc(r.audience_gap || stageInfo.text)}</p><p class="by">${esc(stageInfo.note)}</p>
  </div><div class="funnel-hypothesis">${r.audience_gap ? "" : stageInfo.action}</div></section>
  ${stage==="license" && r.filter.family==="kes" && !r.audience_gap ? optionDetail(r) : ""}`;
}

function optionDetail(r) {
  const labels = {edition:"Редакция",duration:"Срок",license_type:"Тип лицензии"};
  const groups = Object.entries(r.options || {});
  return `<details class="panel"><summary>Выбор редакций, сроков и типов лицензии</summary>
    ${groups.length ? groups.map(([key,values])=>{
      const total = Object.values(values).reduce((sum, v)=>sum+v,0);
      return `<h3>${labels[key]}</h3>${Object.entries(values).map(([name,n])=>`<p>${esc(name)} · ${ratio({n,d:total})}</p>`).join("")}`;
    }).join("") : "<p>Для этого среза нет доступных распределений опций.</p>"}
    <p class="by">Softline v17 · cfg_option_share. Знаменатель — сумма записей по значениям одной группы. Это не число покупателей.</p>
  </details>`;
}

function showFunnel() {
  const model = state.data.funnel;
  const r = funnelView.report;
  const f = funnelView.filter || model.defaults;
  const windows = Object.entries(model.windows);
  const periodOptions = slot => Object.fromEntries(windows.filter(([id, item]) => item.slot === slot &&
    (!item.partial || f.after==="oct_partial") && (f.after!=="oct_partial" || slot!=="after" || item.partial || id==="oct19")).map(([id, item]) =>
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
    <h1>Воронка покупок</h1></div><p class="muted">${state.data.store ? esc(coverageCaption(state.data.store)) : "Приоритет разработки после релиза"}</p></div>`;
  const filter = `<form id="funnel-filters" class="funnel-filters panel" aria-label="Фильтры воронки">
    ${selectField("Товарное семейство", "family", model.families, f.family, lock)}
    ${selectField("Первый период", "before", periodOptions("before"), f.before, lock)}
    ${selectField("Второй период", "after", periodOptions("after"), f.after, lock)}
    ${selectField("Устройство", "device", model.devices, f.device, lock)}
    ${selectField("Покупатели", "audience", model.audiences, f.audience, lock)}
    ${state.data.store && f.after!=="oct19" ? `<label class="toggle"><input name="full_weeks" type="checkbox" ${f.after==="oct_partial"?"":"checked"} ${lock}>Только полные недели</label>` : ""}
  </form>`;
  if (!r || funnelView.loading) return `${headline}${filter}${messages()}${!state.error ? '<p class="feedback" role="status">Читаю счётчики…</p>' : ""}`;
  const cells = {
    license: [unavailable ? "Пробел учёта" : step || reach ? "Есть счётчики" : "Пробел учёта",
              step ? `Шаг 1 → 2 · ${cellRatio(step)}` : reach ? `Выбрали хотя бы одну опцию · ${cellRatio(reach)}` :
              "Нет счётчиков шагов выбора для этого среза.", step || reach ? "neutral" : "gap"],
    cart: [cart ? "Есть счётчики" : "Пробел учёта",
           cart ? `Визиты с добавлением / с открытием · ${cellRatio(cart)}` : r.cart_gap, cart ? "neutral" : "gap"],
    order: [status[0], chosen ? `Индекс · ${number(chosen.before)} → ${number(chosen.after)}` : r.orders_gap, status[1]],
    paid: ["Пробел учёта", r.payment_gap, "gap"],
  };
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
    ${stageSummary(r, chosen, comparator, other, status, gate)}
    ${messages()}
    ${funnelView.stage === "order" ? ordersDetail(r) : ""}
    ${state.data.store && funnelView.stage==="order" && f.family==="astra" && !unavailable && f.device==="all" ? astraAlert() : ""}
    ${!unavailable && funnelView.stage !== "order" ? measuredDetails(r) : ""}
    <section class="panel radar-coverage"><div><h2>Покрытие магазина</h2>
      <p>Индексы заказов только у Kaspersky и Astra. В других ветках есть материалы по товарам.</p></div>
      <div class="row">${button("Поиск продукта", "page", "catalog")}${button("Возможности роста", "page", "growth")}</div>
    </section>${storeIndicators()}`;
}

function currentStudy() {
  const [, id] = route();
  return state.data.tasks.find(t => t.id === id)?.study_data;
}

function shownRelated(item) {
  if (item.related) return button(item.related.id + " · " + item.related.title, "related", item.related.id, "link");
  if (item.candidate) return `<p class="by">В бэклоге есть ${esc(item.candidate.id)}. Модель не отметила связь.</p>`;
  return "";
}

async function runFunnelStudy() {
  if (funnelView.waiting || funnelView.loading || !funnelView.report || funnelView.report.audience_gap) return;
  funnelView.waiting = true;
  state.error = "";
  render();
  try {
    await startRadar({...funnelView.report.filter, stage: funnelView.stage, mode:"stage"});
  } catch (error) {
    if (error.status === 401) return boot();
    state.error = error.message;
  } finally { funnelView.waiting = false; }
  if (route()[0] === "funnel") render();
}

function eventCheck(task) {
  const p = task.plan;
  const outcomes = state.data.event_results;
  const finding = task.radar?.finding === "kes";
  return `<div class="wide">${button("← " + taskLabel(task.id), "task", task.id, "link")}
    <p class="eyebrow">${finding ? "Самостоятельный заказ" : "Проверка после релиза"} · ${taskLabel(task.id)}</p>
    <h1>${finding ? "Проверка после релиза" : "Сверка действия и события"}</h1><p class="lede">${esc(task.title)}</p>
    ${finding ? button("Открыть исходную находку","run",task.radar.id,"link") : ""}
    <section class="panel"><h2>Правило проверки</h2><p>${esc(task.criterion)}</p>${shownRelated(task.study_data)}
      ${task.radar?.owner ? `<p class="by">Владелец · ${esc(task.radar.owner)}. Вернуться ${prettyDate(task.radar.due)}.</p>` : ""}
      ${task.radar?.followup ? `<p class="by">Условие повторной проверки · ${esc(task.radar.followup)}</p>` : ""}</section>
    <section class="panel" id="result">
      <h2>Статус данных</h2>${p.desktop==="waiting" && p.mobile==="waiting" ? chip("Ждём данные") : ""}<p>${esc(task.study_data.historical_result)}</p>
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
