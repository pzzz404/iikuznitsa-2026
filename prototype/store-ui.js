"use strict";

function sourceLink(row, label=row.title) {
  return button(label, "fact", row.id, "link");
}

function storeFacts() {
  const store = state.data.store;
  if (!store) return [];
  return [
    ...Object.values(store.definitions), ...store.releases, ...Object.values(store.initiatives), ...Object.values(store.lk.sources),
    ...store.tasks.map(row => ({...row, id:row.source_id})),
    ...Object.values(store.catalog).flatMap(item => [...item.sources, ...item.prices.matched, ...item.prices.partial, item.invoice].filter(Boolean)),
    ...(funnelView.report?.storeData?.evidence || [])
  ];
}

function coverageCaption(store) {
  const c = store.coverage;
  return "BI по " + prettyDate(c.sales_to) + " · полная неделя до " + prettyDate(c.last_full) + " · веб-аналитика по " + prettyDate(c.metrics_to);
}

function chartSeries(series, events, filter) {
  const windows = state.data.funnel.windows;
  const start = windows[filter.before]?.start;
  const finish = Date.parse(windows[filter.after]?.start) + (windows[filter.after]?.weeks || 0)*604800000;
  const visible = series.filter(row => (!start || row.date >= start) && (!Number.isFinite(finish) || Date.parse(row.date)<finish));
  if (!visible.length) return "";
  const scale = Math.ceil(Math.max(100,...visible.flatMap(a => [a.value,a.average || 0]))/50)*50;
  const ticks = Math.round(scale/50);
  const x = day => 46 + 810*(Date.parse(day)-Date.parse(visible[0].date))/
    Math.max(604800000,Date.parse(visible.at(-1).date)-Date.parse(visible[0].date));
  const y = value => 198 - (value/scale)*160;
  const line = key => visible.filter(v=>v[key] != null).map(v=>x(v.date)+","+y(v[key])).join(" ");
  return `<section class="panel order-chart"><div class="section-heading"><h2>Индекс самостоятельных заказов</h2></div>
    <div class="row by"><span class="weekly-key">Недельный</span><span class="rolling-key">Скользящий за 4 недели</span>
      <span>База 100 · 04.05–28.06.2026</span></div>
    <svg viewBox="0 0 900 220" class="index-chart" role="img" aria-label="Недельный индекс и скользящий индекс за четыре недели">
      ${Array.from({length:ticks+1},(_,i) => `<line class="plot-grid" x1="46" y1="${y(i*50)}" x2="865" y2="${y(i*50)}"/>
        <text x="36" y="${y(i*50)+4}" text-anchor="end">${i*50}</text>`).join("")}
      ${visible.filter((_,i)=>i===visible.length-1 || (i < visible.length-2 && i%Math.max(1,Math.floor(visible.length/5))===0))
        .map(v=>`<text x="${x(v.date)}" y="217" text-anchor="middle">${prettyDate(v.date).slice(0,5)}</text>`).join("")}
      ${events.filter(e=>e.date>=visible[0].date && e.date<=visible.at(-1).date).map((e,i)=>`<line class="plot-event" x1="${x(e.date)}" y1="32" x2="${x(e.date)}" y2="198"/><text x="${x(e.date)+4}" y="${13+(i%2)*14}">${esc(e.title)}</text>`).join("")}
      <polyline class="plot-week" points="${line("value")}"/><polyline class="plot-average" points="${line("average")}"/>
      ${visible.map(v=>`<circle class="plot-point ${v.partial?"partial":""}" cx="${x(v.date)}" cy="${y(v.value)}" r="4"><title>${prettyDate(v.date)} · ${number(v.value)}${v.partial?" · неполная":""}</title></circle>`).join("")}
    </svg>
    ${events.length ? `<div class="row">${events.map(e=>sourceLink(e, e.title+" · "+prettyDate(e.date).slice(0,5)+" · "+({"R-08":"вход","R-09":"подбор KES","R-10":"рассылка в ЛК"}[e.title] || e.type))).join("")}</div>` : ""}
    <details><summary>Недельные значения и строки «Продаж»</summary><div class="table-wrap"><table><thead>
      <tr><th>Неделя с</th><th>Индекс</th><th>За 4 недели</th><th>Основание</th></tr></thead><tbody>
      ${visible.map(v=>`<tr><td>${prettyDate(v.date)}${v.partial?" · неполная":""}</td><td>${number(v.value)}</td>
        <td>${v.average==null?"—":number(v.average)}</td><td>Продажи · строка ${v.row}</td></tr>`).join("")}</tbody></table></div></details>
  </section>`;
}

function astraAlert() {
  const store = state.data.store;
  const pair = store?.alerts.astra.at(-1);
  if (!pair) return "";
  return `<section class="panel radar-signal down"><div><p class="label">Astra · предупреждение по порогу</p>
    <h2>${pair[0].value} и ${pair[1].value} · две недели ниже ${store.threshold}</h2>
    <p class="by">${pair.map(p=>prettyDate(p.date).slice(0,5)).join(" и ")} · индекс самостоятельных заказов · «Продажи», строки ${pair.map(p=>p.row).join(", ")}.</p>
    ${sourceLink(store.definitions.family_orders_idx,"Открыть правило из справочника")}</div>
    ${button("Разобрать путь Astra","page","astra","secondary")}</section>`;
}

function storeIndicators() {
  const store=state.data.store;
  if (!store) return "";
  const office=store.catalog.office.prices, lk=store.lk.counts;
  return `<section class="panel"><h2>Другие решения по магазину</h2>
    <div class="radar-run-row"><div><strong>Office · ${office.below_store} из ${office.matched.length} сопоставимых цен ниже Store</strong>
      <span class="by">Выбор предложения · октябрьский замер</span></div>${button("Проверить предложение Office","catalog","office","secondary")}</div>
    <div class="radar-run-row"><div><strong>Личный кабинет · ${lk.click_visits} клика на ${lk.viewed_visits} визитов с просмотром</strong>
      <span class="by">После покупки · рекомендации</span></div>${button("Открыть рекомендации ЛК","page","lk","secondary")}</div>
  </section>
    <details class="panel"><summary>История магазина · ${store.releases.length} событий</summary>
      ${store.releases.map(r=>`<div class="radar-run-row"><div><strong>${esc(r.title)} · ${prettyDate(r.date)}</strong>
        <p>${esc(r.text)}</p><span class="by">${esc(r.metrics || "")}</span></div>${sourceLink(r,"Строка события")}</div>`).join("")}</details>
    <details class="panel"><summary>Справочник показателей · ${Object.keys(store.definitions).length}</summary>
      <div class="grid">${Object.values(store.definitions).map(r=>`<div><h3>${esc(r.title)}</h3>${sourceLink(r,"Открыть определение")}</div>`).join("")}</div></details>`;
}

function productPrices(prices) {
  const rows = [...prices.matched, ...prices.partial];
  if (!rows.length) return "";
  return `<div class="table-wrap"><table><thead><tr><th>Площадка</th><th>Цена</th><th>Сопоставимость</th><th>Лицензия и условия</th><th>Дата замера</th></tr></thead><tbody>
    ${rows.map(r=>`<tr><td>${sourceLink(r)}</td><td>${number(r.amount)} ₽</td><td>${r.match==="Да"?"Да":"Частичная · исключено"}</td>
      <td>${esc(r.conditions || "—")}</td><td>${esc(r.date ? prettyDate(r.date) : "—")}</td></tr>`).join("")}</tbody></table></div>`;
}

function projectResult(run) {
  if (!run) return "";
  if (!run.result) return growthResult(run);
  const item = run.result;
  const facts = new Map(item.evidence.map(source=>[source.id,source]));
  return `<section class="panel finding-result"><p class="eyebrow">Исследование ${esc(run.id)}</p>
    <div class="section-heading"><h2>Что предлагает Qwen</h2>
    ${button(run.resolution ? "К решению PM" : "Принять решение","finding-decision","","link")}</div>
    <p class="lede">${esc(item.action)}</p>
    <div class="grid finding-evidence">${item.selected.map((id,i)=>{
      const fact=facts.get(id);
      return `<article><h3>${i?"Что ограничивает вывод":"Основание проверки"}</h3><p>${esc(fact.text)}</p>
        ${sourceLink(fact, "Открыть основание · " + fact.title)}</article>`;
    }).join("")}</div>
    <p class="by">${esc(item.historical_result)}</p>
    ${run.finding === "kes" ? `<details><summary>Как результат изменит решение</summary>
      <p>Повторяется сбой действия — воспроизвести на проблемной конфигурации и оценить откат.</p>
      <p>Действие работает, запись теряется — уточнить T-08 и проверить телеметрию.</p>
      <p>Заказы сместились к менеджеру — сверить общий ряд и проверить доступность самостоятельной закупки.</p></details>` : ""}
    <details><summary>Прочитанные записи</summary><div class="grid">${item.evidence.map(sourceCard).join("")}</div></details>
    </section>${growthCost(run)}${growthOperations(run)}${projectDecision(run)}`;
}

function projectDecision(run) {
  if (run.resolution) return resolutionView(run.resolution);
  const item=run.result;
  return `<section class="panel" id="finding-decision" tabindex="-1"><h2>Решение PM</h2>
    <p class="by">Запись создаётся в локальном бэклоге PM Radar.</p>
    <form id="radar-decision" data-run-id="${esc(run.id)}" class="fields">
      ${field("Название проверки","title",item.action,'required maxlength="180"')}
      ${area("Критерий приёмки","criterion",item.criterion,1200,"required")}
      ${area("Условие последующей проверки","followup",item.followup,700,"required")}
      <div class="form-grid">
        ${field("Владелец проверки","owner","",'required maxlength="120"')}
        ${field("Дата возврата к проверке","due",state.data.today,'type="date" required')}
      </div>
      ${field("Комментарий PM","note","",'maxlength="700"')}
      <div class="row">
        ${item.related ? '<button class="primary" data-decision="link">Дополнить T-08</button>' : ""}
        <button class="${item.related?"secondary":"primary"}" data-decision="new">Создать задачу</button>
      </div>
    </form>
    <details><summary>Отложить</summary><form id="radar-defer" data-run-id="${esc(run.id)}" class="fields">
      ${area("Причина и условие возвращения","note","",700,"required")}
      <div><button class="secondary">Сохранить причину</button></div></form></details>
  </section>`;
}

function officePage(ref) {
  const store=state.data.store;
  const item=store.catalog.office, prices=item.prices, detail=detailForRoute();
  if (!detail) return `<h1>${esc(item.title)}</h1>${radarLoading()}`;
  return `<div class="wide radar-page">${button("← Ассортимент","page","catalog","link")}
    <p class="eyebrow">Выбор предложения · октябрь 2026 · EP2-06605</p><h1>${esc(item.title)}</h1>
    <section class="panel radar-signal down"><div><p class="label">Ценовой сигнал</p>
      <h2>${prices.below_store} из ${prices.matched.length} сопоставимых цен ниже Store</h2>
      <p>Цена Store · <strong>${number(prices.store)} ₽</strong>. Бессрочная лицензия на один ПК.</p>
      <p class="by">Сравнение по артикулу и отметке сопоставимости. Замер показывает цены на дату проверки.</p></div>
      ${detail.run ? (detail.run.status === "done" ? button("К решению","finding-decision","","link") : "") :
        `<form id="radar-start-form" data-mode="office"><button class="primary">Исследовать предложение Office</button></form>`}
    </section>${messages()}${projectResult(detail.run)}
    <section class="panel"><h2>Цены и условия</h2>${productPrices(prices)}</section>
    <section class="panel"><h2>Самостоятельный счёт</h2><p>${esc(item.invoice.text)}</p>${sourceLink(item.invoice,"Открыть прохождение")}</section>
    <section class="panel"><h2>Инициатива Softline</h2><p>${esc(store.initiatives.office.text)}</p>
      ${sourceLink(store.initiatives.office,"Слайд 18")}${item.sources.map(s=>sourceLink(s)).join(" · ")}</section>
  </div>`;
}

function lkPage() {
  const store=state.data.store;
  if (!store) return "<h1>Личный кабинет</h1>";
  const {counts:n,sources:s}=store.lk;
  return `<div class="wide">${button("← Воронка","page","funnel","link")}<p class="eyebrow">После покупки · 26.10–22.11.2026</p>
    <h1>Рекомендации в личном кабинете</h1>
    <section class="panel"><h2>Где теряется охват</h2>
      <p>Попытка вывода · <strong>${number(n.status)}</strong> визитов ${sourceLink(s.lk_reco_status_visits,"Строки статуса")}</p>
      <p>Показ · <strong>${ratio({n:n.visits_shown,d:n.visits_shown+n.visits_not_shown})}</strong> визитов ${sourceLink(s.lk_reco_shown_share,"Строки показа")}</p>
      <p>Просмотр · <strong>${n.viewed_visits}</strong> визитов с видимостью блока.</p>
      <p>Клик · <strong>${n.click_visits} из ${n.viewed_visits} · ${(100*n.click_visits/n.viewed_visits).toLocaleString("ru-RU",{maximumFractionDigits:2})}%</strong>
        ${sourceLink(s.lk_reco_ctr,"Строки просмотра и клика")}</p>
      <p class="note">Статусы вывода и сумма показов с непоказами расходятся. Сначала сверить охват ручных связок. Связи с оплатой нет.</p>
      ${store.tasks.filter(t=>["T-04","T-05"].includes(t.id)).map(t=>sourceLink({...t,id:t.source_id},t.id+" · "+t.title)).join(" · ")}
    </section>
    <section class="panel"><h2>Повтор заказа после покупки</h2>
      <p>Письмо начинает повтор с сообщения о прошлом заказе. Инициатива Softline добавляет отдельную кнопку в историю ЛК.</p>
      ${sourceLink(store.initiatives.repeat,"Инициатива · слайд 18")} ${findingButton(null,"Исследование повтора из письма")}</section></div>`;
}
