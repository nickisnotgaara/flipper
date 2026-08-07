# Деплой Flipper на сервер

> Структура `flipper/services/` изменилась 2026-07-25 (см. `PLAN.md`).
> Подробная архитектура — в [SYSTEM.md](SYSTEM.md).

## Требования

- Linux VPS (Ubuntu 22.04+ / Debian 12+), рекомендуется Timeweb Cloud
- Docker Engine 24+ и Docker Compose Plugin v2
- Git
- Минимум 4 GB RAM, 40 GB disk (Firecrawl + Flipper + PostgreSQL)

---

## 1. Подготовка сервера

```bash
# Установить Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Перелогиниться чтобы группа docker подхватилась
```

---

## 2. Flippercrawl (self-hosted Firecrawl)

Firecrawl деплоится **отдельным** docker-compose. Flipper подключается к нему через общую Docker-сеть `firecrawl_backend`.

### 2.1 Клонировать и настроить Firecrawl

```bash
cd /opt
git clone https://github.com/mendableai/firecrawl.git flippercrawl
cd flippercrawl
```

Скопировать и отредактировать `.env`:

```bash
cp apps/api/.env.example apps/api/.env
nano apps/api/.env
```

Ключевые переменные:

```env
# Можно оставить пустым для self-hosted без auth
FIRECRAWL_API_KEY=local

# LLM для AI-экстракции (используется cian_active)
# OpenRouter / любой OpenAI-совместимый endpoint
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
MODEL_NAME=glm-4-9b-chat
```

### 2.2 Запустить Flippercrawl

```bash
cd /opt/flippercrawl
docker compose up -d
```

Проверить:

```bash
# API должен отвечать на порту 3002
curl http://localhost:3002/
```

### 2.3 Убедиться что сеть создана

Firecrawl автоматически создаёт сеть. Flipper подключается к ней как `external`. Проверить:

```bash
docker network ls | grep firecrawl_backend
```

Если сети нет (Firecrawl ещё не поднят или использует другое имя):

```bash
docker network create firecrawl_backend
```

> **Важно:** имя сети в `docker-compose.yml` Flipper — `firecrawl_backend`. Если в вашем Firecrawl она называется иначе, поменяйте в `docker-compose.yml` Flipper секцию `networks`.

---

## 3. Flipper — клонирование и настройка

```bash
cd /opt
git clone <repo-url> flipper
cd flipper
```

### 3.1 Файл окружения

```bash
cp .env.example .env
nano .env
```

Обязательные переменные:

| Переменная | Описание |
|---|---|
| `FIRECRAWL_API_KEY` | `local` (self-hosted без auth) |
| `FIRECRAWL_BASE_URL` | URL Firecrawl API (см. ниже) |
| `SPREADSHEET_ID` | ID Google Sheets документа |
| `TG_BOT_TOKEN` | Telegram бот токен |
| `TG_CHAT_ID` | ID чата для уведомлений |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL |
| `NOVNC_PUBLIC_URL` | `http://<IP сервера>:8080/vnc.html` |
| `WEEKLY_RUN_DAY_OF_WEEK` | День для winners/domclick (default: `sun`) |
| `WEEKLY_WINNERS_HOUR` | Час winners (default: `6`) |
| `WEEKLY_DOMCLICK_HOUR` | Час domclick (default: `7`) |

#### Firecrawl URL — какой указать?

В `docker-compose.yml` `cian_active` подключён к сети `firecrawl_backend`, поэтому может обращаться к Firecrawl по имени контейнера:

```env
# Имя контейнера Firecrawl API (обычно <project>-api-1)
# Проверить: docker ps --format '{{.Names}}' | grep api
FIRECRAWL_BASE_URL=http://flippercrawl-api-1:3002
```

Если DNS по имени контейнера не работает, используется fallback через хост:

```env
# Fallback — через host.docker.internal (настроено в docker-compose.yml)
# Работает если Firecrawl публикует порт 3002 на хосте
FIRECRAWL_BASE_URL=http://host.docker.internal:3002
```

> Проверить имя контейнера: `docker ps --format '{{.Names}}' | grep api`

### 3.2 Google Credentials

```bash
# С локальной машины
scp credentials.json root@<server-ip>:/opt/flipper/credentials.json
```

### 3.3 Прокси (резидентские)

```bash
mkdir -p data
# Формат: host:port:user:pass — по одному на строку
nano data/proxies.txt
```

Или скопировать готовый файл:

```bash
scp data/proxies.txt root@<server-ip>:/opt/flipper/data/proxies.txt
```

---

## 4. Сборка и запуск Flipper

```bash
cd /opt/flipper

# Собрать все образы (бэкенд + инфраструктура)
docker compose build

# Запустить инфраструктуру + бэкенд + scheduler
docker compose up -d
```

Проверить:

```bash
docker compose ps
```

Ожидаемый результат:

```
app_postgres          running (healthy)
app_redis             running (healthy)
cookie_manager        running (healthy)
html_to_markdown      running (healthy)
flipper_api           running (healthy)
flipper_scheduler     running
```

> `cian_active`, `category_counter`, `cian_sold`, `winners_sold`, `domclick_sold`, `flatinfo_houses` имеют `profiles: [manual]` — они **не** запускаются в `docker compose up`. Их запускает `scheduler` по расписанию или вы вручную.
>
> **`web` (Next.js) больше не в compose** — фронт собирается отдельно (см. раздел [12. Деплой фронтенда](#12-деплой-фронтенда)). Это сделано специально, чтобы при правке фронта не перезапускать Docker-стек.

### Проверить связность с Firecrawl

```bash
docker compose run --rm cian_active python -c "
import httpx, os
url = os.environ.get('FIRECRAWL_BASE_URL', 'http://host.docker.internal:3002')
r = httpx.get(url, timeout=5)
print(f'{url} -> {r.status_code}')
"
```

---

## 5. Миграция данных из secondary/ (один раз)

> Выполняется только если у вас есть файлы в `secondary/` от предыдущей структуры проекта.
> Если деплоите с нуля — пропустите.

### 5.1 Копирование secondary/ на сервер

```bash
scp -r secondary/ root@<server-ip>:/opt/secondary/
```

### 5.2 Убедиться что PostgreSQL запущен

```bash
docker compose up -d app_postgres
docker compose exec app_postgres pg_isready -U flipper
```

### 5.3 Запуск миграции

```bash
docker compose run --rm cian_sold \
    python -m scripts.migrate_secondary_files_to_postgres \
        --secondary /opt/secondary \
        --db "postgresql+asyncpg://flipper:${POSTGRES_PASSWORD:-flipper_secret}@app_postgres:5432/flipper"
```

Скрипт переливает:
- `secondary/cian/data/result.jsonl` → `houses` + `sold_ads` (source=`cian_sold`)
- `secondary/winners/all_advs*.json` → `houses` + `sold_ads` (source=`winners_sold`)
- `secondary/domclick/domclick_result.json` → `houses` + `sold_ads` (source=`domclick_sold`)
- `secondary/flatinfo/house_pages_result.json` → `houses` (source=`flatinfo_houses`)

Идемпотентен (upsert). После успешной миграции можно удалить `secondary/`.

### 5.4 Проверка миграции

```bash
docker compose exec app_postgres psql -U flipper -c "
  SELECT source, COUNT(*) FROM houses GROUP BY source;
  SELECT source, COUNT(*) FROM sold_ads GROUP BY source;
"
```

### 5.5 Удаление secondary/ (опц.)

```bash
rm -rf /opt/secondary/
```

---

## 6. Расписание (автоматическое)

Scheduler запущен в шаге 4. Расписание:

| Время (MSK) | Задача |
|---|---|
| 09:00 | `category_counter` |
| 10:00 | `cian_active --mode avans`, затем `--mode offers` |
| 18:00 | `cian_active --mode avans`, затем `--mode offers` |
| **Sun 06:00** | `winners_sold` (еженедельно) |
| **Sun 07:00** | `domclick_sold` (еженедельно) |

Остальные парсеры (`cian_sold`, `flatinfo_houses`) — **только вручную**.

Scheduler автоматически:
- Запускает контейнеры через `docker compose run --rm` (тот же сценарий, что и при ручном запуске по SSH на сервере: без `--no-deps`, чтобы сработали `depends_on` и healthcheck зависимостей)
- Повторяет при ошибке (до 3 попыток с exponential backoff)
- Отправляет Telegram-алерты при сбоях
- Использует lock чтобы задачи не пересекались

### 6.1 VPS (Linux-сервер): что важно для шедулера

Шедулер крутится **внутри контейнера** и вызывает `docker compose` на том же хосте (через смонтированный `/var/run/docker.sock`). Compose-проект берётся из каталога, примонтированного в контейнер как `/app` (корень репозитория на диске сервера, например `/opt/flipper`).

- **Пути к `credentials.json` и `data/` на хосте.** Чтобы одноразовые контейнеры `cian_active` / `category_counter` видели те же файлы, что и при `docker compose run` с SSH, в окружение подставляются абсолютные пути на **хосте**. Обычно они определяются автоматически из bind-mount (в логах: «корень репозитория на хосте …=…»). Если путь неверный или пустой — в `.env` на сервере задайте явно: `SCHEDULER_HOST_BIND_ROOT=/opt/flipper` (замените на ваш каталог с репозиторием).
- **Firecrawl.** Парсер ходит в Firecrawl по `FIRECRAWL_BASE_URL` / `PARSER_FIRECRAWL_BASE_URL`. На VPS по умолчанию часто `http://host.docker.internal:3002` (в `docker-compose.yml` у `cian_active` есть `extra_hosts: host.docker.internal:host-gateway`). Если Firecrawl в другом compose и в сети `firecrawl_backend`, в `.env` укажите URL вида `http://<имя_контейнера_api>:3002` и убедитесь, что сеть подключена к `cian_active`. Проверка — раздел «Проверить связность с Firecrawl» выше.
- **Ручной запуск с сервера** (`ssh` → `docker compose run …`) и **ночной cron шедулера** используют один Docker daemon и один проект — после правок они должны вести себя одинаково по сети и томам.

---

## 7. Ручной запуск парсеров

```bash
# Активные CIAN (через Firecrawl)
docker compose run --rm cian_active --mode offers
docker compose run --rm cian_active --mode avans

# Снятые CIAN (deactivated_offers) — обычно раз в месяц
docker compose run --rm cian_sold

# Еженедельные (запускаются автоматически, но можно вручную)
docker compose run --rm winners_sold
docker compose run --rm domclick_sold

# Реестр домов flatinfo — по запросу
docker compose run --rm flatinfo_houses

# Category counter
docker compose run --rm category_counter
```

---

## 8. Мониторинг

### Логи

```bash
# Все сервисы Flipper
docker compose logs -f

# Scheduler
docker compose logs -f scheduler

# Последний запуск cian_active
docker compose logs cian_active

# Firecrawl (из другого каталога)
cd /opt/flippercrawl && docker compose logs -f api
```

### Состояние БД

```bash
# Все источники в houses
docker compose exec app_postgres psql -U flipper -c "
  SELECT source, COUNT(*) FROM houses GROUP BY source ORDER BY source;
"

# Активные / снятые
docker compose exec app_postgres psql -U flipper -c "
  SELECT source, COUNT(*) FROM active_ads GROUP BY source ORDER BY source;
  SELECT source, COUNT(*) FROM sold_ads GROUP BY source ORDER BY source;
"
```

### Telegram-уведомления

Бот отправляет:

1. **Signal** — объявление добавлено в Signals_Parser (снижение цены)
2. **Signal удалён** — объявление убрано из Signals (критерии больше не выполняются)
3. **Продано / Аванс внесён** — объявление снято с публикации
4. **Scheduler: <task> FAILED** — задача упала после 3 попыток
5. **Куки слетели** — требуется обновить cookies через NoVNC

---

## 9. Обновление

### Flipper (бэкенд + инфраструктура)

```bash
cd /opt/flipper
git pull
docker compose build
docker compose up -d
# Если есть новые миграции схемы:
docker compose run --rm api alembic upgrade head
```

### Flipper (только бэкенд api, без пересборки остального)

```bash
cd /opt/flipper
git pull
docker compose build api
docker compose up -d api
```

### Flipper (только фронт — Docker не трогаем)

```bash
cd /opt/flipper
git pull
cd web/next
npm ci --no-audit --no-fund
npm run build
# Залить ./out на Vercel/Cloudflare Pages/nginx/S3 (см. web/next/README.md)
```

### Flippercrawl

```bash
cd /opt/flippercrawl
git pull
docker compose up -d --build
```

---

## 10. Бэкапы PostgreSQL

```bash
# Создать дамп
docker compose exec app_postgres pg_dump -U flipper flipper > backup_$(date +%Y%m%d_%H%M%S).sql

# Восстановить из дампа
cat backup_20260415.sql | docker compose exec -T app_postgres psql -U flipper flipper
```

Автоматические бэкапы — crontab хоста:

```bash
mkdir -p /opt/flipper/backups

# Добавить в crontab -e:
# Каждый день в 3:00
0 3 * * * cd /opt/flipper && docker compose exec -T app_postgres pg_dump -U flipper flipper | gzip > /opt/flipper/backups/flipper_$(date +\%Y\%m\%d).sql.gz
```

---

## 11. Структура сервисов

```
┌────────────────────────────────────────────────────────────────────┐
│  /opt/flippercrawl (отдельный docker-compose)                     │
│                                                                    │
│  ┌─────────────┐  ┌───────────┐  ┌───────────┐  ┌─────────────┐  │
│  │ firecrawl   │  │ playwright│  │  redis     │  │  rabbitmq   │  │
│  │ API :3002   │  │  service  │  │           │  │             │  │
│  └──────┬──────┘  └───────────┘  └───────────┘  └─────────────┘  │
│         │ сеть: firecrawl_backend                                  │
└─────────┼──────────────────────────────────────────────────────────┘
          │
          │ docker network (firecrawl_backend)
          │
┌─────────┼──────────────────────────────────────────────────────────┐
│  /opt/flipper (docker-compose)                                     │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────┐   cron (apscheduler)                            │
│  │  scheduler   │──────────┬─────────────────────┐               │
│  │  (always on) │          ▼                     ▼               │
│  │              │   ┌──────────────┐    ┌──────────────┐         │
│  └──────────────┘   │ cian_active  │    │category_count│         │
│                     │  profiles:   │    │  profiles:   │         │
│                     │  [manual]    │    │  [manual]    │         │
│                     │  10:00, 18:00│    │  09:00       │         │
│                     └──────┬───────┘    └──────────────┘         │
│                            │                                    │
│  ┌─────────────────────────┴───────────────────────────────┐    │
│  │  Parsers (manual + weekly):                             │    │
│  │   cian_sold       domclick_sold   flatinfo_houses       │    │
│  │   winners_sold    (Sun 06:00)    (Sun 07:00)            │    │
│  │   (вручную)        (еженедельно)  (вручную)              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    │
│  │ app_postgres │    │  cookie_manager  │    │  flipper_api │    │
│  │ (PostgreSQL) │    │ (FastAPI+NoVNC)  │    │  (FastAPI    │    │
│  └──────────────┘    └──────────────────┘    │   prod :8000)│    │
│                                                └──────┬───────┘    │
│  ┌──────────────┐    ┌──────────────────┐             │           │
│  │  app_redis   │    │ html_to_markdown │             │           │
│  └──────────────┘    └──────────────────┘             │           │
└──────────────────────────────────────────────────────┼───────────┘
                                                       │
                                            HTTP /api/* │
                                                       │
┌──────────────────────────────────────────────────────┼───────────┐
│  /opt/flipper/web/next/out/ (статика, НЕ в Docker)  │           │
│                                                       ▼           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Next.js static export  (HTML+JS+CSS)                        │  │
│  │  NEXT_PUBLIC_API_BASE → flipper_api:8000                      │  │
│  │  Деплой: Vercel / Cloudflare Pages / nginx / S3+CloudFront   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

Все парсеры пишут в **общую PostgreSQL** (`houses`, `active_ads`, `sold_ads`).
Подробнее — в [SYSTEM.md](SYSTEM.md).

> **Фронт (Next.js) намеренно вынесен из Docker-стека.** Подробности — в разделах [12. Деплой фронтенда](#12-деплой-фронтенда) и [web/next/README.md](web/next/README.md).

---

## 12. Деплой фронтенда

**Зачем вынесли:** раньше Next.js жил в `docker compose --profile dev up` рядом с FastAPI. Любая правка UI требовала рестарта контейнера. Теперь фронт собирается отдельно (`npm run build` → статика в `./web/next/out/`) и деплоится независимо от бэка. Правка фронта ≠ рестарт Docker.

### 12.1 Что собираем

- `web/next/` — Next.js 14 App Router с `output: 'export'` (см. `web/next/next.config.mjs`)
- Результат сборки: чистая статика в `web/next/out/` (HTML + JS + CSS + картинки)
- Никакого Node.js-сервера в рантайме не нужно

### 12.2 Где собирать

Два варианта:

| Где | Команда | Когда выбирать |
|---|---|---|
| Локально (CI runner, Mac, Linux) | `./scripts/deploy_web.sh` или `.\scripts\deploy_web.ps1` | Удобнее, проще отлаживать |
| Внутри Docker | `docker build -f web/next/Dockerfile.build -t flipper-web-build web/next` | Когда хост без Node.js или нужен воспроизводимый билд |

Оба варианта дают одинаковую статику в `out/`.

### 12.3 Конфигурация: куда ходит фронт

Фронт узнаёт URL бэка через `NEXT_PUBLIC_API_BASE` (см. `web/next/.env.example`).

**Перед сборкой задайте** либо через `.env` в `web/next/`, либо через переменную окружения:

```bash
# Отдельный домен API (рекомендуется)
export NEXT_PUBLIC_API_BASE=https://api.flipper.example.com
./scripts/deploy_web.sh

# Или единый домен + reverse proxy
export NEXT_PUBLIC_API_BASE=https://flipper.example.com
./scripts/deploy_web.sh
```

### 12.4 Варианты деплоя статики

**Vercel (проще всего):**
```bash
npm i -g vercel
vercel deploy --prebuilt --prod   # в web/next/, где лежит ./out
```

**Cloudflare Pages:**
```bash
npm i -g wrangler
wrangler pages deploy web/next/out --project-name flipper-web
```

**Netlify:**
```bash
npm i -g netlify-cli
netlify deploy --dir=web/next/out --prod
```

**nginx на своём сервере:**
```bash
rsync -av --delete web/next/out/ root@flipper.example.com:/var/www/flipper/
# Конфиг nginx → /etc/nginx/sites-available/flipper.conf:
#   root /var/www/flipper;
#   location / { try_files $uri $uri/ /index.html; }
#   location /api/ { proxy_pass http://127.0.0.1:8001; }  # → flipper_api
```

**S3 + CloudFront:**
```bash
aws s3 sync web/next/out/ s3://flipper-web/ --delete
aws cloudfront create-invalidation --distribution-id EXXXXX --paths "/*"
```

### 12.5 CORS

CORS управляется через переменную окружения `CORS_ORIGINS` (см. `web/server.py`).
По умолчанию `*` (любой origin — ок для dev). На проде сузьте до домена фронта
в `.env`:

```env
# .env (на проде)
CORS_ORIGINS=https://flipper.example.com,https://www.flipper.example.com
```

После изменения `.env` нужно перезапустить только `flipper_api`:

```bash
docker compose up -d --no-deps api
```

Фронт при этом не пересобирается и не рестартует.

### 12.6 Чего делать **не** надо

- ❌ Не кладите фронт обратно в `docker-compose.yml` (для этого есть `Dockerfile.build` — он опциональный, для CI).
- ❌ Не запускайте `npm run dev` на проде — это dev-сервер с hot reload, не предназначен для нагрузки.
- ❌ Не правьте `web/server.py` и фронт в одном коммите, если можно иначе: бэк рестартует контейнер, фронт требует ребилда.

### 12.7 Типичный цикл правки фронта

```bash
# Правлю компоненты в web/next/components/...
git add web/next/ && git commit -m "feat(web): новая кнопка"
git push                                            # CI сам соберёт и задеплоит
# ИЛИ локально:
./scripts/deploy_web.sh
wrangler pages deploy web/next/out --project-name flipper-web
```

Docker-стек (api, scheduler, postgres, парсеры) продолжает работать без изменений.

---

## Troubleshooting

### Firecrawl не отвечает из cian_active

```bash
cd /opt/flippercrawl && docker compose ps

# Проверить имя контейнера API
docker ps --format '{{.Names}}' | grep api

# Проверить что сеть firecrawl_backend существует и оба compose подключены
docker network inspect firecrawl_backend --format '{{range .Containers}}{{.Name}} {{end}}'

# Тест из контейнера cian_active
docker compose run --rm cian_active python -c "
import httpx, os
url = os.environ.get('FIRECRAWL_BASE_URL', 'http://host.docker.internal:3002')
print(httpx.get(url, timeout=5).status_code)
"
```

### PostgreSQL не стартует

```bash
docker compose logs app_postgres
docker volume ls | grep pgdata
```

### cian_active не подключается к PostgreSQL

```bash
docker compose run --rm cian_active env | grep DATABASE_URL
docker compose exec app_postgres pg_isready -U flipper
```

### Scheduler не запускает задачи

```bash
docker compose logs -f scheduler | grep -E "START|END|FAILED"
docker compose exec flipper_scheduler docker ps
```

### Cookie error

1. Открыть NoVNC: `http://<server-ip>:8080/vnc.html`
2. Вручную пройти капчу / залогиниться на cian.ru
3. Cookies обновятся автоматически

### Парсер не находит данные в БД

Проверьте, что файл JSON не пустой и таблицы созданы:

```bash
docker compose run --rm cian_sold \
    python -c "from packages.flipper_db import init_db; import asyncio; asyncio.run(init_db())"

docker compose exec app_postgres psql -U flipper -c "\dt"
```

Если таблиц нет — `init_db` не вызывался. Убедитесь, что при ручном запуске переменная `DATABASE_URL` доступна.

---

## Порты

| Порт | Сервис | Проект |
|---|---|---|
| 3002 | Firecrawl API | flippercrawl |
| 5432 | PostgreSQL | flipper |
| 6379 | Redis | flipper |
| 8000 | Cookie Manager API | flipper |
| 8080 | NoVNC | flipper |
| 8090 | HTML to Markdown | flipper |
