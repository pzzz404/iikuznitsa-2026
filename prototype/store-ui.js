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
  if (state.data.cloud_research) return "Учебные продажи и метрики";
  if (store.demo) return "Демо жюри · согласованные агрегаты и учебный бэклог";
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

function astraRef(finding,before,after) {
  return finding+"."+deviationRef({family:"astra",before,after,device:"desktop",audience:"all"});
}

function astraDateRange(first,last) {
  const format=new Intl.DateTimeFormat("ru-RU",{day:"numeric",month:"long",timeZone:"UTC"});
  return format.formatRange(new Date(first),new Date(Date.parse(last)+6*86400000));
}

function updateOverviewResearch() {
  const report=funnelView.report;
  if (!report?.storeData) return;
  const ref=deviationRef({...report.filter,family:"kes"});
  const matches=radarView.runs.filter(run=>run.backlog_search && deviationRef(run.filter)===ref);
  const existing=report.storeData.kesRun;
  const pool=existing && !matches.some(run=>run.id===existing.id) ? [...matches,existing] : matches;
  const run=pool.sort((a,b)=>Number(b.status==="done")-Number(a.status==="done") ||
    b.created.localeCompare(a.created))[0];
  if (run && (run.id!==existing?.id || run.status!==existing.status || run.resolution?.kind!==existing.resolution?.kind)) {
    report.storeData.kesRun=run;
    render();
  }
}

function overviewRows(report) {
  const store=state.data.store;
  const options=state.data.funnel.windows;
  const {before,after}=report.filter;
  const windows=[options[before],options[after]];
  const dates=windows.map(w=>w.label).join(" и ");
  const within=iso=>windows.some(w=>Date.parse(iso)>=Date.parse(w.start) &&
    Date.parse(iso)<Date.parse(w.start)+w.weeks*604800000);
  const rows=[];
  const pair=report.storeData.astraAlert;
  const first=pair && Object.keys(options).find(id=>options[id].start===pair[0].date &&
    options[options[id].mate]?.start===pair[1].date);
  const astra=report.orders.astra;
  if (astra && first) {
    const latest=options[first].mate;
    const context=before===first && after===latest ? "" : ` · среднее индекса ${signed(astra.change)}% за окна ${dates}`;
    rows.push({product:"astra",stage:"order",label:"Astra",signal:"Две недели ниже порога "+store.threshold,
      scope:`${pair[0].value} → ${pair[1].value} · ${options[first].label} и ${options[latest].label}${context}`,
      className:"down",cta:button("Разобрать "+astraDateRange(pair[0].date,pair[1].date),"astra",astraRef("below90",first,latest),"primary")});
  } else if (astra && options[before].mate) {
    rows.push({product:"astra",stage:"order",label:"Astra",signal:"Индекс самостоятельных заказов "+signed(astra.change)+"%",
      scope:dates+" · "+number(astra.before)+" → "+number(astra.after),
      className:astra.change<0?"down":"",cta:button("Разобрать выбранные недели","astra",astraRef("comparison",before,after),"secondary")});
  } else if (astra && store.demo && options.oct12 && options.oct19) {
    rows.push({product:"astra",stage:"order",label:"Astra",signal:"Индекс самостоятельных заказов "+signed(astra.change)+"%",
      scope:dates+" · "+number(astra.before)+" → "+number(astra.after),
      className:astra.change<0?"down":"",cta:button("Открыть октябрьские замеры подбора","astra",astraRef("comparison","oct12","oct19"),"link")});
  }
  const kes=report.orders.kes;
  if (kes) {
    const filters={...report.filter,family:"kes"};
    const run=report.storeData.kesRun;
    const done=run?.status==="done";
    const action=done ? (run.resolution ? "Открыть решение" : "Открыть вывод Qwen") :
      run && ["queued","running"].includes(run.status) ? "Открыть ход исследования" : "Открыть отклонение";
    const progress=done ? (run.resolution ? "Решение сохранено" : "Вывод готов к решению") :
      run ? radarStates[run.status] : "Исследование не запускалось для этого периода";
    rows.push({product:"kes",stage:"order",label:"Kaspersky",signal:"Индекс самостоятельных заказов "+signed(kes.change)+"%",
      scope:dates+" · "+progress,className:kes.change<0?"down":"",
      cta:button(action,"deviation",deviationRef(filters)+(run?"~"+run.id:""),"secondary")});
  }
  const office=store.catalog.office;
  const measured=office.prices.matched[0]?.date;
  if (measured && within(measured)) {
    rows.push({product:"office",stage:"license",label:office.title,
      signal:`${office.prices.below_store} из ${office.prices.matched.length} сопоставимых предложений дешевле Store`,
      scope:(store.demo?"Учебный замер ":"Замер ")+new Intl.DateTimeFormat("ru-RU",{day:"numeric",month:"long",timeZone:"UTC"}).format(new Date(measured)),
      className:"down",cta:button("Сверить цены","office-prices","office","secondary")});
  }
  return rows;
}

function showOverview() {
  const model=state.data.funnel, store=state.data.store, report=funnelView.report;
  const f=funnelView.filter || model.defaults;
  const {stage,product}=funnelView;
  const dates=[f.before,f.after].map(key=>model.windows[key].label).join(" и ");
  const locked=funnelView.loading || funnelView.waiting ? "disabled" : "";
  const products={all:"Все товары",...Object.fromEntries(Object.entries(store.catalog).map(([key,row])=>[key,row.title]))};
  const headings={license:["Выбор предложения и лицензии",product==="all"?"Цены Office и данные подбора":
      product==="office"?"Сопоставимые предложения":"Материалы по выбранному товару"],
    cart:["Корзина",product==="kes"?"Пробел учёта Kaspersky":product==="all" || product==="astra"?"Счётчики добавления по Astra":"Нет счётчиков для товара"],
    order:["Самостоятельный заказ",product==="all"?"Kaspersky и Astra":
      model.families[product] || "Нет ряда по выбранному товару"],
    paid:["Оплата","Нет связки с оплатой"]};
  const controls=`<div class="overview-toolbar">
      ${selectField("Товар","product",products,product,locked)}
      <details id="overview-filters" ${funnelView.filtersOpen?"open":""}><summary>Сравнить периоды и разрезы</summary>
        <form id="funnel-filters" class="funnel-filters panel" aria-label="Периоды и разрезы">
          ${selectField("Первый период","before",periodOptions(model,"before",f),f.before,locked)}
          ${selectField("Второй период","after",periodOptions(model,"after",f),f.after,locked)}
          ${selectField("Устройство","device",model.devices,f.device,locked)}
          ${selectField("Покупатели","audience",model.audiences,f.audience,locked)}
          ${model.windows.oct_partial && !model.windows[f.after].mate ? `<label class="toggle"><input name="full_weeks" type="checkbox"
            ${f.after==="oct_partial"?"":"checked"} ${locked}>Только полные недели</label>` : ""}
        </form>
      </details></div>`;
  const title=`<div class="overview-head"><h1>Обзор магазина</h1>
    <p><strong>${esc(dates)}</strong>${model.windows[f.after].partial ? " · включает неполную неделю" : ""}
       <span class="by">${esc(coverageCaption(store))} · индекс заказов по двум семействам</span></p></div>`;
  const path=`<ol class="funnel-stages overview-stages" aria-label="Путь покупки">
    ${Object.entries(headings).map(([key,[label,note]])=>`<li>
      <button type="button" data-funnel-stage="${key}" aria-pressed="${stage===key}" ${locked}>
        <strong>${label}</strong><span class="funnel-cell-detail">${note}</span>
        ${stage===key?'<span class="stage-selected">Выбран</span>':""}</button>
    </li>`).join("")}</ol>`;
  if (!report || funnelView.loading) return `<div class="store-overview">${title}${controls}${path}${messages()}
    ${state.error?"":'<p class="feedback" role="status">Читаю данные…</p>'}</div>`;
  const visible=overviewRows(report).filter(row=>(stage==="all" || row.stage===stage) &&
    (product==="all" || row.product===product));
  const canMeasure=["kes","astra"].includes(product) || product==="all";
  const stageNotes=canMeasure && ["license","cart","paid"].includes(stage) ?
    stageSummary(report,report.orders[f.family],null,f.family,["","gap"],funnelView.waiting || report.audience_gap) : "";
  const notice=visible.length ? visible.map(row=>`<article class="overview-row ${row.className}" data-product="${row.product}">
    <div><p class="overview-product">${esc(row.label)}</p><h3>${esc(row.signal)}</h3><p class="by">${esc(row.scope)}</p></div>
    ${row.cta}</article>`).join("") : stageNotes ? "" :
    `<p class="note"><strong>Нет данных для сигнала</strong> · ${esc(report.audience_gap ||
      (stage==="paid" ? report.payment_gap : product==="office" ?
      "Дата ценового замера не попадает в выбранные периоды." : "В выбранном срезе нет сопоставимых измерений."))}</p>`;
  return `<div class="store-overview">${title}${controls}${path}${messages()}
    <section class="overview-findings"><div class="section-heading"><h2>Ближайшие решения</h2>
      ${stage!=="all" ? button("Все этапы","funnel-stage","all","link") : ""}</div>
      ${notice}${stageNotes}</section>
    <div class="row overview-more">${button("Поиск продукта","page","catalog","link")}
      ${button("Возможности роста","page","growth","link")}
      ${button("После покупки · рекомендации ЛК","page","lk","link")}</div>
    ${report.orders[f.family] && ["all","order"].includes(stage) ? ordersDetail(report) : ""}
    ${canMeasure && ["license","cart","paid"].includes(stage) ? measuredDetails(report) : ""}
    ${storeIndicators()}</div>`;
}

function cloudRunButton(mode, run) {
  if (run && run.status !== "done") return "";
  return `<form id="cloud-run-form" class="row actions" data-mode="${mode}" data-previous="${esc(run?.id || "")}">
    <button class="${run ? "secondary" : "primary"}">${run ? "Запустить новый разбор Qwen3‑32B" : "Исследовать с Qwen3‑32B"}</button>
  </form>`;
}

function astraDiagnostic(data) {
  const {before,after}=data.periods;
  const labels=state.data.funnel.windows;
  const range=astraDateRange(labels[data.filter.before].start,labels[data.filter.after].start);
  const evidence=(id,label)=>{
    const fact=data.evidence.find(item=>item.id===id);
    return fact ? sourceLink(fact,label) : "";
  };
  const metric=(key,id,heading)=>{
    return `<tr><th scope="row">${heading}</th>${["before","after"].map(slot=>{
      const value=data.periods[slot][key];
      return `<td>${value ? ratio(value) : "Нет данных"}
        ${value && key==="cart" ? `<span class="by">Покрытие ${value.rows}/${value.expected_rows} дней</span>` : ""}
        ${value ? evidence("astra-"+id+"-"+slot,"Строки · "+data.periods[slot].label) : ""}</td>`;
    }).join("")}</tr>`;
  };
  const isAlert=data.finding==="below90";
  const hypothesis=isAlert ? "Проверить переход от итога подбора к добавлению в корзину на компьютере." :
    "Сверить, как меняются прохождение подбора и добавления в выбранных неделях.";
  return `<div class="wide radar-page">${button("← Обзор магазина","funnel-back",overviewBack(data.filter),"link")}
    <p class="eyebrow">${esc(state.data.store.catalog.astra.title)} · недели ${before.label} и ${after.label}</p>
    <h1>Astra · ${range} 2026</h1>
    <p class="lede">${isAlert ? `Две недели ниже порога ${data.threshold} · индекс ${before.index} → ${after.index}` :
      `Индекс самостоятельных заказов ${before.index ?? "—"} → ${after.index ?? "—"}`}</p>
    <section class="panel astra-diagnostic"><h2>Где меняется путь покупки</h2>
      <div class="table-wrap"><table><thead><tr><th>Показатель</th><th>${before.label}</th><th>${after.label}</th></tr></thead><tbody>
        <tr><th scope="row">Самостоятельные заказы · индекс BI</th><td>${before.index ?? "Нет данных"}</td><td>${after.index ?? "Нет данных"}</td></tr>
        ${metric("step","cfg_step_dropoff","Шаг 1 → 2 · все устройства")}
        ${metric("cart","cfg_add_to_cart_rate","Подбор → корзина · компьютеры")}
      </tbody></table></div>
      <p class="by">${evidence("sales-astra","Строки «Продаж»")} ·
        ${evidence(state.data.store.definitions.family_orders_idx.id,"Правило порога в справочнике")}</p>
    </section>
    ${state.data.cloud_research ? `${messages()}${isAlert ? cloudRunButton("astra",data.run) : ""}
      ${projectResult(data.run)}` : `<form id="radar-astra-form" class="panel" data-stage="${isAlert?"cart":"license"}">
      <h2>Что проверить</h2><p>${hypothesis}</p>
      ${isAlert && before.cart && after.cart ? `<p>Открытия на компьютерах выросли с ${before.cart.d} до ${after.cart.d}.
        Добавления ${before.cart.n===after.cart.n?`остались на уровне ${after.cart.n}`:`изменились с ${before.cart.n} до ${after.cart.n}`}.</p>` : ""}
      <p class="by">В данных нет общего идентификатора заказа и визита. Связь с изменением индекса BI не установлена.</p>
      <button class="primary">${isAlert?"Проверить путь до корзины":"Проверить вход в подбор Astra"}</button>
    </form>${messages()}`}</div>`;
}

function storeIndicators() {
  const store=state.data.store;
  if (!store) return "";
  return `<details class="panel"><summary>История магазина · ${store.releases.length} событий</summary>
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
    ${item.cloud_claims ? '<p class="by">Qwen3‑32B · OpenRouter</p>' : ""}
    <p class="lede">${esc(item.action)}</p>
    <div class="grid finding-evidence">${item.cloud_claims ? cloudEvidence(item.cloud_claims, facts) : item.selected.map((id,i)=>{
      const fact=facts.get(id);
      return `<article><h3>${i?"Что ограничивает вывод":"Основание проверки"}</h3><p>${esc(fact.text)}</p>
        ${sourceLink(fact, "Открыть основание · " + fact.title)}</article>`;
    }).join("")}</div>
    ${run.backlog_search || run.finding === "kes" ? taskMatch(item) : ""}
    <p class="by">${esc(item.historical_result)}</p>
    <div id="project-mail-status">${projectMail(run.mail)}</div>
    ${item.cloud_branches ? `<div class="panel"><h3>Как результат изменит решение</h3>
      ${item.cloud_branches.map(branch=>`<p><strong>${esc(branch.label)}</strong> · ${esc(branch.text)}</p>`).join("")}
      ${item.cloud_business ? `<h3>${esc(item.cloud_business.label)}</h3><p>${esc(item.cloud_business.text)}</p>` : ""}</div>` : run.finding === "kes" ? `<details><summary>Как результат изменит решение</summary>
      <p>Повторяется сбой действия — воспроизвести на проблемной конфигурации и оценить откат.</p>
      <p>Действие работает, запись теряется — проверить телеметрию.</p>
      <p>Заказы сместились к менеджеру — сверить общий ряд и проверить доступность самостоятельной закупки.</p></details>` : ""}
    <details><summary>Прочитанные записи</summary><div class="grid">${item.evidence.map(sourceCard).join("")}</div></details>
    </section>${growthCost(run)}${growthOperations(run)}${projectDecision(run)}`;
}

function cloudEvidence(claims, facts) {
  const labels = {signal:"Что изменилось", alternative:"Другое объяснение",
    customer:"Свидетельство покупателя", counterexample:"Контрпример", limit:"Предел вывода"};
  return Object.entries(labels).map(([key,label]) => {
    const claim = claims[key], source = facts.get(claim.source);
    return `<article data-claim="${key}"><h3>${esc(claim.label || label)}</h3>${claim.text === claim.quote ? "" : `<p>${esc(claim.text)}</p>`}
      <blockquote>${esc(claim.quote)}</blockquote>
      ${sourceLink(source,"Открыть источник · " + source.title)}</article>`;
  }).join("");
}

function taskMatch(item) {
  const match = item.task_match;
  if (!match) return '<p class="by">В историческом прогоне связь с бэклогом отдельно не проверялась.</p>';
  if (!item.related) return `<div class="radar-related"><strong>Подходящая задача не найдена</strong>
    <p>${match.model_task && match.model_task !== "none" ? "Вариант Qwen · " + esc(match.model_task) + ". " : ""}${esc(match.reason)}</p></div>`;
  return `<div class="radar-related"><strong>Задача, которую нашла Qwen</strong>
    ${button(item.related.id + " · " + item.related.title, "fact", item.related.record_id, "link")}
    ${match.reason === match.quote ? "" : `<p>${esc(match.reason)}</p>`}<blockquote>${esc(match.quote)}</blockquote>
    <p class="by">${esc(match.source)} · ${esc(match.version)}</p></div>`;
}

function projectMail(mail) {
  if (!mail) return "";
  const statuses = {queued:"в очереди",sending:"отправляется",accepted:"принято",
    failed:"отклонено",uncertain:"подтверждение не получено"};
  return `<details><summary>Тестовое письмо · ${esc(mail.recipient)}</summary>
    <p>SMTP · ${esc(statuses[mail.status])}. ${mail.smtp_at ? esc(hDate.format(new Date(mail.smtp_at))) + " МСК." : ""}</p>
    <p>Входящие · ${mail.inbox_at ? "письмо найдено " + esc(hDate.format(new Date(mail.inbox_at))) + " МСК." : "появление письма пока не подтверждено."}</p></details>`;
}

function updateProjectMail(mail) {
  const node = document.querySelector("#project-mail-status");
  if (!node) return;
  const open = node.querySelector("details")?.open;
  node.innerHTML = projectMail(mail);
  if (open && node.firstElementChild) node.firstElementChild.open = true;
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
        ${item.related ? `<button class="primary" data-decision="link">Дополнить ${esc(item.related.id)}</button>` : ""}
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
  const pricesFirst=hashParams().get("tab")==="prices";
  const table=`<section class="panel"><h2>Цены и условия</h2>${productPrices(prices)}</section>`;
  return `<div class="wide radar-page">${hashParams().get("from") ? button("← Обзор магазина","funnel-back",overviewBack(),"link") :
    button("← Ассортимент","page","catalog","link")}
    <p class="eyebrow">Выбор предложения · ${prettyDate(prices.matched[0].date)}${state.data.cloud_research ? " · учебный замер" : " · EP2-06605"}</p><h1>${esc(item.title)}</h1>
    <section class="panel radar-signal down"><div><p class="label">Ценовой сигнал</p>
      <h2>${prices.below_store} из ${prices.matched.length} сопоставимых цен ниже Store</h2>
      <p>Цена Store · <strong>${number(prices.store)} ₽</strong>. Бессрочная лицензия на один ПК.</p>
      <p class="by">Сравнение по артикулу и отметке сопоставимости. Замер показывает цены на дату проверки.</p></div>
      ${state.data.cloud_research ? cloudRunButton("office",detail.run) :
        detail.run ? (detail.run.status === "done" ? button("К решению","finding-decision","","link") : "") :
        `<form id="radar-start-form" data-mode="office"><button class="primary">Исследовать предложение Office</button></form>`}
    </section>${messages()}${pricesFirst ? table : ""}${projectResult(detail.run)}${pricesFirst ? "" : table}
    <section class="panel"><h2>Самостоятельный счёт</h2><p>${esc(item.invoice.text)}</p>${sourceLink(item.invoice,"Открыть прохождение")}</section>
    <section class="panel"><h2>${state.data.cloud_research ? "Учебная инициатива" : "Инициатива Softline"}</h2><p>${esc(store.initiatives.office.text)}</p>
      ${sourceLink(store.initiatives.office,state.data.cloud_research ? "Открыть запись" : "Слайд 18")}${item.sources.map(s=>sourceLink(s)).join(" · ")}</section>
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
