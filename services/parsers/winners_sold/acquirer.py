"""
services.parsers.winners_sold.acquirer - парсер данных из API baza-winner.ru.

Логика:
- Делает POST-запросы с шагом size=400 начиная с from=0 до from=MAX_FROM включительно.
- Собирает все элементы из поля "advs" в один общий список с сохранением порядка.
- Сохраняет результат в JSON.

Поддерживаются пресеты (категории):
- new       — новостройки (is_new_building=true), до from=33600
- secondary — вторичка     (is_new_building=false), до from=76400

Использование:
    python acquirer.py                       # по умолчанию: new
    python acquirer.py --category secondary  # вторичка -> all_advs_vtorichka.json
    python acquirer.py --category new --output all_advs.json
"""

import argparse
import copy
import json
import time
from pathlib import Path

import requests


# Пресеты под разные категории. Меняются только четыре вещи:
# order_id в URL, параметры wscg/wsct и флаг is_new_building в body,
# плюс максимальное значение from (зависит от общего количества объявлений).
PRESETS: dict[str, dict] = {
    "new": {
        "order_id": "32b57902-0ef1-4f30-b787-a1396a0fd9bb",
        "wscg": "3e32755b-736f-4259-990c-7e9b5d7f544c",
        "wsct": "2026-04-21T20:03:07.407Z",
        "is_new_building": True,
        "max_from": 33_600,
        "output_filename": "all_advs.json",
    },
    "secondary": {
        "order_id": "1d049503-4f7b-4430-b99f-4cb6707c8c12",
        "wscg": "c3566a3e-5f24-40d4-ac32-eed8adf7005c",
        "wsct": "2026-04-21T20:51:56.435Z",
        "is_new_building": False,
        "max_from": 76_400,
        "output_filename": "all_advs_vtorichka.json",
    },
}


URL_TEMPLATE = (
    "https://mls.baza-winner.ru/v2/users/546849/orders/"
    "{order_id}/items/_search.json"
)

HEADERS = {
    "accept": "*/*",
    "accept-language": "en,ru;q=0.9,en-US;q=0.8,uz;q=0.7",
    "access-token": "My2Cx7RZOTkhNQBSHTe7BYNFuPqBJZZ7rscMCUUFQIgpnA0j6txbTIXQMoNDb9Kg",
    "access_token": "My2Cx7RZOTkhNQBSHTe7BYNFuPqBJZZ7rscMCUUFQIgpnA0j6txbTIXQMoNDb9Kg",
    "content-type": "application/json",
    "origin": "https://w7.baza-winner.ru",
    "priority": "u=1, i",
    "referer": "https://w7.baza-winner.ru/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

# Базовое тело запроса (from будет подставляться динамически).
BASE_PAYLOAD = {
    "aggregations": {
        "avg_price_rub": True,
        "avg_meter_price_rub": True,
        "avg_total_price_rub": True,
        "avg_sotka_price_rub": True,
    },
    "fields": [
        "guid", "deal_status_id", "user_deal_status_id", "winner_relevance",
        "w6_offer_id", "external_id", "area", "is_new_building", "object_guid",
        "free_mode_relevance", "is_selected", "is_favorite", "is_hidden",
        "is_exclusive_mark1", "is_sended_to_viewboard", "is_liked_on_viewboard",
        "is_disliked_on_viewboard", "is_monitored", "photo_count", "video_count",
        "total_room_count", "offer_room_count", "is_studio", "is_free_planning",
        "realty_type_id", "geo_cache_subway_station_name_1",
        "geo_subway_station_guid_1", "transport_access_1", "walking_access_1",
        "geo_cache_subway_station_name_2", "geo_subway_station_guid_2",
        "transport_access_2", "walking_access_2",
        "geo_cache_subway_station_name_3", "geo_subway_station_guid_3",
        "transport_access_3", "walking_access_3",
        "geo_cache_subway_station_name_4", "geo_subway_station_guid_4",
        "transport_access_4", "walking_access_4", "geo_cache_state_name",
        "geo_cache_region_name", "geo_cache_town_name", "geo_cache_street_name",
        "geo_cache_building_name", "geo_cache_town_name_2",
        "geo_cache_settlement_name", "geo_cache_estate_object_name",
        "geo_cache_district_name", "geo_cache_micro_district_name",
        "geo_cache_street_name_2", "is_construction_address",
        "geo_cache_housing_complex_name", "storey", "storeys_count",
        "walls_material_type_id", "building_batch_name", "built_year",
        "balcony_type_id", "total_square", "life_square", "kitchen_square",
        "ceiling_height", "price_rub", "meter_price_rub", "creation_datetime",
        "pub_datetime", "offer_pub_duration", "media_id", "media_name",
        "broker.short_name", "broker.url", "external_url", "external_seller_2",
        "phone_list.is_black", "phone_list.black_note", "has_online_presentation",
        "is_published_by_probable_owner", "external_jk_bc", "phone_list_xz",
        "deal_type_id", "security_type_id", "user_note", "price_change_date",
        "price_change_type_id", "video_list", "client_association_list",
        "ownership_type_id", "sale_type_name", "agency_bonus",
        "agency_bonus_type_id", "agency_bonus_currency_type_id",
        "rooms_adjacency_type_id",
    ],
    "sort": [
        {"winner_relevance": {"order": "desc"}},
        {"w6_offer_id": {"order": "desc"}},
    ],
    "from": 0,
    "size": 400,
    "conditions": {
        "published_days_ago": {"days": 180},
        "realty_section": {"code": ["flat"]},
        "deal_type": {"code": ["sale"]},
        "area": {"code": ["msk"]},
        "is_deal_actual": False,
        "media": {"id": [17]},
        "is_new_building": True,
        "is_apartment": False,
        "is_first_storey": False,
        "is_auction": False,
        "geo_administrative_district": {
            "guid": [
                "324F978F-AE52-4DEC-B39A-A6BFB78AD399",
                "A8465B3C-94E7-40B9-BCFC-A852A100BEA7",
                "1FA76533-6A2D-4560-8E28-60E52573FD0F",
                "9A2A132F-FFD4-422B-8A0F-84E238383FEA",
            ]
        },
        "geo_district": {
            "guid": [
                "5EB17E9A-B530-47F1-B592-D1666051800A",
                "AE9720DC-7931-4DD3-8BD5-E09DE742F8A3",
                "FF2279BD-2725-4BD4-BF97-3A0A364E0573",
                "3087FEF0-0472-473C-9C7B-047D2D859C34",
                "95A92072-9FE2-4694-8B29-AC3596689550",
                "8B4AE1CD-B226-4167-8A14-CA0195E4D6E5",
                "EC386E19-9B45-46BB-B841-3F0885CEB6BB",
                "4E11209E-9DDA-4B78-B3E7-6F07AD8C051C",
                "C2342757-6CAB-4410-97C4-55C5FE4368C1",
                "4C3C5D49-AD0A-4754-BD56-5D6489785EF3",
                "C0230E22-E269-4841-A229-EC9D7D01E023",
                "835ECB65-DCE0-44B9-8B06-495EF901ABBF",
                "0715C00E-1BBE-4128-97F2-8D7E61196E5F",
                "5BD86C38-7E6E-41AA-A289-F64A18FB6064",
                "8487FAD5-8786-45B9-96B0-8FCBD560DB65",
                "4DD6BB44-7377-4E18-B4D3-3C8A7F61B31D",
                "162484AC-527A-4EB6-97FE-4E7E0F0A336D",
                "1A7339D2-51B1-4A79-8695-1E978E4BC787",
                "D17E3BFA-8936-4DCD-A62A-8E92310754CC",
                "E7D5C0F9-D336-424B-87B6-61D0E031C9E4",
                "491E36E9-BB03-4242-8A61-2853F9016ED3",
                "5278DF53-B5E2-45C4-BBC4-B393DBAC5EA1",
                "359C559B-0F6B-4158-9598-5DF5D129BD24",
                "3052E452-5614-4B16-BEB7-5F83B928132D",
                "7A628DDF-0B94-4B3E-981C-4118721BB67A",
                "A1BBBFF7-1B33-4851-8F53-9EC06FAC52C2",
                "1B6DD49E-D7E1-410D-9B5D-3E1AA6A24369",
                "A2A8F25F-E024-4047-87BE-2379058D4B0C",
                "F519F935-DEB9-44B0-B6F3-B9CA5BF084E3",
                "0DDCA454-5704-4C85-88FA-74CEAFA94023",
                "22267AEE-8B4D-4A39-87E9-A8F336ACF5C0",
                "10447A48-969D-4FAA-9938-1BB9844CAC60",
                "3165F484-39D8-41D8-961E-A55157C1B68D",
                "2260A0E0-7F0B-4F26-A7DE-A16A03AD1833",
                "B773A2CE-B87F-4EFC-B7BB-AD5586ED54A4",
                "B4D3FA5D-1056-4406-A555-183FB7361371",
                "3D850BCE-8206-4402-8151-9B2D2AC1FEC1",
                "D6A50FA6-7049-4556-B78D-557912FD0DEF",
                "85BE0765-B313-40FC-A12D-A56F6D1BDE8F",
                "F1EB41AB-F414-4C09-A8BA-915C0E9AEB54",
                "3CA481EF-8916-42F4-8D62-3A90B6F47DAF",
                "86667DFE-B510-4E5A-9227-49A08097FE6A",
                "A2F03B82-3C8B-4E13-8247-3FF0B5A91BFD",
                "3C1E51B9-D999-4F20-9F72-D141746D4CDE",
                "92F9DF31-5325-4E0B-8647-CC7D128AD34F",
                "2EB0BEB6-7D87-41EF-B6E2-8CB74FA539E8",
                "D9D1CAC4-DDFA-470F-A4E3-DACBB9D519C9",
                "541E6C6B-098A-4745-86D0-3484B84903E1",
                "7A18CBD8-67F3-4252-82B5-E056CE58E3FC",
                "B97A82B9-B2AE-40A3-BA27-069B5743E6A8",
                "39CB6915-A934-49CB-834B-C9B4C5ABC6CE",
                "A4E14734-CAB0-414F-86CC-EBD8C6EAFAC2",
                "19E7DCA9-07A8-49AB-80B4-5C28007B8B22",
                "85256EE0-FBAC-4D98-8A05-3D2C23145F73",
                "F3E476D4-0EB0-47F4-87A1-02E2E058BBA1",
                "FB9C2746-DBC9-422F-A943-0E117F73B454",
                "ECEDFF09-EF87-402A-9A4A-44BDF01D4CB9",
                "0A2C33A3-7027-4BC2-9FDB-2AB5E3A8363C",
                "D4B91109-9C25-4B83-B74B-C1B46A4DE486",
                "4F610D18-67B8-4212-8EC7-DC4A1C26DA78",
                "9E954563-2C49-4567-870D-079C5116C46E",
                "7F6FF6A8-DC4A-4B43-894C-012645C6B244",
                "7959D298-C8EF-4F7F-B7C3-74CD8E68169A",
                "E4F79321-62F9-479A-989B-BFAE8871C8F2",
                "27911BC7-FC9B-440F-B701-2859870DDEF2",
            ]
        },
    },
    "filters": {"is_hidden": False, "use_or_offer_mark": True},
    "mixins": {"is_selected": True, "is_hidden": False},
    "dsl_version": 2,
}


PAGE_SIZE = 400
MAX_RETRIES = 5        # Сколько раз повторить запрос при сетевой ошибке.
SLEEP_BETWEEN = 0.3    # Пауза между запросами (сек).


def fetch_page(
    session: requests.Session,
    url: str,
    query_params: dict,
    payload_template: dict,
    from_value: int,
) -> list[dict]:
    """Запрашивает одну страницу и возвращает список advs."""
    payload = dict(payload_template)
    payload["from"] = from_value
    payload["size"] = PAGE_SIZE

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(
                url,
                params=query_params,
                headers=HEADERS,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("advs", []) or []
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            wait = 2 ** attempt
            print(
                f"  [!] from={from_value} попытка {attempt}/{MAX_RETRIES} "
                f"провалилась: {exc}. Жду {wait}с..."
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Не удалось получить страницу from={from_value}: {last_error}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Парсер объявлений из API baza-winner.ru с пагинацией.",
    )
    parser.add_argument(
        "--category", choices=sorted(PRESETS.keys()), default="new",
        help="Категория: new (новостройки) или secondary (вторичка). "
             "По умолчанию: new.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Путь к выходному JSON. По умолчанию берётся из пресета.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preset = PRESETS[args.category]

    url = URL_TEMPLATE.format(order_id=preset["order_id"])
    query_params = {
        "project_code": "w7",
        "pack_history": "1",
        "except_null": "1",
        "return_restricted": "1",
        "wscg": preset["wscg"],
        "wsct": preset["wsct"],
    }

    # Готовим шаблон payload и подставляем флаг категории.
    payload_template = copy.deepcopy(BASE_PAYLOAD)
    payload_template["conditions"]["is_new_building"] = preset["is_new_building"]

    max_from = preset["max_from"]
    output_file = args.output or (Path(__file__).parent / preset["output_filename"])

    print(f"Категория: {args.category} "
          f"(is_new_building={preset['is_new_building']})")
    print(f"URL:       {url}")
    print(f"Выход:     {output_file}")

    session = requests.Session()
    all_advs: list[dict] = []
    from_values = list(range(0, max_from + 1, PAGE_SIZE))
    total_pages = len(from_values)

    print(f"Всего страниц к загрузке: {total_pages} (from 0 ... {max_from})\n")

    for idx, from_value in enumerate(from_values, start=1):
        print(f"[{idx}/{total_pages}] Запрос from={from_value}...", end=" ")
        advs = fetch_page(session, url, query_params, payload_template, from_value)
        print(f"получено {len(advs)} элементов (всего: {len(all_advs) + len(advs)})")
        all_advs.extend(advs)

        if idx < total_pages:
            time.sleep(SLEEP_BETWEEN)

    print(f"\nИтого собрано: {len(all_advs)} объявлений")
    print(f"Сохраняю в {output_file}...")

    with output_file.open("w", encoding="utf-8") as fp:
        json.dump(all_advs, fp, ensure_ascii=False, indent=2)

    print("Готово!")


if __name__ == "__main__":
    main()
