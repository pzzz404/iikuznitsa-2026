# PM Radar

Помощник продукт-менеджера интернет-магазина. На обзоре магазина видны решения по Astra, Kaspersky и Office. Из сигнала Kaspersky можно запустить исследование. Qwen формирует поисковые запросы, выбирает записи и предлагает проверку. Менеджер открывает первоисточник, дополняет T-08 и назначает владельца и срок. В карточке сохраняются решение, проверка после релиза и фактические токены каждого вызова.

## Запуск на учебных данных

Понадобятся Python 3.11+, openpyxl и для исследования локальная Qwen2.5 Instruct в формате GGUF с llama.cpp. Воронку и карточки можно посмотреть до подключения модели. Команды выполняются из корня клона ветки jury.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'openpyxl>=3.1,<4'
python demo/sample_store.py .demo-data/sample
PM_DATA_DIR="$PWD/.demo-data/db" \
PM_EVIDENCE_FILE="$PWD/.demo-data/sample/input.json" \
PM_STORE_FILE="$PWD/.demo-data/sample/store.json" \
PM_RESEARCH_FILE="$PWD/.demo-data/sample/research.json" \
python prototype/app.py
```

Откройте [PM Radar на своём компьютере](http://127.0.0.1:18763). Все числа и интервью в этом режиме вымышлены. Для запуска исследования поднимите модель в другом терминале и оставьте её работать.

```bash
llama-server -m /path/to/qwen2.5-instruct.gguf --host 127.0.0.1 --port 18764 -c 4096 -np 1 --alias pm-local
```

Выберите **Kaspersky → Открыть отклонение → Исследовать Kaspersky с Qwen**. По завершении откройте источник, затем «Принять решение» и «Дополнить T-08». Из сохранённой задачи можно открыть связанную проверку. На защищённом стенде также работает экспорт CSV для Redmine. В находке раскройте «Расход исследования» для просмотра входных и выходных токенов, времени и количества вызовов.

## Запуск с материалами задачи

Ролик записан на исторических данных Softline. У организаторов та же версия кода рассчитывает показатели по предоставленным материалам. Сохраните Excel-книги и презентацию в закрытом каталоге `source/`, включая исходную подпапку интервью. Подготовьте файлы для чтения приложением.

```bash
mkdir -p .demo-data/partner
python prototype/store_history.py .demo-data/partner/store.json
python prototype/research_corpus.py .demo-data/partner/research.json
PM_DATA_DIR="$PWD/.demo-data/partner/db" \
PM_STORE_FILE="$PWD/.demo-data/partner/store.json" \
PM_RESEARCH_FILE="$PWD/.demo-data/partner/research.json" \
python prototype/app.py
```

Книги, выгрузки источников, базы, учётные данные, приглашения и файл модели хранятся отдельно от публичного Git. Для просмотра защищённого стенда организатор получает ссылку-приглашение от участника. Интеграции включают локальный Qwen, отдельный замер OpenRouter на синтетическом наборе, экспорт CSV для Redmine и тестовое почтовое уведомление при наличии конфигурации.
