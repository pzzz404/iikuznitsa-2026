"use strict";

const radarView = {runs: [], details: null, detailKey: null, pending: null, polling: false};
const radarPages = ["deviation", "research", "activity", "astra", "growth", "catalog"];
const radarStates = {queued:"В очереди",running:"Выполняется",done:"Завершено",failed:"Ошибка"};
const decisionNames = {link:"Связать проверку с задачей",new:"Утвердить новую задачу",defer:"Отложить"};
const modelActions = {event:"Сверить действие и событие",reproduce:"Воспроизвести шаг",
  join:"Проверить общий идентификатор",pilot:"Сравнить способы повторной закупки"};
const nextReleaseCheck = "После исправления сверить совпадение действия и события. Затем сравнить полные недели с сопоставимым входом.";
const hDate = new Intl.DateTimeFormat("ru-RU",{dateStyle:"short",timeStyle:"short",timeZone:"Europe/Moscow"});

function deviationRef(filter) {
  return [filter.family,filter.before,filter.after,filter.device,filter.audience].join(".");
}

function deviationArgs(ref) {
  const [family,before,after,device,audience] = String(ref).split(".");
  return {family,before,after,device,audience};
}

function radarDetailPath(page, ref) {
  if (page === "deviation") return "radar/deviation?" + new URLSearchParams(deviationArgs(ref));
  if (page === "research") return "radar/run?" + new URLSearchParams({id:ref});
  if (page === "astra") return "funnel?family=astra&before=oct12&after=oct19";
  return null;
}

function detailForRoute() {
  const [page, ref] = route();
  const path = radarDetailPath(page, ref);
  return path && radarView.detailKey === path ? radarView.details : null;
}

async function loadRadarDetail(path, force=false) {
  if (radarView.pending === path || (!force && radarView.detailKey === path)) return;
  const request = Symbol();
  radarView.request = request;
  radarView.pending = path;
  try {
    const info = await api(path);
    if (radarView.request !== request) return;
    radarView.details = info;
    radarView.detailKey = path;
    state.error = "";
  } catch (error) {
    if (radarView.request !== request) return;
    if (error.status === 401) return boot();
    state.error = error.message;
  } finally {
    if (radarView.request === request) radarView.pending = null;
  }
  if (path === radarDetailPath(...route())) render();
}

function relatedCard(item) {
  return item ? `<div class="radar-related"><strong>Связанный бэклог</strong>
    ${button(item.id + " · " + item.title, "radar-related", item.id, "link")} ${chip(item.status)}</div>` : "";
}

function auditInfo(item) {
  const options = state.data.funnel;
  const f = item.filter;
  return `<details class="panel radar-math"><summary>Как посчитано</summary>
    <p>${esc(options.windows[f.before].label)} и ${esc(options.windows[f.after].label)}. В каждом окне ${item.weeks} полных недель.
      Среднее недельных индексов. Для каждого семейства база 100 — 04.05–28.06.2026.</p>
    <p class="muted">Индекс не содержит абсолютных заказов, оплат или рублей. Для общего индекса магазина нужны веса по базовым объёмам.</p>
    <p class="by">${esc(item.source)}. ${item.jury ? "Покрытие демо включает согласованные агрегаты." : "Покрытие исходной книги: два семейства."}</p>
  </details>`;
}

function openDeviation() {
  const item = detailForRoute();
  if (!item) return `<h1>Отклонение в заказах</h1>${radarLoading()}`;
  const f = item.filter;
  const i = item.index;
  const label = `Самостоятельные заказы ${item.family} ${i.change < 0 ? "↓" : "↑"} ${number(Math.abs(i.change))}%`;
  const scope = item.scope["периоды"].join(" и ");
  const relatedRuns = radarView.runs.filter(r=>r.mode==="release"&&deviationRef(r.filter)===deviationRef(f));
  return `<div class="wide radar-page">${button("← Воронка", "page", "funnel", "link")}
    <p class="eyebrow">Самостоятельный заказ · ${esc(scope)} · ${item.weeks} полных недель в каждом окне</p>
    <h1>${esc(label)}</h1><p class="lede">Индекс BI ${number(i.before)} → ${number(i.after)}. В выгрузке индексы двух семейств.</p>
    <section class="panel"><h2>Первичная сверка</h2>
      ${item.compare ? `<p>${esc(item.compare_name)} за те же недели · <strong>${signed(item.compare.change)}%</strong> (${number(item.compare.before)} → ${number(item.compare.after)}).</p>` : ""}
      <p>${esc(prettyDate(item.login).slice(0,5))} изменился вход, ${esc(prettyDate(item.released).slice(0,5))} выпущены фильтры подбора Kaspersky. Сопоставимость визитных долей через смену входа ограничена.</p>
      ${relatedCard(item.related)}<p class="by">Для Kaspersky нет ряда добавлений из конфигуратора. Причина снижения заказов пока открыта.</p>
    </section>
    <section class="panel"><h2>Что ещё могло повлиять</h2>
      <ul class="radar-versions"><li>Сбой после выбора лицензии.</li><li>Пропуск события при работающей корзине.</li>
      <li>Изменение состава визитов после смены входа.</li></ul>
      <p class="muted">Интервью и конкурентное исследование не подтверждают ни одну из этих причин для данного отклонения.</p>
    </section>
    <form class="recommend fields" id="radar-start-form" data-mode="release">
      <label>Уточнение к исследованию<textarea name="question" maxlength="220" placeholder="Необязательно"></textarea></label>
      <div class="row"><button class="primary">Проверить связь с релизом конфигуратора</button></div>
      ${messages()}
    </form>
    ${relatedRuns.length ? `<section class="panel"><h2>История этого отклонения</h2>${relatedRuns.map(runRow).join("")}</section>` : ""}
    <details class="panel"><summary>Источники первичной сверки</summary>
      <div class="grid">${item.evidence.map(sourceCard).join("")}</div></details>
    ${auditInfo(item)}</div>`;
}

function radarLoading() {
  return state.error ? messages() : '<p class="feedback" role="status">Открываю данные…</p>';
}

function runTitle(run) {
  return run.mode === "release" ? "Связь заказов Kaspersky с релизом подбора" :
    run.mode === "growth" ? "Повторная закупка из письма" : run.scope["семейство"] + " · " + run.scope["этап"];
}

function runRow(run) {
  return `<div class="radar-run-row"><div><strong>${esc(runTitle(run))}</strong>
    <span class="by">${esc(hDate.format(new Date(run.created)))} · ${esc(radarStates[run.status])}</span></div>
    ${button(run.status === "done" ? "Посмотреть результат" : "Открыть исследование", "run", run.id, "link")}</div>`;
}

function activityPage() {
  return `<div class="wide"><h1>Исследования</h1><section class="panel">
    ${radarView.runs.length ? radarView.runs.map(runRow).join("") : '<p class="muted">Запустите разбор из карточки отклонения. Готовый результат появится здесь.</p>'}
  </section></div>`;
}

function resolutionView(result) {
  if (!result) return "";
  return `<section class="panel radar-resolution"><h2>Решение PM</h2>
    <p><strong>${esc(decisionNames[result.kind])}${result.linked ? " · " + esc(result.linked) : ""}</strong></p>
    ${result.note ? `<p>${esc(result.note)}</p>` : ""}
    ${result.followup ? `<p class="by">Условие последующей проверки · ${esc(result.followup)}</p>` : ""}
    ${result.task ? button("Открыть " + taskLabel(result.task), "task", result.task, "primary") : ""}
  </section>`;
}

function researchPage() {
  const run = detailForRoute();
  if (!run) return `<h1>Исследование</h1>${radarLoading()}`;
  const back = run.mode === "release" ? button("← Отклонение", "deviation", deviationRef(run.filter), "link") :
    button("← Исследования", "page", "activity", "link");
  const status = radarStates[run.status];
  const scope = Object.values(run.scope).flat().join(" · ");
  const head = `<div class="wide radar-page">${back}<p class="eyebrow">Исследование ${esc(run.id.slice(0,8))} · ${esc(status)}</p>
    <h1>${esc(runTitle(run))}</h1><p class="lede">${esc(scope)}</p>`;
  if (run.status !== "done") return `${head}<section class="panel"><h2>${esc(status)}</h2>
    <p>${esc(run.error || "Можно перейти в другой раздел. Уведомление появится после готового результата.")}</p>
    ${run.status === "failed" ? button("Повторить исследование", "radar-retry", run.id, "primary") : ""}${messages()}
  </section></div>`;
  const item = run.result;
  const followup = run.mode === "release" ? nextReleaseCheck : "Вернуться к решению после получения и проверки исходов выбранного сценария.";
  const resolved = run.resolution ? resolutionView(run.resolution) : `<form id="radar-decision" class="panel fields">
    <h2>Решение PM</h2>
    ${field("Название проверки", "title", item.action, 'required maxlength="180"')}
    ${area("Критерий приёмки", "criterion", item.criterion, 1200, "required")}
    ${area("Условие последующей проверки", "followup", followup, 700, "required")}
    ${field("Комментарий PM", "note", "", 'maxlength="700"')}
    <div class="row">
      ${item.related || item.candidate ? '<button class="primary" data-decision="link">Связать проверку с T-08</button>' : ""}
      <button class="${item.related || item.candidate ? "secondary" : "primary"}" data-decision="new">Утвердить новую задачу</button>
      ${chip(state.data.tag)}
    </div>
  </form><details class="panel"><summary>Отложить</summary><form id="radar-defer" class="fields">
    ${area("Причина или условие возвращения", "note", "", 700, "required")}
    <div><button class="secondary">Сохранить причину</button></div>
  </form></details>`;
  return `${head}<p class="by">Готово ${esc(hDate.format(new Date(run.finished)))} МСК</p>
    <section class="panel"><div class="section-heading"><h2>Доказательства и неопределённость</h2>${chip(item.model)}</div>
      <div class="grid radar-evidence">${item.evidence.map((fact,index)=>`<div>
        <h3>${index===0 ? "Наблюдение" : "Ограничение"}</h3>${sourceCard(fact)}</div>`).join("")}</div>
      <p>${esc(item.confirmation)}</p>
      ${modelActions[item.recommended_check] ? `<p><strong>Первый шаг по модели</strong> · ${esc(modelActions[item.recommended_check])}</p>` : ""}
      ${relatedCard(item.related)}
      ${!item.related && item.candidate ? `<p class="by">Кандидат из первичной сверки</p>${relatedCard(item.candidate)}` : ""}
      <p class="by">${esc(item.historical_result)}</p>
      ${run.mode === "release" ? "<p>Если корзина работает, а событие пропадает, исправить учёт. Если сбой действия воспроизведён, оценить исправление или откат. При пробеле в доказательствах отложить решение до сверки.</p>" : ""}
      <details><summary>Фактический расход модели</summary>${usageSummary(item.usage)}</details>
    </section>
    ${messages()}${resolved}</div>`;
}

function growthPage() {
  return `<div class="wide">${button("← Воронка", "page", "funnel", "link")}
    <p class="eyebrow">Возможности роста · весь магазин</p><h1>Повторная закупка из письма</h1>
    <p class="lede">Гипотеза для продлеваемых лицензий. Размер аудитории и эффект на оплаты неизвестны.</p>
    <section class="panel"><h2>Основания</h2><div class="grid">${state.data.growth.map(sourceCard).join("")}</div></section>
    <details class="panel"><summary>Открыть черновик проверки</summary>
      <p>Сравнить путь из письма и из истории у покупателей с продлеваемыми лицензиями. Измерить завершение повтора и ошибки выбора.</p>
      <form id="radar-growth-form" class="row actions"><button class="primary">Исследовать гипотезу</button></form>
    </details>${messages()}</div>`;
}

function astraPage() {
  const data = detailForRoute();
  if (!data) return `<h1>Подбор Astra</h1>${radarLoading()}`;
  const first = data.steps.before[0];
  const second = data.steps.after[0];
  const left = data.visits.before.desktop;
  const right = data.visits.after.desktop;
  return `<div class="wide">${button("← Воронка", "page", "funnel", "link")}
    <p class="eyebrow">Подбор · Astra · 12–18.10 и 19–25.10</p>
    <h1>Где меняется прохождение?</h1>
    <section class="panel"><h2>Шаг 1 → 2 · все устройства</h2>
      <p><strong>12–18.10</strong> · ${first ? ratio(first) : "Нет пары счётчиков"}</p>
      <p><strong>19–25.10</strong> · ${second ? ratio(second) : "Нет пары счётчиков"}</p>
      <p class="by">Softline v17 · Метрики_данные · cfg_step_dropoff, визиты достигших шагов.</p>
      ${left && right ? `<p>На десктопе вход на страницы семейства снизился с ${left.total} до ${right.total} визитов.</p>` : ""}
      <p>Проверить вход до первого шага. По переходу 1 → 2 нет основания переделывать подбор.</p>
    </section>
    <details class="panel"><summary>Открыть разбивку по устройствам</summary>
      ${["before","after"].map((key,i)=> `<h3>${i===0 ? "12–18.10" : "19–25.10"}</h3>${Object.entries(data.visits[key]).map(([device,v])=>
        `<p>${esc(state.data.funnel.devices[device])} · ${v.total} визитов · ${v.days}/${v.expected} дней</p>`).join("")}`).join("")}
      <p class="by">Softline v17 · Метрики_данные · cfg_family_views. У перехода между шагами поля устройства нет.</p>
    </details>
    <form id="radar-astra-form" class="panel"><button class="primary">Проверить вход в подбор Astra</button></form>${messages()}</div>`;
}

function catalogPage(id) {
  const selected = state.data.catalog[id];
  if (selected) return `<div class="wide">${button("← Каталог", "page", "catalog", "link")}
    <p class="eyebrow">${esc(selected.stage)}</p><h1>${esc(selected.title)}</h1>
    <section class="panel"><h2>Доступные материалы</h2><p>${esc(selected.text)}</p><p class="by">${esc(selected.source)}</p>
    <p class="note">Нет истории заказов в выгрузке. Количественное сравнение семейств недоступно.</p></section></div>`;
  return `<div class="wide"><h1>Каталог</h1><p class="lede">Покрытие зависит от семейства и этапа.</p>
    <section class="panel"><h2>Количественные ветки</h2>
      <div class="row">${button("Kaspersky · самостоятельные заказы", "deviation", "kes.aug.oct.all.all")}
        ${button("Astra · прохождение подбора", "page", "astra")}</div></section>
    <section class="panel"><h2>Товары с качественными материалами</h2>
      ${Object.entries(state.data.catalog).map(([key,item])=>button(item.title, "catalog", key, "block-row")).join("")}
    </section></div>`;
}

function renderRadarNotice() {
  const aside = document.querySelector("#radar-notice");
  const count = document.querySelector("#radar-count");
  const ready = radarView.runs.filter(run=>run.status==="done"&&!run.seen);
  const run = ready[0];
  count.textContent = ready.length ? String(ready.length) : "";
  aside.hidden = !state.data || !run;
  aside.innerHTML = !aside.hidden ? `<strong>Исследование завершено</strong><p>${esc(runTitle(run))}</p>
    ${button("Посмотреть результат", "run", run.id, "link")}` : "";
}

async function pollRadar() {
  if (!state.data?.funnel || radarView.polling) return;
  radarView.polling = true;
  try {
    const previous = JSON.stringify(radarView.runs);
    radarView.runs = await api("radar/runs");
    renderRadarNotice();
    const [page, id] = route();
    if (page==="activity" && JSON.stringify(radarView.runs)!==previous) render();
    const current = radarView.runs.find(run=>run.id===id);
    if (page==="research" && current && detailForRoute()?.status!==current.status)
      void loadRadarDetail(radarDetailPath(page,id), true);
  } catch (error) {
    if (error.status===401) void boot();
  } finally { radarView.polling = false; }
}

async function openRun(id) {
  go("research",id);
  try {
    await api("radar/seen",{id});
    await pollRadar();
  } catch(error) { if (error.status===401) void boot(); }
}

async function startRadar(payload) {
  const run = await api("radar/start",payload);
  await openRun(run.id);
}

async function retryRadar() {
  const run = detailForRoute();
  if (!run || run.status!=="failed") return;
  const question = run.question?.split(" Уточнение PM: ").slice(1).join(" Уточнение PM: ") || "";
  await startRadar({...run.filter,mode:run.mode,stage:run.stage,question});
}
