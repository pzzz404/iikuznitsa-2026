import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {once} from "node:events";
import {open, writeFile} from "node:fs/promises";
import {join} from "node:path";
import {pathToFileURL} from "node:url";

const [url, work, output] = process.argv.slice(2);
const {chromium} = await import(pathToFileURL(process.env.PM_PLAYWRIGHT ||
  "/opt/internal-tools/browser-qa/node_modules/playwright/index.mjs"));
const browser = await chromium.launch({
  headless:false, executablePath:process.env.PM_CHROMIUM ||
    "/home/pzzz/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome",
  ignoreDefaultArgs:["--enable-automation"],
  args:["--no-sandbox", "--disable-infobars", "--disable-translate", "--disable-features=Translate,TranslateUI",
        "--window-position=0,0", "--window-size=1440,900"],
});
const page = await browser.newPage({viewport:null, locale:"ru-RU"});
const button = name => page.getByRole("button", {name, exact:true});
const heading = name => page.getByRole("heading", {name, exact:true});
const byText = text => page.locator("p").getByText(text,{exact:true});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const captureLog = await open(join(work,"capture.log"), "w");
const events = [];
let capture;
let complete;
try {
  await page.goto(url);
  await heading("Что исследуем?").waitFor();
  await page.evaluate(() => document.fonts.ready);
  assert(await page.evaluate(() => document.fonts.check('400 16px Manrope')));
  assert.deepEqual(await page.evaluate(() => [innerWidth,innerHeight,screenX,screenY]), [1439,812,0,0]);
  const clean = await (await page.request.get(url + "/api/data")).json();
  assert(clean.sample && !clean.jury && clean.tasks.length === 0);
  const empty = await (await page.request.get(url + "/api/usage")).json();
  assert.equal(empty.usage.calls, 0);
  capture = spawn("ffmpeg", ["-hide_banner","-y","-loglevel","warning",
    "-thread_queue_size","512","-f","x11grab","-framerate","30","-video_size","1438x812",
    "-draw_mouse","0","-i",process.env.DISPLAY + ".0+0,87","-i",join(work,"narration.wav"),
    "-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","ultrafast","-threads","2",
    "-crf","16","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-t","180",
    "-movflags","+faststart",output], {stdio:["ignore","ignore",captureLog.fd]});
  complete = once(capture,"exit");
  const t0 = performance.now() + 350;
  const at = async (sec, name) => {
    const left = t0 + sec*1000 - performance.now();
    if (left > 0) await wait(left);
    const elapsed = (performance.now()-t0)/1000;
    assert(elapsed < sec+4, name + " запаздывает на " + (elapsed-sec).toFixed(1) + " с");
    events.push({name, time:elapsed});
  };

  await at(5,"Отдельный тестовый счётчик");
  await button("Источники").click();
  await button("Тестовый счётчик Яндекс.Метрики").click();
  await button("Проверить подключение").click();
  await byText("Тестовый счётчик участника пока не подключён.").or(
    page.getByText("Тестовый счётчик участника пока не подключён.",{exact:true})).first().waitFor();
  await at(11,"Контроль Kaspersky");
  await button("Сигналы").click();
  await page.locator('[data-topic="kes"]').click();
  await page.locator(".source-card").filter({hasText:"Заказы двух семейств"}).getByRole("button").click();
  await at(18,"Вопрос о самостоятельном счёте");
  await button("Закрыть источник").click();
  await page.locator('[data-topic="invoice"]').click();
  await at(21,"Первый вызов Qwen");
  const first = page.waitForResponse(r => r.url().endsWith("/api/study"), {timeout:38000});
  await button("Исследовать").click();
  const response = await first;
  const invoice = await response.json();
  assert.equal(response.status(),200,JSON.stringify(invoice));
  assert(invoice.focus && invoice.evidence.length > 0);
  await heading("Свидетельства разбора").waitFor();
  await at(48,"Карточка источника");
  const selected = page.locator(".source-card").filter({hasText:"Самостоятельный счёт"});
  const sourceInLibrary = !(await selected.count());
  if (sourceInLibrary) {
    await button("Источники").click();
    await button("Исторические материалы").click();
  }
  await selected.getByRole("button").click();
  await page.getByRole("dialog",{name:""}).waitFor();
  await at(58,"Редактирование критерия");
  await button("Закрыть источник").click();
  if (sourceInLibrary) await button("Сигналы").click();
  await page.locator("#create-task").scrollIntoViewIfNeeded();
  const criterion = "За 14 дней связать выбор счёта, выставление и оплату. Считать по организациям. Отдельно учитывать обращения к менеджеру.";
  await page.getByLabel("Критерий приёмки").fill("");
  await page.getByLabel("Критерий приёмки").pressSequentially(criterion,{delay:22});
  await at(71,"Сохранение задачи");
  await button("Сохранить в бэклог").click();
  await page.waitForURL(/#backlog\/1$/);
  await byText(criterion).waitFor();
  await at(80,"Повторная отправка");
  await button("Сигналы").click();
  await button("Сохранить в бэклог").click();
  await page.waitForURL(/#backlog\/1$/);
  await at(85,"Перезагрузка страницы");
  await page.reload();
  await byText(criterion).waitFor();
  assert.equal((await (await page.request.get(url + "/api/data")).json()).tasks.length,1);
  await at(91,"Другой вопрос");
  await button("Сигналы").click();
  await page.locator('[data-topic="repeat"]').click();
  const next = page.waitForResponse(r => r.url().endsWith("/api/study"), {timeout:36000});
  await button("Исследовать").click();
  const alternate = await next;
  const repeat = await alternate.json();
  assert.equal(alternate.status(),200,JSON.stringify(repeat));
  assert.equal(repeat.topic,"repeat");
  assert.notDeepEqual(invoice.selected,repeat.selected);
  await heading("Свидетельства разбора").waitFor();
  await at(117,"Журнал и тариф");
  await button("Журнал модели").click();
  await heading("Последние вызовы").waitFor();
  const journal = await (await page.request.get(url + "/api/usage")).json();
  assert.equal(journal.usage.calls,2);
  assert(journal.calls.every(row=>row.status==="ok"&&row.prompt_tokens>0&&row.completion_tokens>0));
  await at(133,"Открытие проверки");
  await button("Проверки").click();
  await page.locator("[data-check='1']").click();
  await byText("Исторический срез · ожидаем данные после релиза.").waitFor();
  await at(141,"Синтетические группы и решение PM");
  await page.getByLabel("Синтетическая выборка").check();
  const decision = "Оставить текущий путь. Собрать больше наблюдений перед расширением.";
  await page.getByLabel("Решение PM").fill(decision);
  await at(150,"Расчёт результата");
  await button("Сохранить и пересчитать").click();
  await byText("Данных недостаточно").waitFor();
  await heading("Эффект после релиза").evaluate(() => window.scrollTo(0,0));
  const snapshot = await (await page.request.get(url + "/api/data")).json();
  assert.equal(snapshot.tasks[0].plan.decision,decision);
  assert(snapshot.tasks[0].result.low<0&&snapshot.tasks[0].result.high>0);
  await writeFile(join(work,"take.json"), JSON.stringify({invoice,repeat,journal,task:snapshot.tasks[0],events},null,2));
  console.log(JSON.stringify(journal.usage));
  const [code] = await complete;
  assert.equal(code,0,"Ошибка записи экрана");
} catch(error) {
  if (capture && capture.exitCode === null) capture.kill("SIGINT");
  if (complete) await complete.catch(()=>{});
  throw error;
} finally {
  await browser.close();
  await captureLog.close();
}
