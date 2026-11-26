import assert from "node:assert/strict";
import {writeFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";

const [url, output] = process.argv.slice(2);
const {chromium} = await import(process.env.PM_PLAYWRIGHT ? pathToFileURL(process.env.PM_PLAYWRIGHT) : "playwright");
const browser = await chromium.launch({headless:true, args:["--no-sandbox"],
  executablePath:process.env.PM_CHROMIUM});
try {
  const page = await browser.newPage({viewport:{width:1366,height:900}});
  const button = name => page.getByRole("button",{name,exact:true});
  await page.goto(url);
  await page.getByText("Синтетический сценарий · OpenRouter",{exact:true}).waitFor();
  const pending = page.waitForResponse(r => r.url().endsWith("/api/study"),{timeout:85000});
  await button("Исследовать").click();
  const response = await pending;
  const study = await response.json();
  if (!response.ok()) throw Error(study.error || "Ошибка OpenRouter");
  assert(study.model.startsWith("qwen/qwen3-32b") && study.evidence.length > 0);
  await page.getByRole("heading",{name:"Свидетельства разбора"}).waitFor();
  await button("Открыть источник").first().click();
  await page.getByRole("dialog").getByText("Синтетический набор",{exact:false}).waitFor();
  await button("Закрыть источник").click();
  const criterion = "Связать выбор счёта с выставлением и оплатой за 14 дней. Единица измерения — компания.";
  await page.getByLabel("Критерий приёмки").fill(criterion);
  await button("Сохранить в бэклог").click();
  await page.waitForURL(/#backlog\/\d+$/);
  const taskId = Number(page.url().split("/").at(-1));
  await page.reload();
  await page.locator("p").getByText(criterion,{exact:true}).waitFor();
  await button("Журнал модели").click();
  await page.getByRole("heading",{name:"Последние вызовы"}).waitFor();
  const snapshot = await (await page.request.get(url+"/api/data")).json();
  const task = snapshot.tasks.find(t => t.id===taskId);
  const journal = await (await page.request.get(url+"/api/usage")).json();
  assert(task && task.criterion===criterion);
  await writeFile(output, JSON.stringify({study, task, journal},null,2), {mode:0o600});
  assert(task.calls.length > 0);
  assert(task.calls.every(call => call.platform==="OpenRouter" && call.currency==="USD" &&
    call.actual_cost!=null && call.receipt && call.generation && call.model==="qwen/qwen3-32b" &&
    call.prompt_tokens>0 && call.completion_tokens>0));
  console.log(JSON.stringify({task:task.id, usage:task.usage}));
} finally {
  await browser.close();
}
