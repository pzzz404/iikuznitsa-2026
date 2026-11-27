"use strict";

const radarView = {runs:[],details:null,detailKey:null,pending:null,polling:false,dismissed:new Set()};
const radarPages = ["deviation", "research", "activity", "work", "astra", "growth", "catalog", "lk"];
const radarStates = {queued:"В очереди",running:"Выполняется",done:"Завершено",failed:"Ошибка"};
const decisionNames = {link:"Связать проверку с задачей",new:"Утвердить проверку",segment:"Уточнить сегмент",defer:"Отложить"};
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
  if (page === "deviation") {
    const [filter,run] = String(ref).split("~");
    return "radar/deviation?" + new URLSearchParams({...deviationArgs(filter), ...(run ? {run} : {})});
  }
  if (page === "research") return "radar/run?" + new URLSearchParams({id:ref});
  if (page === "astra") {
    if (!ref || !state.data.store) return "funnel?family=astra&before=oct12&after=oct19";
    const [scope,run]=ref.split("~");
    const [finding,...pieces]=scope.split(".");
    return "radar/astra?" + new URLSearchParams({finding,...deviationArgs(pieces.join(".")),...(run ? {run} : {})});
  }
  if (page === "growth" && ref?.split("~")[0] === state.data.growth.key)
    return "radar/finding?" + new URLSearchParams({id:ref.split("~")[1] || ""});
  if (page === "catalog" && state.data.store && ref?.split("~")[0] === "office")
    return "radar/office?" + new URLSearchParams({run:ref.split("~")[1] || ""});
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

function auditInfo(item) {
  const options = state.data.funnel;
  const f = item.filter;
  return `<details class="panel radar-math"><summary>Как посчитано</summary>
    <p>${esc(options.windows[f.before].label)} и ${esc(options.windows[f.after].label)}.
      ${item.coverage ? "Покрытие: " + item.coverage.before + " и " + item.coverage.after + " недель" +
        (item.coverage.partial ? ", последняя неполная." : ", полные окна.") : "В каждом окне " + item.weeks + " полных недель."}
      Среднее недельных индексов. Для каждого семейства база 100 — 04.05–28.06.2026.</p>
    <p class="muted">Индекс не содержит абсолютных заказов, оплат или рублей. Для общего индекса магазина нужны веса по базовым объёмам.</p>
    <p class="by">${esc(item.source)}. ${item.synthetic ? "Учебные ряды по двум семействам." :
        item.jury ? "Покрытие демо включает согласованные агрегаты." : "Покрытие исходной книги: два семейства."}</p>
    ${item.definition ? item.evidence.filter(s=>s.id.startsWith("sales-")).map(s=>sourceLink(s,
      (item.jury ? "Агрегат · " : "Строки «Продаж» · ")+(s.id==="sales-kes"?"Kaspersky":"Astra"))).join(" · ") +
      " · " + sourceLink(item.definition,"Определение индекса") : ""}
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
  const readyToStart = !state.data.cloud_research || deviationRef(f) === deviationRef(state.data.funnel.defaults);
  return `<div class="wide radar-page">${state.data.store ? button("← Обзор магазина","funnel-back",overviewBack(f),"link") :
    button("← Воронка","funnel-back",deviationRef(f)+"~order","link")}
    <p class="eyebrow">Самостоятельный заказ · ${esc(scope)}${item.coverage?.partial ? " · включает неполную неделю" : ""}${item.jury ? " · агрегаты для жюри" : ""}</p>
    <h1>${esc(label)}</h1><p class="lede">Индекс BI ${number(i.before)} → ${number(i.after)}. В выгрузке индексы двух семейств.</p>
    ${state.data.cloud_research && readyToStart ? cloudRunButton("release",item.run) :
      state.data.store && !item.run && readyToStart ? `<form class="row actions" id="radar-start-form" data-mode="release">
      <button class="primary">Исследовать Kaspersky с Qwen</button></form>` : ""}
    ${!readyToStart ? '<p class="note">Облачное исследование доступно для исходных двух шестинедельных окон.</p>' : ""}
    ${messages()}${state.data.store && item.run ? projectResult(item.run) : ""}
    <section class="panel"><h2>Первичная сверка</h2>
      ${item.compare ? `<p>${esc(item.compare_name)} за те же недели · <strong>${signed(item.compare.change)}%</strong> (${number(item.compare.before)} → ${number(item.compare.after)}).</p>` : ""}
      <p>${esc(prettyDate(item.login).slice(0,5))} изменился вход, ${esc(prettyDate(item.released).slice(0,5))} выпущены фильтры подбора Kaspersky. Сопоставимость визитных долей через смену входа ограничена.</p>
      <p class="by">Для Kaspersky нет ряда добавлений из конфигуратора. Причина снижения заказов пока открыта.</p>
      ${item.reach ? `<p>Выбрали хотя бы одну опцию · ${ratio(item.reach)} визитов.
        Покрытие ${item.reach.rows} из ${item.reach.expected_rows} сочетаний день × устройство.</p>` : ""}
      ${item.reach_full && f.device === "all" ? `<p class="by">С запуска фильтров ${prettyDate(item.reach_full.since).slice(0,5)}
        по ${prettyDate(state.data.store.coverage.metrics_to).slice(0,5)} · ${ratio(item.reach_full)} визитов по доступным строкам.</p>` : ""}
    </section>
    ${item.series ? chartSeries(item.series,item.events,item.filter) : ""}
    <section class="panel"><h2>Что ещё могло повлиять</h2>
      <ul class="radar-versions"><li><strong>Сбой пути.</strong> Проверить фактическое содержимое корзины после выбора. Сейчас ряда добавлений KES нет.
        ${item.customer_evidence?.[3] ? sourceLink(item.customer_evidence[3],"Контрпример · продление Cloud онлайн") : ""}</li>
        <li><strong>Потеря события.</strong> Возможна при работающей корзине. Пропуск Метрики сам по себе не объясняет снижение независимого индекса BI.
        ${item.cart_definition ? sourceLink(item.cart_definition,"Определение счётчика корзины") : ""}</li>
        <li><strong>Переход к менеджеру.</strong> Для подтверждения сдвига нужны два ряда заказов за те же недели.
        ${item.customer_evidence?.[0] ? sourceLink(item.customer_evidence[0],"Интервью · канал покупки KES") : ""}</li></ul>
      <p class="muted">${item.jury ? "Выборка жюри содержит согласованные агрегаты. Первичные интервью и замеры конкурентов доступны только в закрытом контуре." : "Интервью и конкурентное исследование не подтверждают ни одну из этих причин для данного отклонения."}</p>
    </section>
    ${!state.data.store ? `<form class="recommend fields" id="radar-start-form" data-mode="release">
      <label>Уточнение к исследованию<textarea name="question" maxlength="220" placeholder="Необязательно"></textarea></label>
      <div class="row"><button class="primary">Проверить связь с релизом конфигуратора</button></div>
      ${messages()}
    </form>` : ""}
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
    run.mode === "office" ? "Предложение Office Home and Business 2024" :
    run.mode === "growth" ? state.data.growth.title : run.scope["семейство"] + " · " + run.scope["этап"];
}

function runRow(run) {
  const label = run.status === "done" ? runTitle(run) + " · результат" : runTitle(run) + " · " + radarStates[run.status];
  return `<div class="radar-run-row"><div><strong>${esc(runTitle(run))}</strong>
    <span class="by">${esc(hDate.format(new Date(run.created)))} · ${esc(radarStates[run.status])}</span></div>
    <button type="button" class="link" data-run="${esc(run.id)}" aria-label="${esc(label)}">
      ${run.finding ? "Открыть находку" : run.status === "done" ? "Посмотреть результат" : "Открыть исследование"}</button></div>`;
}

function activityPage() {
  return `<div class="wide"><h1>Исследования</h1><section class="panel">
    ${radarView.runs.length ? radarView.runs.map(runRow).join("") : '<p class="muted">Запустите разбор из карточки отклонения. Готовый результат появится здесь.</p>'}
  </section></div>`;
}

function workPage() {
  const runs = radarView.runs;
  const failed = runs.filter(r => r.status === "failed");
  const row = (title, rows, empty) => `<section class="panel"><h2>${title}</h2>${rows || `<p class="muted">${empty}</p>`}</section>`;
  return `<div class="wide"><h1>Моя работа</h1>
    ${row("Нужно решение", runs.filter(r => r.status === "done" && !r.resolution).map(runRow).join(""), "Готовых исследований без решения пока нет.")}
    ${row("Агент работает", runs.filter(r => ["queued","running"].includes(r.status)).map(runRow).join(""), "Нет активных исследований.")}
    ${row("Пора проверить эффект", state.data.tasks.map(t => `<div class="radar-run-row">
      <div><strong>${esc(t.title)}</strong><span class="by">${taskLabel(t.id)} · ${t.result ? esc(t.result.outcome) : "Ожидаем данные"}</span></div>
      ${button("Открыть проверку", "check", t.id, "link")}</div>`).join(""), "Сохраните проверку из готового исследования.")}
    ${row("Принятые решения", runs.filter(r => r.resolution).map(r =>
      `<div class="radar-run-row"><div><strong>${esc(runTitle(r))}</strong><span class="by">${esc(decisionNames[r.resolution.kind])}</span></div>
      ${button(r.finding ? "Открыть находку" : "Открыть решение", "run", r.id, "link")}
      ${r.resolution.task ? button(taskLabel(r.resolution.task), "task", r.resolution.task, "link") : ""}</div>`).join(""), "Сохранённых решений пока нет.")}
    ${failed.length ? row("Остановившиеся исследования", failed.map(runRow).join("")) : ""}
    <div class="row">${button("Бэклог", "page", "backlog", "link")} ${button("Журнал модели", "page", "usage", "link")}</div>
  </div>`;
}

function resolutionView(result) {
  if (!result) return "";
  return `<section class="panel radar-resolution" id="finding-decision" tabindex="-1"><h2>Решение PM</h2>
    <p><strong>${esc(result.legacy_link ? "Историческое решение сохранено" : decisionNames[result.kind])}${result.linked ? " · " + esc(result.linked) : ""}</strong></p>
    ${result.note ? `<p>${esc(result.note)}</p>` : ""}
    ${result.followup ? `<p class="by">Условие последующей проверки · ${esc(result.followup)}</p>` : ""}
    ${result.owner ? `<p class="by">Владелец · ${esc(result.owner)}. Вернуться ${prettyDate(result.due)}. Запись локальная.</p>` : ""}
    ${result.task ? button("Открыть " + taskLabel(result.task), "task", result.task, "primary") : ""}
  </section>`;
}

function researchPage() {
  const run = detailForRoute();
  if (!run) return `<h1>Исследование</h1>${radarLoading()}`;
  if (run.finding) return `<div class="wide"><h1>${esc(runTitle(run))}</h1>${run.finding === state.data.growth.key ?
    findingButton(run.id) : button("Открыть исходную находку","run",run.id,"link")}</div>`;
  const back = run.mode === "release" ? button("← Отклонение", "deviation", deviationRef(run.filter), "link") :
    run.mode === "growth" ? button("← Находка", "finding", state.data.growth.key, "link") :
    button("← Исследования", "page", "activity", "link");
  const status = radarStates[run.status];
  const scope = Object.values(run.scope).flat().join(" · ");
  const head = `<div class="wide radar-page">${back}<p class="eyebrow">Исследование ${esc(run.id.slice(0,8))} · ${esc(status)}</p>
    <h1>${esc(runTitle(run))}</h1><p class="lede">${esc(scope)}</p>
    ${run.mode === "growth" ? '<p class="by">Исторический запуск. Модель выбирала из подготовленных вариантов.</p>' : ""}`;
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
      <button class="primary" data-decision="new">Утвердить новую задачу</button>
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
      <p class="by">${esc(item.historical_result)}</p>
      ${run.mode === "release" ? "<p>Если корзина работает, а событие пропадает, исправить учёт. Если сбой действия воспроизведён, оценить исправление или откат. При пробеле в доказательствах отложить решение до сверки.</p>" : ""}
      <details><summary>Фактический расход модели</summary>${usageSummary(item.usage)}</details>
    </section>
    ${messages()}${resolved}</div>`;
}

function findingRef(id) { return state.data.growth.key + (id ? "~" + id : ""); }

function findingButton(id, label="Открыть исходную находку") {
  return button(label, "finding", findingRef(id), "link");
}

function researchClaim(claim, run) {
  const citations = claim.sources.map(id => {
    const fact = run.result.evidence.find(row => row.id === id);
    return button(fact.type + " · " + (fact.cohort || fact.sheet) + " · " + fact.record, "fact", id, "link");
  });
  return `<p>${esc(claim.text)}</p><div class="row finding-citations">${citations.join("")}</div>`;
}

function growthDecision(run) {
  if (run.resolution) return resolutionView(run.resolution);
  const result = run.result.research;
  return `<section class="panel" id="finding-decision" tabindex="-1"><h2>Решение PM</h2>
    <div class="finding-decisions">
      <details ${result.recommendation === "проверить решение" ? "open" : ""}><summary>Утвердить проверку</summary>
        <form id="radar-decision" data-run-id="${esc(run.id)}" class="fields">
          ${field("Название проверки", "title", result.action, 'required maxlength="180"')}
          ${area("Критерий результата", "criterion", result.criterion, 1200, "required")}
          ${area("Условие последующей проверки", "followup", result.followup, 700, "required")}
          <div class="row"><button class="primary" data-decision="new">Сохранить в бэклог</button>${chip(state.data.tag)}</div>
        </form>
      </details>
      ${[["segment","Уточнить сегмент","Какой сегмент и что нужно выяснить"], ["defer","Отложить","Причина или условие возвращения"]].map(([key,name,label]) =>
        `<details><summary>${name}</summary><form id="radar-${key}" data-run-id="${esc(run.id)}" class="fields">
          ${area(label,"note","",700,"required")}<div><button class="secondary">Сохранить решение</button></div></form></details>`).join("")}
    </div>
  </section>`;
}

function growthCost(run) {
  if (!run.calls.length) return "";
  const first = run.calls[0], cloud = first.platform === "OpenRouter";
  return `<details class="panel" id="study-cost"><summary>Расход исследования · ${number(run.usage.prompt + run.usage.completion)} токенов</summary>
    <p><strong>${esc(first.model)}</strong> · ${esc(first.platform)} · ID ${esc(run.id)}</p>
    ${usageSummary(run.usage)}
    <p class="by">${cloud ? "Суммы по квитанциям OpenRouter в USD." :
      "Локальная плата за API · 0 RUB. Электричество и амортизация сервера отдельно, замера нет."}
      Токены Codex относятся к разработке.</p>
    <div class="table-wrap"><table><thead><tr><th>Вызов</th><th>Вход</th><th>Выход</th><th>Время</th>
      ${cloud ? "<th>Списано, USD</th><th>Квитанция</th>" : ""}<th>Статус</th></tr></thead>
    <tbody>${run.calls.map(c => `<tr><td>#${c.id} · ${esc(c.scenario.split(" · ").at(-1))}</td>
      <td>${c.prompt_tokens ?? "—"}</td><td>${c.completion_tokens ?? "—"}</td>
      <td>${c.elapsed_ms === null ? "—" : seconds(c.elapsed_ms)}</td>
      ${cloud ? `<td>${esc(c.actual_cost ?? "Ожидаем")}</td><td>${esc(c.receipt || "—")} · ${esc(c.upstream || "—")}
        ${c.generation ? `<small class="by" title="${esc(c.generation)}">${esc(c.generation)}</small>` : ""}</td>` : ""}
      <td>${esc(callStatus[c.status])}</td></tr>`).join("")}</tbody></table></div>
    ${button("Открыть журнал модели", "page", "usage", "link")}
  </details>`;
}

function growthOperations(run) {
  if (!run.operations.length) return "";
  return `<details class="panel"><summary>Что искала и читала Qwen · ${run.operations.length} операций</summary>
    <p class="by">Набор ${esc(run.corpus_version)} · ${run.provider === "OpenRouter" ?
      "Qwen выбирает источники по каталогу и сопоставляет прочитанные описания задач." :
      "Запросы Qwen ранжируются с учётом исходного вопроса. Показаны первые совпадения."}</p>
    <ol class="finding-operations">${run.operations.map(op => op.op === "search" ?
    `<li><strong>${esc(op.purpose)}</strong><p>«${esc(op.query)}» · ${esc(op.type)} · проверено ${op.searched}, ${op.fallback ?
      "точных совпадений нет, просмотр группы" : "найдено"} ${esc((op.task_hits || op.hits).join(", ") || "0")}</p></li>` :
    `<li><strong>Открыта запись ${esc(op.record.task_id || op.record.id)}</strong> · ${esc(op.record.version)}
      <div>${button(op.record.source, "fact", op.record.id, "link")}</div></li>`).join("")}</ol>
    </details>`;
}

function growthResult(run) {
  const r = run.result?.research;
  if (!r) return `<section class="panel" role="status"><h2>${esc(radarStates[run.status])}</h2>
    <p>${esc(run.error || "Можно перейти в «Мою работу». Уведомление вернёт сюда, когда вывод будет готов.")}</p>
    ${run.status === "failed" ? button("Повторить исследование", "radar-retry", run.id, "primary") :
      button("Перейти в «Мою работу»", "page", "work", "link")}
    </section>${growthOperations(run)}${growthCost(run)}`;
  const recommendation = r.recommendation === "отложить" ? "отложить запуск" : r.recommendation;
  return `<section class="panel finding-result">
    <div class="section-heading"><h2>Вывод Qwen</h2><div class="row">${chip(r.confidence)}
      ${button(run.resolution ? "К решению PM" : "Принять решение", "finding-decision", "", "link")}</div></div>
    ${researchClaim(r.conclusion, run)}
    <h3>Аудитория для проверки</h3><p>${esc(r.audience)}</p>
    <div class="grid finding-evidence"><article><h3>Что говорит за</h3>${researchClaim(r.for, run)}</article>
      <article><h3>Что говорит против</h3>${researchClaim(r.against, run)}</article></div>
    ${run.result.evidence.filter(row => row.kind === "competitor" && !r.against.sources.includes(row.id))
      .map(row => `<h3>Альтернативный путь</h3>${researchClaim({text:row.text,sources:[row.id]},run)}`).join("")}
    ${run.result.evidence.filter(row => row.kind === "backlog")
      .map(row => `<h3>Запись бэклога</h3>${researchClaim({text:row.text,sources:[row.id]},run)}`).join("")}
    <h3>Что пока неизвестно</h3><p>${esc(r.unknown)}</p>
    <h3>Рекомендация · ${esc(recommendation)}</h3>${researchClaim(r.why, run)}
  </section>${growthCost(run)}${growthOperations(run)}${growthDecision(run)}`;
}

function growthPage(id) {
  const summary = state.data.growth;
  if (!id) return `<div class="wide">${button("← Воронка", "page", "funnel", "link")}
    <h1>Возможности роста</h1>
    <section class="panel finding-list"><p class="eyebrow">После покупки · весь магазин</p>
      <h2>${esc(summary.title)}</h2><p>Для кого следующий заказ стоит начинать из письма о предыдущей покупке?</p>
      <p class="by">${summary.known ? "Есть отдельное интервью. Размер аудитории и платёжный эффект неизвестны." : "Адресные материалы доступны на LAN-стенде."}</p>
      ${findingButton(null, summary.title)}
    </section></div>`;
  const item = detailForRoute();
  if (!item) return `<h1>${esc(summary.title)}</h1>${radarLoading()}`;
  const run = item.run;
  const before = run?.before || item;
  return `<div class="wide radar-page">${button("← Возможности роста", "page", "growth", "link")}
    <p class="eyebrow">После покупки · весь магазин${run ? " · исследование " + esc(run.id.slice(0,8)) : ""}</p>
    <h1>${esc(item.title)}</h1><p class="lede">${esc(run?.question || item.question)}</p>
    ${messages()}
    ${run?.result ? growthResult(run) : ""}
    <section class="panel"><h2>Что было известно до запуска</h2>
      ${before.known ? `<p>В одном интервью покупатель предложил начинать повтор из письма. Масштаб потребности и влияние на оплату предстоит выяснить.</p>
        ${button("Открыть исходное интервью", "fact", before.known.id, "link")}` : "<p>Пока нет доступной исходной записи по письму.</p>"}
      ${run || item.version ? `<p class="by">${Object.entries(before.coverage).map(([kind,count]) => esc(kind) + " " + count).join(" · ")}</p>` :
        '<p class="by">Исследование доступно на защищённом LAN-стенде.</p>'}
      ${!run && item.version ? '<form id="radar-growth-form" class="row actions"><button class="primary">Исследовать с Qwen</button></form>' : ""}
    </section>
    ${state.data.store ? `<section class="panel"><h2>Повтор из истории заказов</h2>
      <p>${esc(state.data.store.initiatives.repeat.text)}</p>${sourceLink(state.data.store.initiatives.repeat,"Инициатива Softline · слайд 18")}</section>` : ""}
    ${run && !run.result ? growthResult(run) : ""}
    ${run?.resolution && item.version ? `<details class="panel" ${run.resolution.kind === "segment" ? "open" : ""}>
      <summary>Исследовать другой сегмент</summary><form id="radar-growth-form" class="fields">
      ${area("Уточнение сегмента", "question", "", 220, "required")}
      <div><button class="primary">Исследовать уточнение с Qwen</button></div></form></details>` : ""}
    ${item.runs.some(r=>r.id!==run?.id) ? `<details class="panel"><summary>Предыдущие исследования</summary>
      ${item.runs.filter(r=>r.id!==run?.id).map(runRow).join("")}</details>` : ""}
  </div>`;
}

function astraPage() {
  const data = detailForRoute();
  if (!data) return `<h1>Подбор Astra</h1>${radarLoading()}`;
  if (data.periods) return astraDiagnostic(data);
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
  if (state.data.store && id?.split("~")[0]==="office") return officePage(id);
  const product=state.data.store?.catalog[id];
  if (product) return `<div class="wide">${button("← Ассортимент","page","catalog","link")}
    <p class="eyebrow">${esc(product.group)}</p><h1>${esc(product.title)}</h1>
    <section class="panel"><h2>Свидетельства по товару</h2>
      ${product.sources.map(r=>`<p>${esc(r.text)} · ${sourceLink(r,"Открыть основание")}</p>`).join("")}
      ${id==="cryptopro" ? sourceLink(state.data.store.initiatives.cryptopro) : ""}
      ${id==="astra" ? button("Октябрьский пример · 12–25 октября","astra",astraRef("comparison","oct12","oct19"),"secondary") : ""}
      ${id==="kes" ? button("Открыть отклонение Kaspersky","deviation",deviationRef({...funnelView.filter || state.data.funnel.defaults,family:"kes",device:"all",audience:"all"}),"secondary") : ""}
    </section>${product.prices.matched.length ? `<section class="panel"><h2>Ценовые замеры</h2>${productPrices(product.prices)}</section>` : ""}</div>`;
  const selected = state.data.catalog[id];
  if (selected) return `<div class="wide">${button("← Ассортимент", "page", "catalog", "link")}
    <p class="eyebrow">${esc(selected.stage)}</p><h1>${esc(selected.title)}</h1>
    <section class="panel"><h2>Доступные материалы</h2><p>${esc(selected.text)}</p><p class="by">${esc(selected.source)}</p>
    <p class="note">Нет истории заказов в выгрузке. Количественное сравнение семейств недоступно.</p></section></div>`;
  return `<div class="wide">${button("← Воронка", "page", "funnel", "link")}<h1>Ассортимент</h1>
    <section class="panel"><label>Поиск продукта<input id="catalog-query" type="search" value="${esc(state.catalogQuery)}"></label>
      <div id="catalog-matches">${catalogMatches()}</div>
    </section></div>`;
}

function catalogMatches() {
  const entries = state.data.store ? Object.entries(state.data.store.catalog).map(([id,item])=>[item.title,"catalog",id,item.group]) : [
    ["Kaspersky · самостоятельные заказы", "deviation", "kes.aug.oct.all.all"],
    ["Astra · прохождение подбора", "page", "astra"],
    ...Object.entries(state.data.catalog).map(([key,item]) => [item.title, "catalog", key])
  ];
  const query = (state.catalogQuery || "").trim().toLocaleLowerCase("ru");
  return entries.filter(([title,,,group]) => (title + " " + (group || "")).toLocaleLowerCase("ru").includes(query))
    .map(([title, action, key]) => button(title, action, key, "block-row")).join("") ||
    '<p class="by" role="status">В доступном ассортименте совпадений нет.</p>';
}

function renderRadarNotice() {
  const aside = document.querySelector("#radar-notice");
  const count = document.querySelector("#radar-count");
  const ready = radarView.runs.filter(run=>run.status==="done"&&!run.seen);
  const run = ready.find(item=>!radarView.dismissed.has(item.id));
  count.textContent = ready.length ? String(ready.length) : "";
  aside.hidden = !state.data || !run;
  const displayed = aside.hidden ? "" : run.id;
  if (aside.dataset.run === displayed) return;
  aside.dataset.run = displayed;
  aside.innerHTML = !aside.hidden ? `<p><strong>Исследование завершено</strong> · ${esc(runTitle(run))}</p>
    <div class="row">${button("Посмотреть результат","run",run.id,"link")}
      ${button("Скрыть уведомление","radar-dismiss",run.id,"link")}</div>` : "";
}

async function pollRadar() {
  if (!state.data?.funnel || radarView.polling) return;
  radarView.polling = true;
  try {
    const previous = JSON.stringify(radarView.runs);
    radarView.runs = await api("radar/runs");
    renderRadarNotice();
    const [page, id] = route();
    if (["activity","work"].includes(page) && JSON.stringify(radarView.runs)!==previous) render();
    if (page==="funnel" && state.data.store) updateOverviewResearch();
    const detail = detailForRoute();
    const activeRun = detail?.run || (page==="research" ? detail : null);
    const current = radarView.runs.find(run=>run.id===(activeRun?.id || id));
    if (activeRun?.status==="done" && current?.status==="done" &&
        JSON.stringify(activeRun.mail)!==JSON.stringify(current.mail)) {
      activeRun.mail = current.mail;
      updateProjectMail(current.mail);
    }
    if (page==="research" && current && detailForRoute()?.status!==current.status)
      void loadRadarDetail(radarDetailPath(page,id), true);
    if (["growth","deviation","catalog","astra"].includes(page) && activeRun && current && (activeRun.status !== current.status ||
        (["queued","running"].includes(activeRun.status) && current.operation_count !== undefined &&
          activeRun.operations.length !== current.operation_count && !dialog.open)))
      void loadRadarDetail(radarDetailPath(page,id), true);
  } catch (error) {
    if (error.status===401) void boot();
  } finally { radarView.polling = false; }
}

async function openRun(id, run=radarView.runs.find(item=>item.id===id)) {
  try {
    run ||= await api("radar/run?" + new URLSearchParams({id}));
    const from=overviewNavigation();
    if (run.finding === "kes") go("deviation", deviationRef(run.filter)+"~"+id, from);
    else if (run.finding === "office") go("catalog","office~"+id,from);
    else if (run.finding === "astra") go("astra","below90."+deviationRef(run.filter)+"~"+id,from);
    else if (run.finding) go("growth", findingRef(id));
    else go("research",id);
    await api("radar/seen",{id});
    await pollRadar();
  } catch(error) { if (error.status===401) void boot(); }
}

async function startRadar(payload) {
  const run = await api("radar/start",payload);
  const path = radarDetailPath(...route());
  if (detailForRoute()?.run?.id === run.id && path) await loadRadarDetail(path,true);
  await openRun(run.id, run);
}

async function retryRadar() {
  const info = detailForRoute();
  const run = info?.run || info;
  if (!run || run.status!=="failed") return;
  const question = run.question?.split(" Уточнение PM: ").slice(1).join(" Уточнение PM: ") || "";
  await startRadar({...run.filter,mode:run.mode,...(state.data.cloud_research ? {previous:run.id} : {stage:run.stage,question})});
}
