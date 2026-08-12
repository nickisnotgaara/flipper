# API парсера карточек Cian

Документ для клиентского проекта, который ходит в Flippercrawl API за данными объявлений Cian.

## Кратко

| Было | Стало |
|------|--------|
| `POST /v2/scrape` | `POST /v2/cian/scrape` |
| Тело ~160 строк: `url`, `excludeTags`, `formats`, `schema`, `systemPrompt`, `headers` | Тело: только `url` и опционально `headers` |
| Каждая карточка → LLM (медленно, дорого) | Сначала статический парсер (быстро, без токенов); LLM только при сбое |

Формат **успешного ответа** тот же, что у `/v2/scrape`: `success`, `data`, `data.json` с полями объявления. Добавлено служебное поле `_extraction_mode`.

---

## Эндпоинт

```
POST /v2/cian/scrape
```

- Авторизация: как у scrape — заголовок `Authorization: Bearer <API_KEY>`
- `Content-Type: application/json`
- Биллинг / лимиты: те же middleware, что у `/v2/scrape` (1 credit за запрос)

Работает и при включённом `API_SCRAPE_ONLY` (вместе с обычным `/v2/scrape`).

---

## Запрос

### Минимальный

```json
{
  "url": "https://www.cian.ru/sale/flat/313326812/"
}
```

### С Cookie (если нужна авторизованная сессия Cian)

```json
{
  "url": "https://www.cian.ru/sale/flat/313326812/",
  "headers": {
    "Cookie": "_CIAN_GK=...; session_region_id=1; ..."
  }
}
```

### Поля

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `url` | `string` | да | URL карточки продажи квартиры на Cian |
| `headers` | `Record<string, string>` | нет | HTTP-заголовки при загрузке страницы (чаще всего только `Cookie`) |

### Допустимые URL

Регулярное выражение на сервере:

```
^https?://([a-z0-9-]+\.)?cian\.ru/sale/flat/\d+/?(\?.*)?$
```

Примеры **валидных** URL:

- `https://www.cian.ru/sale/flat/313326812/`
- `https://www.cian.ru/sale/flat/313326812`
- `https://irkutsk.cian.ru/sale/flat/327214373/`
- `https://www.cian.ru/sale/flat/313326812/?utm_source=google`

Примеры **невалидных** (ответ `400`):

- аренда: `https://www.cian.ru/rent/flat/...`
- дома: `https://www.cian.ru/sale/suburban/...`
- не Cian: `https://avito.ru/...`

### Что больше не нужно слать с клиента

На сервере зашиты (раньше были в `scrape_body_current.json`):

- `excludeTags`
- `formats`: `markdown`, `rawHtml`, `json` со схемой и `systemPrompt`

Источник правды в репозитории: [`apps/api/src/lib/cian/requestTemplate.ts`](../apps/api/src/lib/cian/requestTemplate.ts).

При изменении схемы или промпта достаточно обновить API — клиент менять не нужно.

---

## Ответ

### Успех (`200`)

```json
{
  "success": true,
  "data": {
    "markdown": "...",
    "rawHtml": "...",
    "json": {
      "_extraction_mode": "static",
      "cian_id": "313326812",
      "price": 940500000,
      "price_per_m2": 1816425,
      "title": "Продается многокомнатная квартира, 517,5 м²",
      "description": "...",
      "address": {
        "full": "Москва, ЗАО, р-н Раменки, ...",
        "district": "Раменки",
        "metro_station": "Ломоносовский проспект",
        "okrug": "ЗАО"
      },
      "area": 517.5,
      "rooms": 6,
      "housing_type": "Вторичка",
      "building_type": "Монолитный",
      "floor_info": { "current": 9, "all": 9 },
      "construction_year": 2020,
      "renovation": "Без ремонта",
      "metro_walk_time": 21,
      "total_views": 1546,
      "unique_views": 4,
      "is_active": true,
      "has_avans_deposit": false,
      "price_history": [
        {
          "date": "2025-02-06",
          "price": 885000000,
          "change_type": "initial",
          "change_amount": 0
        }
      ]
    },
    "metadata": { ... }
  }
}
```

### Поле `_extraction_mode`

| Значение | Значение для клиента |
|----------|----------------------|
| `"static"` | Данные извлечены детерминированным парсером (встроенный JSON Cian на странице). Без LLM, быстрее и дешевле. **Ожидаемый режим в норме.** |
| `"llm"` | Статика не справилась (изменилась структура страницы и т.п.) — ответ собран через LLM-fallback. Данные есть, но дороже; на сервере запускается попытка авто-починки парсера. |

Рекомендация для мониторинга: логировать долю `llm` — рост означает деградацию статики.

Клиент может **игнорировать** `_extraction_mode` при записи в БД или сохранять отдельно для метрик.

### Поля `data.json`

Схема совпадает с прежним клиентским `scrape_body_current.json`.

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `cian_id` | `string` | да | ID из URL (`/sale/flat/<id>/`) |
| `price` | `integer` | да | Цена, ₽ |
| `area` | `number` | да | Площадь, м² |
| `price_per_m2` | `integer` | нет | Цена за м² (считается на сервере) |
| `title` | `string` | нет | Заголовок карточки |
| `description` | `string` | нет | Текст описания продавца |
| `address.full` | `string` | нет | Полный адрес |
| `address.district` | `string` | нет | Район |
| `address.metro_station` | `string` | нет | Ближайшее метро (без слова «метро») |
| `address.okrug` | `string` | нет | Округ (ЦАО, ЗАО, …) |
| `rooms` | `integer` | нет | Число комнат |
| `housing_type` | `string` | нет | `Вторичка` или `Новостройка` |
| `building_type` | `string \| null` | нет | Тип дома (Панельный, Кирпичный, …) |
| `floor_info.current` | `integer` | нет | Этаж |
| `floor_info.all` | `integer` | нет | Этажей в доме |
| `construction_year` | `integer` | нет | Год постройки |
| `renovation` | `string` | нет | Тип ремонта |
| `metro_walk_time` | `integer` | нет | Минут пешком до ближайшего метро |
| `total_views` | `integer` | нет | Всего просмотров |
| `unique_views` | `integer` | нет | Просмотров за сегодня |
| `is_active` | `boolean` | нет | Объявление активно |
| `has_avans_deposit` | `boolean` | нет | Признак внесённого аванса/задатка |
| `price_history` | `array` | нет | История цены (см. ниже) |

Отсутствующие необязательные поля могут быть `null`.

### `price_history`

Сервер нормализует историю после извлечения:

- `date` → формат `YYYY-MM-DD`
- строки отсортированы от старых к новым
- `change_amount` и `change_type` (`initial` | `increase` | `decrease`) пересчитываются на бэкенде

Клиенту **не нужно** дублировать эту логику.

---

## Ошибки

| HTTP | `success` | Когда |
|------|-----------|--------|
| `400` | `false` | Нет `url`, невалидный JSON, URL не карточка `sale/flat` на `*.cian.ru` |
| `403` | `false` | Нет прав / блоклист |
| `408` | `false` | Таймаут scrape |
| `500` | `false` | Внутренняя ошибка |

Пример `400`:

```json
{
  "success": false,
  "error": "URL must be a cian.ru flat sale listing, e.g. https://www.cian.ru/sale/flat/123456/"
}
```

---

## Миграция клиента

### Было (`POST /v2/scrape`)

```http
POST /v2/scrape
Authorization: Bearer <token>
Content-Type: application/json

<содержимое scrape_body_current.json — url, excludeTags, formats, schema, systemPrompt, headers>
```

### Стало (`POST /v2/cian/scrape`)

```http
POST /v2/cian/scrape
Authorization: Bearer <token>
Content-Type: application/json

{
  "url": "https://www.cian.ru/sale/flat/313326812/",
  "headers": {
    "Cookie": "..."
  }
}
```

### Чеклист

1. Заменить URL эндпоинта на `/v2/cian/scrape`.
2. Убрать из тела `excludeTags`, `formats`, `schema`, `systemPrompt`.
3. Оставить `url`; `headers.Cookie` — по необходимости.
4. Читать данные по-прежнему из `response.data.json`.
5. Опционально: сохранять `data.json._extraction_mode` для метрик.
6. Убедиться, что в коде не завязаны на поля, которых не было в старой схеме (кроме `_extraction_mode`).

Старый `POST /v2/scrape` с полным телом **продолжает работать**, но всегда идёт через LLM — для Cian использовать его не рекомендуется.

---

## Примеры кода

### cURL

```bash
curl -s -X POST "https://<HOST>/v2/cian/scrape" \
  -H "Authorization: Bearer $FLIPPERCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.cian.ru/sale/flat/313326812/"}'
```

### TypeScript (fetch)

```typescript
type CianListing = {
  _extraction_mode?: "static" | "llm";
  cian_id: string;
  price: number;
  area: number;
  // ... остальные поля схемы
};

async function scrapeCianFlat(url: string, cookie?: string): Promise<CianListing> {
  const res = await fetch(`${API_BASE}/v2/cian/scrape`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      url,
      ...(cookie ? { headers: { Cookie: cookie } } : {}),
    }),
  });

  const body = await res.json();
  if (!res.ok || !body.success) {
    throw new Error(body.error ?? `HTTP ${res.status}`);
  }
  return body.data.json as CianListing;
}
```

### Python (requests)

```python
import requests

def scrape_cian_flat(url: str, cookie: str | None = None) -> dict:
    payload = {"url": url}
    if cookie:
        payload["headers"] = {"Cookie": cookie}

    r = requests.post(
        f"{API_BASE}/v2/cian/scrape",
        json=payload,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(body.get("error", "scrape failed"))
    return body["data"]["json"]
```

---

## Поведение на сервере (для понимания, не для интеграции)

1. Загружается HTML карточки Cian (с прокси/Cookie как у обычного scrape).
2. Из `rawHtml` читается встроенный стейт `frontend-offer-card` → `defaultState.offerData`.
3. Поля маппятся в `data.json` по конфигу на сервере.
4. При сбое — LLM с той же схемой и промптом (`_extraction_mode: "llm"`).
5. При повторяющихся сбоях сервер может автоматически обновить конфиг маппинга (self-heal); клиенту ничего делать не нужно.

---

## Связанные файлы в репозитории

| Файл | Назначение |
|------|------------|
| [`apps/api/src/controllers/v2/cian-scrape.ts`](../apps/api/src/controllers/v2/cian-scrape.ts) | Контроллер эндпоинта |
| [`apps/api/src/lib/cian/requestTemplate.ts`](../apps/api/src/lib/cian/requestTemplate.ts) | Схема, промпт, excludeTags |
| [`apps/api/src/lib/cian/mappingEngine.ts`](../apps/api/src/lib/cian/mappingEngine.ts) | Статический маппинг |
| [`scrape_body_current.json`](../scrape_body_current.json) | Прежний клиентский запрос (reference) |

Тесты: `apps/api/src/lib/cian/__tests__/cian-static.test.ts` (20 реальных карточек), `apps/api/src/__tests__/snips/v2/cian-scrape.test.ts` (e2e).
