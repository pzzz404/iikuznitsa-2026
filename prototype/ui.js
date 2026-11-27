"use strict";

const app = document.querySelector("#app");
const dialog = document.querySelector("#evidence");
const dialogBody = document.querySelector("#dialog-body");
const nav = document.querySelector("nav");
const state = {data: null, topic: "invoice", question: "", study: null, waiting: false, error: "", notice: ""};
const pages = ["funnel", "signals", "backlog", "checks", "sources", "usage"];
const esc = value => String(value ?? "").replace(/[&<>"']/g, char =>
  ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;"}[char]));
const number = value => new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 1}).format(value);
const signed = value => (value > 0 ? "+" : "") + number(value).replace("-", "−");
const seconds = ms => number(ms / 1000) + " с";
const callStatus = {ok:"Готово",error:"Ошибка",no_result:"Без вывода",received:"Ответ получен",
  running:"Выполняется",interrupted:"Прерван"};
const prettyDate = val => val.split("-").reverse().join(".");
const allFacts = () => [...state.data.facts, ...state.data.research];
const taskLabel = id => "PM-" + String(id).padStart(3, "0");
const chip = value => '<span class="chip">' + esc(value) + '</span>';
const button = (label, name, value, cls = "secondary") =>
  `<button class="${cls}" type="button" data-${name}="${esc(value)}">${esc(label)}</button>`;
const field = (label, name, value, attrs = "") =>
  `<label>${esc(label)}<input name="${name}" value="${esc(value)}" ${attrs}></label>`;
const area = (label, name, value, max, extra = "") =>
  `<label>${esc(label)}<textarea name="${name}" aria-label="${esc(label)}" maxlength="${max}" ${extra}>${esc(value)}</textarea></label>`;

async function api(path, data) {
  const res = await fetch("/api/" + path, data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data),
  });
  const payload = await res.json();
  if (!res.ok) throw Object.assign(new Error(payload.error || "Не удалось выполнить запрос"), {status: res.status});
  return payload;
}

async function refresh() {
  state.data = await api("data");
  if (!state.question) state.question = state.data.topics[state.topic].question;
}

function route() {
  const [page, id] = location.hash.slice(1).split("?")[0].split("/");
  const hasFunnel = state.data?.funnel;
  if (page === "funnel" && hasFunnel) return [page,id];
  if (hasFunnel && radarPages.includes(page)) return [page, id];
  const available = pages.includes(page) && (page !== "funnel" || hasFunnel) &&
                    (page !== "signals" || !(state.data?.jury && hasFunnel));
  return [available ? page : hasFunnel ? "funnel" : "signals", Number(id)];
}

function hashParams() {
  return new URLSearchParams(location.hash.split("?")[1] || "");
}

function overviewNavigation() {
  if (!state.data.store) return {};
  const from=route()[0]==="funnel" ? overviewRef() : hashParams().get("from");
  return from ? {from} : {};
}

function go(page, id, params={}) {
  const query = new URLSearchParams(params).toString();
  const hash = "#" + page + (id ? "/" + id : "") + (query ? "?" + query : "");
  if (location.hash === hash) render();
  else location.hash = hash;
  window.scrollTo(0, 0);
}

function messages() {
  return (state.error ? `<p class="error feedback" role="alert">${esc(state.error)}</p>` : "") +
         (state.notice ? `<p class="feedback" role="status">${esc(state.notice)}</p>` : "");
}

function sourceCard(fact) {
  return `<article class="source-card"><span class="label">${esc(fact.id)} · ${esc(fact.type)}</span>
    <h3>${esc(fact.title)}</h3><p>${esc(fact.text)}</p>
    ${button("Открыть источник", "fact", fact.id, "link")}</article>`;
}

function openSource(id) {
  const radarInfo = detailForRoute();
  const [page, ref] = route();
  const task = ["backlog","checks"].includes(page) ? state.data.tasks.find(t => t.id === ref) : null;
  const known = radarInfo?.run?.before ? radarInfo.run.before.known : radarInfo?.known;
  const fact = (radarInfo?.result?.evidence || radarInfo?.evidence)?.find(f => f.id === id) ||
    radarInfo?.run?.operations.find(op => op.record?.id === id)?.record ||
    (known?.id === id ? known : null) || task?.study_data.evidence.find(f => f.id === id) ||
    currentStudy()?.evidence.find(f => f.id === id) || storeFacts().find(f=>f.id===id) ||
    allFacts().find(f => f.id === id);
  if (!fact) return;
  dialogBody.innerHTML = `<h2>${esc(fact.title)}</h2><p class="by">${esc(fact.source)}${fact.version ? " · " + esc(fact.version) : ""}${fact.date ? " · " + prettyDate(fact.date) : ""}</p>
    ${fact.cohort ? `<p class="by">Когорта · ${esc(fact.cohort)}${fact.role ? " · " + esc(fact.role) : ""}</p>` : ""}
    ${fact.derived ? '<p class="by">Сводка по указанным записям</p>' : ""}
    <blockquote>${esc(fact.text)}</blockquote>
    ${fact.rule ? `<p><strong>Правило сигнала</strong> · ${esc(fact.rule)}</p>` : ""}
    ${fact.scope ? `<p class="by">Разрез · ${esc(fact.scope)}</p>` : ""}
    ${fact.note ? `<p class="by">${esc(fact.note)}</p>` : ""}
    ${fact.releases?.length ? `<p>Связанные события · ${fact.releases.map(esc).join(", ")}</p>` : ""}
    ${fact.image ? `<img alt="Фрагмент интерфейса магазина" src="/images/${esc(fact.image)}">` : ""}`;
  dialog.showModal();
}

function usageSummary(usage) {
  if (!usage.calls) return '<p class="muted">Для этой задачи журнал вызовов пуст.</p>';
  const external = usage.usd_calls > 0;
  const price = external ? (usage.usd === null ? "Нет замера" : esc(usage.usd) + " USD") : "0 ₽";
  const billing = external ? ` · списание подтверждено для ${usage.usd_confirmed}/${usage.usd_calls} вызовов` : " · серверные расходы отдельно";
  return `<dl class="summary-grid">
    <div><dt>Вход</dt><dd>${number(usage.prompt)}</dd></div>
    <div><dt>Выход</dt><dd>${number(usage.completion)}</dd></div>
    <div><dt>Вызовы</dt><dd>${usage.measured}/${usage.calls}</dd></div>
    <div><dt>${external ? "Списание OpenRouter" : "По тарифу шаблона"}</dt><dd>${price}</dd></div></dl>
    <p class="by">Вызовы с замером / всего · ${seconds(usage.elapsed_ms)} суммарно${billing}</p>`;
}

function studied() {
  const item = state.study;
  if (!item) return "";
  const cfg = state.data.topics[item.topic];
  return `<section id="analysis">
    <div class="section-heading"><h2>Свидетельства разбора</h2>${chip(item.model)}</div>
    <div class="grid">${item.evidence.map(sourceCard).join("")}</div>
    ${item.retrieved?.some(f => !item.selected.includes(f.id)) ? `<details class="panel"><summary>Другие совпадения в добавленных исследованиях</summary>
      <div class="grid">${item.retrieved.filter(f => !item.selected.includes(f.id)).map(sourceCard).join("")}</div></details>` : ""}
    <section class="recommend">
      <h2>${esc(state.data.decisions[item.decision])}</h2>
      ${item.focus ? `<p><strong>Фокус модели</strong> · ${esc(item.focus)}</p>` : ""}
      <p class="muted">${esc(cfg.limit)}</p>
      <details class="run-usage"><summary>Замер модели · ${number(item.usage.prompt + item.usage.completion)} токенов · ${seconds(item.calls.at(-1).elapsed_ms)}</summary>${usageSummary(item.usage)}</details>
    </section>
    <form id="create-task" class="panel fields">
      <div><h2>Задача в бэклог</h2><p class="by">Шаблон по теме. Перед сохранением PM уточняет критерий.</p></div>
      ${field("Название", "title", cfg.action, 'required maxlength="180"')}
      ${area("Критерий приёмки", "criterion", cfg.criterion, 1200, "required")}
      <div class="row"><button class="primary">Сохранить в бэклог</button>${chip(state.data.tag)}</div>
    </form></section>`;
}

function signals() {
  const cfg = state.data.topics[state.topic];
  const overdue = state.data.tasks.filter(t => !t.plan.decision && t.plan.date <= state.data.today);
  const active = state.data.deferred.find(d => d.topic === state.topic);
  const context = state.data.facts.filter(f => cfg.allowed.includes(f.id));
  return `<div class="shell"><aside class="rail"><h2>Сигналы магазина</h2>
    ${Object.entries(state.data.topics).filter(([id]) => !state.data.external || id === "invoice").map(([id,t]) => `<button type="button" data-topic="${id}" class="signal ${id === state.topic ? "selected" : ""}">
      <small>${state.data.deferred.some(d => d.topic === id) ? "Отложен" : {invoice:"Оплата",repeat:"Удержание",cross:"Корзина",kes:"Динамика"}[id]}</small>
      <strong>${esc(t.title)}</strong><span>${esc(t.short)}</span></button>`).join("")}
    <section class="note preview"><h3>Ежедневные сигналы</h3><p class="by">Предпросмотр · доставка выключена</p>
      ${overdue.length ? `<p>${button("Открыть проверку " + taskLabel(overdue[0].id), "check", overdue[0].id, "link")}</p>` : '<p class="by">Проверок к сегодняшней дате нет</p>'}
    </section></aside>
    <div><p class="eyebrow">${state.data.external ? "Синтетический сценарий · OpenRouter" : state.data.sample ? "Демонстрационный контур · обезличенные выдержки" : "Рабочий контур · исторические данные"}</p>
    <h1>Что исследуем?</h1><p class="lede">Сверьте данные магазина, наблюдения и интервью. Сохраните решение с проверяемым критерием.</p>
    <form id="question-form" class="panel"><label for="question">Вопрос продукт-менеджера</label>
      <div class="question-row"><input id="question" name="question" maxlength="350" minlength="3" required ${state.data.external ? "readonly" : ""} value="${esc(state.question)}">
      <button class="primary" ${state.waiting ? "disabled" : ""}>${state.waiting ? "Модель разбирает…" : "Исследовать"}</button></div>
      ${state.waiting ? `<p class="waiting feedback" role="status">${state.data.external ? "Qwen через OpenRouter" : "Локальная Qwen"} читает свидетельства и выбирает следующий шаг.</p>` : ""}
      ${messages()}</form>
    ${studied()}
    ${!state.study && !state.waiting ? `<section class="context"><div class="section-heading"><h2>Контекст сигнала</h2><span class="by">${context.length} источника</span></div>
      <div class="grid">${context.map(sourceCard).join("")}</div></section>` : ""}
    <details class="defer"><summary>Отложить сигнал</summary>
      ${active ? `<p>До ${prettyDate(active.until_date)} · ${esc(active.reason)}</p>` : ""}
      <form id="defer" class="panel fields">${field("Вернуть сигнал", "date", "", 'type="date" required')}
      ${field("Причина", "reason", "", 'required maxlength="240"')}<div><button class="secondary">Сохранить срок</button></div></form>
    </details></div></div>`;
}

function backlog(id) {
  const task = state.data.tasks.find(t => t.id === id);
  if (task) return `<div class="wide">${button("← Бэклог", "page", "backlog", "link")}
    <p class="eyebrow">${taskLabel(id)} · ${esc(state.data.tag)}</p>
    <h1>${esc(task.title)}</h1><p class="lede">${esc(task.study_data.question)}</p>
    <section class="panel"><h2>Критерий приёмки</h2><p>${esc(task.criterion)}</p>
      ${task.study_data.topic === "funnel" ? shownRelated(task.study_data) : ""}
      ${task.radar ? `<p><strong>Решение PM</strong> · ${esc(decisionNames[task.radar.kind])}${task.radar.linked ? " · " + esc(task.radar.linked) : ""}</p>
        ${task.radar.note ? `<p>${esc(task.radar.note)}</p>` : ""}
        <p class="by">Условие последующей проверки · ${esc(task.radar.followup)}</p>
        ${task.radar.owner ? `<p class="by">Владелец · ${esc(task.radar.owner)}. Вернуться ${prettyDate(task.radar.due)}.</p>` : ""}
        ${task.radar.finding ? button("Открыть исходную находку","run",task.radar.id,"link") : button("Открыть исследование", "run", task.radar.id, "link")}` : ""}
      <div class="row actions">${button("Открыть связанную проверку", "check", id, "primary")}</div>
      ${state.data.store && task.radar?.finding ? `<details><summary>Экспорт для Redmine${task.radar.linked ? " · "+esc(task.radar.linked) : ""}</summary>
        <p><a class="link" href="/api/task/redmine.csv?id=${id}" download>Скачать CSV для Redmine</a></p>
        <p class="by">В импорте выберите UTF-8 и запятую. Сопоставьте «Тема» и «Описание». В описании сохранены тег, критерий и адрес находки.</p>
      </details>` : task.radar?.linked ? `<p class="by">Локальное дополнение к ${esc(task.radar.linked)}.</p>` : ""}
      ${messages()}</section>
    <section class="context"><h2>Свидетельства в задаче</h2><div class="grid">${task.study_data.evidence.map(sourceCard).join("")}</div></section>
    <details class="panel"><summary>Изменить задачу</summary>
      <form id="edit-task" class="fields">${field("Название", "title", task.title, 'required maxlength="180"')}
      ${area("Критерий приёмки", "criterion", task.criterion, 1200, "required")}
      <div><button class="secondary">Сохранить изменения</button></div></form></details>
    <section class="panel"><h2>Расход на задачу</h2>${usageSummary(task.usage)}</section></div>`;
  return `<div class="wide"><h1>Бэклог</h1>
    <section class="panel"><h2>Задачи после разбора</h2>
    ${state.data.tasks.map(t => `<button class="block-row" type="button" data-task="${t.id}">
      <span class="evidence-id">${taskLabel(t.id)}</span><strong>${esc(t.title)}</strong></button>`).join("") ||
      '<p class="muted">Здесь появятся сохранённые задачи.</p>'}</section>
    <section class="panel"><h2>${state.data.sample ? "Типовые задачи для демонстрации" : "Исходные задачи из Excel"}</h2>
      ${state.data.imported.map(t => {
        const original=state.data.store?.tasks.find(row=>row.id===t.id);
        return `<p class="block-row"><span class="evidence-id">${esc(t.id)}</span>
          ${original ? sourceLink({...original,id:original.source_id}) : `<strong>${esc(t.title)}</strong>`}
           · <span class="muted">${esc(t.status)}</span></p>`;
      }).join("")}</section></div>`;
}

function checkResult(task) {
  const r = task.result;
  return `<section class="panel" id="result"><div class="section-heading"><h2>После релиза</h2>${chip(r ? "Синтетический A/B" : "Ждём данные")}</div>
    ${r ? `<p class="big">${esc(r.outcome)}</p><dl class="summary-grid">
      <div><dt>Основная метрика</dt><dd>${signed(r.delta)} п. п.</dd></div>
      <div><dt>95% интервал</dt><dd>${signed(r.low)} … ${signed(r.high)} п. п.</dd></div>
      <div><dt>Защитная метрика</dt><dd>${signed(r.guard_delta)} п. п.</dd></div>
      <div><dt>Верхняя граница защитной</dt><dd>${signed(r.guard_high)} п. п.</dd></div></dl>
      <p class="by">Разность долей, 95% интервал по методу Ньюкомба. Исторический срез · ожидаем данные.</p>` :
      '<p>Исторический срез · ожидаем данные после релиза.</p><p class="by">Можно подключить синтетический пример в параметрах ниже.</p>'}
    ${task.plan.decision ? `<p class="decision"><strong>Решение PM</strong> · ${esc(task.plan.decision)}</p>` : ""}
    ${messages()}</section>`;
}

function checks(id) {
  const task = state.data.tasks.find(t => t.id === id);
  if (task?.study_data.topic === "funnel" && !["growth","offer"].includes(task.study_data.stage)) return eventCheck(task);
  if (!task) return `<div class="wide"><h1>Проверки</h1><p class="lede">Планы и решения после релиза по задачам бэклога.</p><section class="panel">
    ${state.data.tasks.map(t => button(taskLabel(t.id) + " · " + t.title, "check", t.id, "block-row")).join("") ||
    '<p>Сначала сохраните задачу из разбора.</p>'}</section></div>`;
  const p = task.plan;
  return `<div class="wide">${button("← " + taskLabel(id), "task", id, "link")}<p class="eyebrow">Проверка гипотезы · ${taskLabel(id)}</p>
    <h1>Эффект после релиза</h1><p class="lede">${esc(task.title)}</p>
    ${task.radar?.finding ? `<div class="row">${button("Открыть исходную находку","run",task.radar.id,"link")} ${button("Моя работа", "page", "work", "link")}</div>` : ""}
    <section class="panel"><h2>До релиза</h2><p>${esc(task.criterion)}</p>
      ${task.radar?.followup ? `<p><strong>Условие повторной проверки</strong> · ${esc(task.radar.followup)}</p>` : ""}
      <p class="by">Сначала собрать базовый уровень. Для A/B считать исходы в контрольной и тестовой группах за одно окно.</p>
      <div class="chips">${chip("Цель ≥ " + number(p.target) + " п. п.")}${chip("Защитный порог ≤ " + number(p.guard_max) + " п. п.")}</div></section>
    ${checkResult(task)}
    <form id="check-form" class="panel fields">
      <div class="section-heading"><h2>Параметры проверки</h2><label class="toggle"><input type="checkbox" name="sample" ${p.sample ? "checked" : ""}> Синтетическая выборка</label></div>
      <div class="form-grid">${field("Основная метрика", "metric", p.metric, 'required maxlength="150"')}
        ${field("Минимальный прирост, п. п.", "target", p.target, 'type="number" min="0" max="100" step="0.1" required')}
        ${field("Защитная метрика", "guard", p.guard, 'required maxlength="150"')}
        ${field("Допустимый рост, п. п.", "guard_max", p.guard_max, 'type="number" min="0" max="100" step="0.1" required')}
        ${field("Дата проверки", "date", p.date, 'type="date" required')}</div>
      <details ${p.sample ? "open" : ""}><summary>Численность и исходы синтетических групп</summary><div class="form-grid">
        ${["control","variant"].map((group, i) => `<div class="fields"><h3>${i ? "Тест" : "Контроль"}</h3>
          ${field("Подходящие наблюдения", group + "_n", p[group + "_n"], 'type="number" min="1" required')}
          ${field("Исходы основной метрики", group + "_paid", p[group + "_paid"], 'type="number" min="0" required')}
          ${field("Исходы защитной метрики", group + "_guard", p[group + "_guard"], 'type="number" min="0" required')}</div>`).join("")}</div></details>
      ${area("Решение PM", "decision", p.decision, 700)}
      <div><button class="primary">Сохранить и пересчитать</button></div>
    </form></div>`;
}

function sources() {
  const mode = state.sourceMode || "research";
  const research = state.data.research;
  return `<div class="wide"><h1>Источники</h1>
    <div class="row actions">${button("Исторические материалы", "source-mode", "research", mode === "research" ? "primary" : "secondary")}
      ${button("Демонстрационная CRM и платежи", "source-mode", "crm", mode === "crm" ? "primary" : "secondary")}
      ${button("Тестовый счётчик Яндекс.Метрики", "source-mode", "metrika", mode === "metrika" ? "primary" : "secondary")}</div>
    ${messages()}
    ${mode === "research" ? `<section class="context"><div class="section-heading"><h2>Библиотека свидетельств</h2>
      <span class="by">${state.data.facts.length} исходных · ${research.length} добавлено</span></div>
      <div class="grid">${state.data.facts.map(sourceCard).join("")}</div></section>
      ${research.length ? `<details class="panel"><summary>Добавленные исследования (${research.length})</summary>
      <div class="grid">${research.map(sourceCard).join("")}</div></details>` : ""}
      ${!state.data.jury && !state.data.external ? researchForm() : ""}` : ""}
    ${mode === "crm" ? `<section class="panel"><h2>Сверка оплаченных заказов</h2><p class="muted">Синтетические заказы, платежи и возвраты.</p>
      <div class="table-wrap"><table><thead><tr><th>Когорта</th><th>Самостоятельно</th><th>С менеджером</th><th>Всего</th><th>Чистые поступления</th></tr></thead><tbody>
      ${state.data.crm.map(r => `<tr><td>${esc(r.cohort)}</td><td>${r.store}</td><td>${r.manager}</td><td>${r.total}</td><td>${number(r.net_rub)} ₽</td></tr>`).join("")}</tbody></table></div></section>` : ""}
    ${mode === "metrika" ? `<section class="panel"><h2>Тестовый счётчик участника</h2><p class="muted">Отдельное подключение API. История магазина загружена из Excel.</p>
      <div class="row actions">${button("Проверить подключение", "metrika", "check", "primary")}
      <span id="metrika-status" role="status"></span></div></section>` : ""}</div>`;
}

function researchForm() {
  return `<details class="panel"><summary>Добавить исследование</summary>
  <form id="research-form" class="fields"><div class="form-grid">
    <label>Тема<select name="topic">${Object.entries(state.data.topics).map(([id,t]) => `<option value="${id}">${esc(t.title)}</option>`).join("")}</select></label>
    ${field("Название", "title", "", 'maxlength="120" required')}
    ${field("Источник и место в документе", "source", "", 'maxlength="160" required')}
    ${field("Версия", "version", "", 'maxlength="60" required')}
    ${field("Дата", "date", state.data.today, 'type="date" required')}</div>
    ${area("Обезличенная выдержка", "text", "", 1000, "required")}
    <div><button class="primary">Добавить источник</button></div></form>
    <form id="research-bulk" class="fields panel"><h3>Загрузка набора</h3>
      <p class="by">До 1000 записей в JSON-массиве. Поля topic, title, source, version, date, text. Темы invoice, repeat, cross, kes.</p>
      <label>JSON-файл<input type="file" accept=".json,application/json" name="file" required></label>
      <div><button class="secondary">Загрузить набор</button></div></form></details>`;
}

function usagePage() {
  const journal = state.journal;
  return `<div class="wide"><h1>Журнал модели</h1><p class="lede">Фактический расход разборов по данным ${state.data.external ? "OpenRouter" : "локальной модели"}.</p>
    ${messages()}
    ${journal ? `<section class="recommend"><h2>Расход на показанные вызовы</h2>${usageSummary(journal.usage)}</section>
      <section class="panel"><h2>Последние вызовы</h2><div class="table-wrap"><table><thead><tr><th>Вызов</th><th>Сценарий</th><th>Модель</th><th>Вход</th><th>Выход</th><th>Время</th>${state.data.external ? "<th>Списано, USD</th>" : ""}<th>Статус</th></tr></thead>
      <tbody>${journal.calls.map(r => `<tr><td>#${r.id}</td><td>${esc(state.data.topics[r.scenario]?.title || r.scenario)}
      ${r.finding ? `<div>${button("Открыть исходную находку","run",r.study,"link")}</div>` : ""}</td><td>${esc(r.model)}</td><td>${r.prompt_tokens ?? "—"}</td><td>${r.completion_tokens ?? "—"}</td><td>${r.elapsed_ms == null ? "—" : seconds(r.elapsed_ms)}</td>
      ${state.data.external ? `<td>${esc(r.actual_cost ?? "—")}</td>` : ""}<td>${esc(callStatus[r.status])}</td></tr>`).join("")}</tbody></table></div></section>` : '<p class="feedback">Открываю журнал…</p>'}
      <p class="by footer">${state.data.external ? "Стоимость берётся из ответа OpenRouter." : "Локальная плата за API · 0 RUB. Электричество и амортизация Beelink отдельно, замера нет."} Токены разработки Codex в этот журнал не входят.</p></div>`;
}

function render() {
  if (!state.data) return;
  const sampleNote = document.querySelector("#sample-note");
  sampleNote.hidden = !state.data.demo_store;
  if (state.data.cloud_research) sampleNote.textContent =
    "Учебный набор · показатели, интервью и бэклог вымышлены. Исследование выполняет Qwen3‑32B через OpenRouter.";
  else if (state.data.store?.demo) sampleNote.textContent =
    "Стенд жюри · согласованные агрегаты BI и веб-аналитики. Остальные материалы и бэклог — учебные.";
  const [page, id] = route();
  if (page==="funnel") restoreFunnelView(id);
  nav.querySelector('[data-page="funnel"]').textContent = state.data.store ? "Обзор магазина" : "Воронка";
  nav.hidden = false;
  document.querySelector("#task-count").textContent = state.data.tasks.length;
  for (const item of nav.querySelectorAll("button")) {
    const active = item.dataset.page === page || (item.dataset.page === "work" && ["backlog","checks","usage","activity"].includes(page));
    item.hidden = ((item.dataset.page === "funnel" || radarPages.includes(item.dataset.page)) && !state.data.funnel) ||
                  (Boolean(state.data.funnel) && ["signals","backlog","checks","sources","usage"].includes(item.dataset.page));
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  app.innerHTML = {funnel: showFunnel, signals, backlog, checks, sources, usage: usagePage,
    deviation:openDeviation, research:researchPage, activity:activityPage, work:workPage, astra:astraPage, growth:growthPage, catalog:catalogPage,lk:lkPage}[page](id);
  const detailPath = radarDetailPath(page,id);
  if (detailPath && !state.error && !detailForRoute()) void loadRadarDetail(detailPath);
  if (page === "funnel" && !funnelView.report && !state.error) void loadFunnel();
  if (page === "usage" && !state.loadingJournal && !state.journal) {
    state.loadingJournal = true;
    api("usage").then(journal => { state.journal = journal; render(); })
      .catch(error => { state.error = error.message; render(); })
      .finally(() => { state.loadingJournal = false; });
  }
}

async function boot() {
  const fragment = location.hash.slice(1);
  const token = new URLSearchParams(fragment).get("invite");
  if (token) {
    history.replaceState(null, "", location.pathname);
    try { await api("invite", {token}); }
    catch (error) { state.error = error.message; }
  }
  try { await refresh(); render(); void pollRadar(); }
  catch (error) {
    state.data = null;
    radarView.runs = [];
    renderRadarNotice();
    nav.hidden = true;
    app.innerHTML = `<div class="wide"><h1>${error.status === 401 ? "Доступ для жюри" : "Прототип недоступен"}</h1><p class="lede">${esc(state.error || error.message)}</p></div>`;
  }
}

window.addEventListener("hashchange", () => {
  state.error = "";
  state.notice = "";
  if (new URLSearchParams(location.hash.slice(1)).has("invite")) {
    void boot();
    return;
  }
  render();
});
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.addEventListener("click", async event => {
  const d = event.target.closest("button")?.dataset;
  if (!state.data || !d) return;
  if (d.page) {
    state.journal=null;
    go(d.page, d.page==="funnel" && state.data.store ? overviewBack() : undefined);
  }
  if (d.task) { if (dialog.open) dialog.close(); go("backlog", d.task); }
  if (d.check) go("checks", d.check);
  if (d.fact) openSource(d.fact);
  if (d.deviation) go("deviation",d.deviation,overviewNavigation());
  if (d.astra) go("astra",d.astra,overviewNavigation());
  if (d.officePrices) go("catalog",d.officePrices,{...overviewNavigation(),tab:"prices"});
  if (d.funnelBack) go("funnel",d.funnelBack);
  if (d.catalog) go("catalog", d.catalog);
  if (d.finding) go("growth", d.finding);
  if (d.findingDecision !== undefined) document.querySelector("#finding-decision")?.focus();
  if (d.run) void openRun(d.run);
  if (d.radarDismiss) { radarView.dismissed.add(d.radarDismiss); renderRadarNotice(); }
  if (d.radarRetry) {
    try { await retryRadar(); }
    catch (error) { state.error = error.message; render(); }
  }
  if (d.funnelStage) {
    const previous=overviewRef();
    funnelView.stage = state.data.store && funnelView.stage===d.funnelStage ? "all" : d.funnelStage;
    rememberFunnelView(previous);
    state.error = "";
    render();
  }
  if (d.funnelStudy !== undefined) void runFunnelStudy();
  if (d.topic && !state.waiting) {
    Object.assign(state, {topic: d.topic, question: state.data.topics[d.topic].question, study: null, error: "", notice: ""});
    render();
  }
  if (d.sourceMode) { state.sourceMode = d.sourceMode; render(); }
  if (d.metrika) {
    const status = document.querySelector("#metrika-status");
    status.textContent = "Запрашиваю статус…";
    try {
      const m = await api("metrika");
      status.textContent = m.configured ? `${number(m.visits)} визитов · ${m.from} — ${m.to}` : m.message;
    } catch (error) { status.textContent = error.message; }
  }
});

app.addEventListener("change", event => {
  if (event.target.matches("#funnel-filters select")) changeFunnelFilter(event.target.name, event.target.value);
  if (event.target.matches(".overview-toolbar select[name=product]")) changeFunnelFilter("product",event.target.value);
  if (event.target.matches("#funnel-filters [name=full_weeks]")) changeFunnelFilter("after",event.target.checked ? "oct" : "oct_partial");
});
app.addEventListener("toggle",event=>{
  if (event.target.id==="overview-filters") funnelView.filtersOpen=event.target.open;
},true);
app.addEventListener("input", event => {
  if (event.target.id === "catalog-query") {
    state.catalogQuery = event.target.value;
    document.querySelector("#catalog-matches").innerHTML = catalogMatches();
  }
});

app.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  const fields = Object.fromEntries(new FormData(form));
  const [page, id] = route();
  const submit = event.submitter || form.querySelector("button");
  submit.disabled = true;
  state.error = state.notice = "";
  try {
    if (form.id === "cloud-run-form") {
      await startRadar({...detailForRoute().filter,mode:form.dataset.mode,
        ...(form.dataset.previous ? {previous:form.dataset.previous} : {})});
    } else if (form.id === "radar-start-form") {
      await startRadar({...detailForRoute().filter, mode:form.dataset.mode, question:fields.question});
    } else if (form.id === "radar-growth-form") {
      await startRadar({mode:"growth", question:fields.question || ""});
    } else if (form.id === "radar-astra-form") {
      await startRadar({...detailForRoute().filter, mode:"stage", stage:form.dataset.stage || "license"});
    } else if (["radar-decision","radar-defer","radar-segment"].includes(form.id)) {
      const kind = submit.dataset.decision || form.id.split("-")[1];
      const resolution = await api("radar/resolve",{...fields,id:form.dataset.runId || id,kind});
      if (resolution.task) await refresh();
      await loadRadarDetail(radarDetailPath(page,id), true);
      void pollRadar();
      return;
    } else if (form.id === "question-form") {
      const defaultQuestion = state.data.topics[state.topic].question;
      Object.assign(state, {question: fields.question, study: null, waiting: true, journal: null});
      render();
      state.study = await api("study", {question: fields.question, topic: fields.question === defaultQuestion ? state.topic : null});
      state.topic = state.study.topic;
    } else if (form.id === "create-task" || form.id === "edit-task") {
      const edit = form.id === "edit-task";
      const studyId = edit ? state.data.tasks.find(t => t.id === id).study : state.study.id;
      const task = await api("task", {...fields, study:studyId, edit});
      await refresh();
      go("backlog", task.id);
      state.notice = "Сохранено в " + taskLabel(task.id);
    } else if (form.id === "check-form") {
      for (const input of form.querySelectorAll('input[type="number"]')) fields[input.name] = input.valueAsNumber;
      const response = await api("check", {...fields, id, sample:fields.sample === "on"});
      Object.assign(state.data.tasks.find(t => t.id === id), response);
      state.notice = "Параметры сохранены. Результат пересчитан.";
    } else if (form.id === "event-check-form") {
      const response = await api("check", {...fields, id});
      Object.assign(state.data.tasks.find(t => t.id === id), response);
      state.notice = "Результат проверки сохранён.";
    } else if (form.id === "research-form" || form.id === "research-bulk") {
      const items = form.id === "research-form" ? [fields] : JSON.parse(await fields.file.text());
      const result = await api("research", {items});
      await refresh();
      state.notice = "Добавлено источников · " + result.added;
    } else if (form.id === "defer") {
      await api("defer", {...fields, topic:state.topic});
      await refresh();
      state.notice = "Сигнал отложен до " + prettyDate(fields.date);
    }
  } catch (error) {
    if (error.status === 401) return boot();
    state.error = error.message;
    if (form.isConnected && form.id !== "question-form") {
      form.querySelector(".submit-error")?.remove();
      const feedback = document.createElement("p");
      feedback.className = "error submit-error";
      feedback.setAttribute("role", "alert");
      feedback.textContent = state.error;
      form.append(feedback);
      submit.disabled = false;
      return;
    }
  } finally {
    if (form.id === "question-form") state.waiting = false;
  }
  render();
  if (["check-form", "event-check-form"].includes(form.id)) document.querySelector("#result")?.scrollIntoView({block:"nearest"});
  if (form.id === "create-task" && page === "signals") window.scrollTo(0, 0);
});

boot();
setInterval(pollRadar, 2000);
