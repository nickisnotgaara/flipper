"""Bootstrap Grist docs: Парсинг (7 таблиц) + Архивы (6 таблиц)."""
import os, time
import requests
h = {'Authorization': 'Bearer flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978'}
GRIST = 'http://127.0.0.1:8484'

PARSING_DOC = 'iATJMEN94wpWGST4WMMjvB'  # Parsing (Personal)
ARCHIVES_DOC = 'kaBfATwGgUYjDa8doqMzk3'  # Archives (flipper)


def col(name, type_name):
    return {'id': name, 'label': name, 'type': type_name}


def add_table(doc_id, name, cols):
    r = requests.post(f'{GRIST}/api/docs/{doc_id}/apply', headers=h,
                      json=[['AddTable', name, [col(n, t) for n, t in cols]]])
    print(f'  {name}: {r.status_code} {r.text[:120]}')
    time.sleep(0.3)


# === Парсинг: 7 таблиц ===
PARSING_TABLES = {
    'FILTERS': [
        ('pg_id', 'Int'),
        ('filter_id', 'Int'),
        ('name', 'Text'),
        ('description', 'Text'),
        ('min_year', 'Int'),
        ('max_year', 'Int'),
        ('districts', 'Text'),
        ('active', 'Bool'),
    ],
    'Аванс': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('cian_id', 'Text'),
        ('url', 'Text'),
        ('price', 'Numeric'),
        ('price_per_m2', 'Int'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('floor_current', 'Int'),
        ('floor_total', 'Int'),
        ('metro_station', 'Text'),
        ('metro_walk_time', 'Int'),
        ('district', 'Text'),
        ('okrug', 'Text'),
        ('renovation', 'Text'),
        ('days_in_exposition', 'Int'),
        ('publish_date', 'Date'),
        ('has_avans_deposit', 'Bool'),
        ('updated_at', 'DateTime'),
    ],
    'Аванс_Продано': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_id', 'Text'),
        ('url', 'Text'),
        ('price', 'Numeric'),
        ('price_per_m2', 'Int'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('floor_current', 'Int'),
        ('floor_total', 'Int'),
        ('metro_station', 'Text'),
        ('renovation', 'Text'),
        ('exposition_days', 'Int'),
        ('publish_date', 'Date'),
        ('sold_date', 'Date'),
    ],
    'Продано': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_id', 'Text'),
        ('url', 'Text'),
        ('house_id', 'Int'),
        ('price', 'Numeric'),
        ('price_per_m2', 'Int'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('floor_current', 'Int'),
        ('floor_total', 'Int'),
        ('metro_station', 'Text'),
        ('renovation', 'Text'),
        ('exposition_days', 'Int'),
        ('publish_date', 'Date'),
        ('sold_date', 'Date'),
    ],
    'Balans': [
        ('pg_id', 'Int'),
        ('address', 'Text'),
        ('rooms', 'Int'),
        ('area', 'Numeric'),
        ('price_estimated', 'Numeric'),
        ('price_actual', 'Numeric'),
        ('delta', 'Numeric'),
        ('status', 'Text'),
        ('updated_at', 'DateTime'),
    ],
    'Offers_Parser': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('cian_id', 'Text'),
        ('url', 'Text'),
        ('price', 'Numeric'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('filter_id', 'Int'),
        ('district', 'Text'),
        ('publish_date', 'Date'),
        ('parsed_at', 'DateTime'),
    ],
    'Signals_Parser': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('cian_id', 'Text'),
        ('url', 'Text'),
        ('signal_type', 'Text'),
        ('description', 'Text'),
        ('price', 'Numeric'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('district', 'Text'),
        ('detected_at', 'DateTime'),
    ],
}

print('=== Парсинг (7 tables) ===')
for name, cols in PARSING_TABLES.items():
    add_table(PARSING_DOC, name, cols)

# === Архивы: 6 таблиц ===
ARCHIVES_TABLES = {
    'CianSold': [  # 231K — будет пустая пока (split нужен)
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_id', 'Text'),
        ('url', 'Text'),
        ('house_id', 'Int'),
        ('price', 'Numeric'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('metro_station', 'Text'),
        ('district', 'Text'),
        ('sold_date', 'Date'),
        ('publish_date', 'Date'),
    ],
    'DomclickSold': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_id', 'Text'),
        ('url', 'Text'),
        ('house_id', 'Int'),
        ('price', 'Numeric'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('metro_station', 'Text'),
        ('sold_date', 'Date'),
    ],
    'WinnersNovostroiki': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_house_id', 'Text'),
        ('address', 'Text'),
        ('developer', 'Text'),
        ('price_from', 'Numeric'),
        ('price_to', 'Numeric'),
        ('year_built', 'Int'),
        ('deadline', 'Text'),
        ('lat', 'Numeric'),
        ('lng', 'Numeric'),
    ],
    'WinnersVtorichka': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_house_id', 'Text'),
        ('address', 'Text'),
        ('price', 'Numeric'),
        ('area', 'Numeric'),
        ('rooms', 'Int'),
        ('year_built', 'Int'),
        ('lat', 'Numeric'),
        ('lng', 'Numeric'),
    ],
    'FlatInfoHouses': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_house_id', 'Text'),
        ('address', 'Text'),
        ('lat', 'Numeric'),
        ('lng', 'Numeric'),
        ('year_built', 'Int'),
        ('levels', 'Int'),
        ('building_type', 'Text'),
    ],
    'HousesAll': [
        ('pg_id', 'Int'),
        ('source', 'Text'),
        ('external_house_id', 'Text'),
        ('address', 'Text'),
        ('street', 'Text'),
        ('house_num', 'Text'),
        ('district', 'Text'),
        ('okrug', 'Text'),
        ('lat', 'Numeric'),
        ('lng', 'Numeric'),
        ('year_built', 'Int'),
        ('levels', 'Int'),
        ('building_type', 'Text'),
    ],
}

print('\n=== Архивы (6 tables) ===')
for name, cols in ARCHIVES_TABLES.items():
    add_table(ARCHIVES_DOC, name, cols)
