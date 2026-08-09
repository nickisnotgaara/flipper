"""Пересоздаём таблицы в Парсинг-доке в правильном порядке: Продано (с данными) первой."""
import time
import requests

h = {'Authorization': 'Bearer flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978'}
GRIST = 'http://127.0.0.1:8484'
DOC = 'mDaHoGD6yahtxaqugwr5mK'  # Парсинг

# 1) Удаляем все таблицы
r = requests.get(f'{GRIST}/api/docs/{DOC}/tables', headers=h)
for t in r.json().get('tables', []):
    rr = requests.post(f'{GRIST}/api/docs/{DOC}/apply', headers=h,
                       json=[['RemoveTable', t['id']]])
    print(f'  remove {t["id"]}: {rr.status_code}')
    time.sleep(0.2)

# 2) Создаём в правильном порядке (порядок AddTable = порядок tableId)
# Сначала Продано (с данными!), потом всё остальное
TABLES = {
    'Продано': [
        ('pg_id','Int'),('source','Text'),('external_id','Text'),('url','Text'),
        ('house_id','Int'),('price','Numeric'),('price_per_m2','Int'),('area','Numeric'),
        ('rooms','Int'),('floor_current','Int'),('floor_total','Int'),
        ('renovation','Text'),('exposition_days','Int'),('publish_date','Date'),
        ('sold_date','Date'),
    ],
    'FILTERS': [
        ('pg_id','Int'),('filter_id','Int'),('name','Text'),('description','Text'),
        ('min_year','Int'),('max_year','Int'),('districts','Text'),('active','Bool'),
    ],
    'Аванс': [
        ('pg_id','Int'),('source','Text'),('cian_id','Text'),('url','Text'),
        ('price','Numeric'),('price_per_m2','Int'),('area','Numeric'),('rooms','Int'),
        ('floor_current','Int'),('floor_total','Int'),('metro_station','Text'),
        ('metro_walk_time','Int'),('district','Text'),('okrug','Text'),('renovation','Text'),
        ('days_in_exposition','Int'),('publish_date','Date'),('has_avans_deposit','Bool'),
        ('updated_at','DateTime'),
    ],
    'Аванс_Продано': [
        ('pg_id','Int'),('source','Text'),('external_id','Text'),('url','Text'),
        ('price','Numeric'),('price_per_m2','Int'),('area','Numeric'),('rooms','Int'),
        ('floor_current','Int'),('floor_total','Int'),('metro_station','Text'),
        ('renovation','Text'),('exposition_days','Int'),('publish_date','Date'),
        ('sold_date','Date'),
    ],
    'Balans': [
        ('pg_id','Int'),('address','Text'),('rooms','Int'),('area','Numeric'),
        ('price_estimated','Numeric'),('price_actual','Numeric'),('delta','Numeric'),
        ('status','Text'),('updated_at','DateTime'),
    ],
    'Offers_Parser': [
        ('pg_id','Int'),('source','Text'),('cian_id','Text'),('url','Text'),
        ('price','Numeric'),('area','Numeric'),('rooms','Int'),('filter_id','Int'),
        ('district','Text'),('publish_date','Date'),('parsed_at','DateTime'),
    ],
    'Signals_Parser': [
        ('pg_id','Int'),('source','Text'),('cian_id','Text'),('url','Text'),
        ('signal_type','Text'),('description','Text'),('price','Numeric'),
        ('area','Numeric'),('rooms','Int'),('district','Text'),('detected_at','DateTime'),
    ],
}

for name, cols in TABLES.items():
    r = requests.post(f'{GRIST}/api/docs/{DOC}/apply', headers=h,
                      json=[['AddTable', name, [{'id': n, 'label': n, 'type': t} for n, t in cols]]])
    print(f'  create {name}: {r.status_code}')
    time.sleep(0.3)

# 3) Проверим порядок
r = requests.get(f'{GRIST}/api/docs/{DOC}/tables', headers=h)
print('\nFinal order:')
for t in r.json().get('tables', []):
    print(f"  {t['id']}")
