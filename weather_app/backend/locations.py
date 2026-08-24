"""Curated list of Korean cities with the coordinates each weather provider needs.

- lat/lon: used for AccuWeather location lookup and for display.
- nx/ny: KMA(기상청) 단기예보 API 격자 좌표 (5km grid, standard published conversion table).
- warn_region: KMA 기상특보 구역 코드 접두어 (broad region grouping used to match 특보 발표 지역명).
"""

LOCATIONS = [
    {"id": "seoul", "name": "서울", "name_en": "Seoul", "lat": 37.5665, "lon": 126.9780, "nx": 60, "ny": 127, "warn_region": "서울"},
    {"id": "busan", "name": "부산", "name_en": "Busan", "lat": 35.1796, "lon": 129.0756, "nx": 98, "ny": 76, "warn_region": "부산"},
    {"id": "daegu", "name": "대구", "name_en": "Daegu", "lat": 35.8714, "lon": 128.6014, "nx": 89, "ny": 90, "warn_region": "대구"},
    {"id": "incheon", "name": "인천", "name_en": "Incheon", "lat": 37.4563, "lon": 126.7052, "nx": 55, "ny": 124, "warn_region": "인천"},
    {"id": "gwangju", "name": "광주", "name_en": "Gwangju", "lat": 35.1595, "lon": 126.8526, "nx": 58, "ny": 74, "warn_region": "광주"},
    {"id": "daejeon", "name": "대전", "name_en": "Daejeon", "lat": 36.3504, "lon": 127.3845, "nx": 67, "ny": 100, "warn_region": "대전"},
    {"id": "ulsan", "name": "울산", "name_en": "Ulsan", "lat": 35.5384, "lon": 129.3114, "nx": 102, "ny": 84, "warn_region": "울산"},
    {"id": "sejong", "name": "세종", "name_en": "Sejong", "lat": 36.4801, "lon": 127.2890, "nx": 66, "ny": 103, "warn_region": "세종"},
    {"id": "suwon", "name": "수원", "name_en": "Suwon", "lat": 37.2636, "lon": 127.0286, "nx": 60, "ny": 121, "warn_region": "경기"},
    {"id": "goyang", "name": "고양", "name_en": "Goyang", "lat": 37.6584, "lon": 126.8320, "nx": 57, "ny": 128, "warn_region": "경기"},
    {"id": "yongin", "name": "용인", "name_en": "Yongin", "lat": 37.2411, "lon": 127.1776, "nx": 64, "ny": 119, "warn_region": "경기"},
    {"id": "seongnam", "name": "성남", "name_en": "Seongnam", "lat": 37.4201, "lon": 127.1262, "nx": 63, "ny": 124, "warn_region": "경기"},
    {"id": "cheonan", "name": "천안", "name_en": "Cheonan", "lat": 36.8151, "lon": 127.1139, "nx": 64, "ny": 93, "warn_region": "충남"},
    {"id": "cheongju", "name": "청주", "name_en": "Cheongju", "lat": 36.6424, "lon": 127.4890, "nx": 69, "ny": 106, "warn_region": "충북"},
    {"id": "jeonju", "name": "전주", "name_en": "Jeonju", "lat": 35.8242, "lon": 127.1480, "nx": 63, "ny": 89, "warn_region": "전북"},
    {"id": "yeosu", "name": "여수", "name_en": "Yeosu", "lat": 34.7604, "lon": 127.6622, "nx": 73, "ny": 66, "warn_region": "전남"},
    {"id": "mokpo", "name": "목포", "name_en": "Mokpo", "lat": 34.8118, "lon": 126.3922, "nx": 50, "ny": 67, "warn_region": "전남"},
    {"id": "pohang", "name": "포항", "name_en": "Pohang", "lat": 36.0190, "lon": 129.3435, "nx": 102, "ny": 94, "warn_region": "경북"},
    {"id": "andong", "name": "안동", "name_en": "Andong", "lat": 36.5684, "lon": 128.7294, "nx": 91, "ny": 106, "warn_region": "경북"},
    {"id": "gyeongju", "name": "경주", "name_en": "Gyeongju", "lat": 35.8562, "lon": 129.2247, "nx": 100, "ny": 91, "warn_region": "경북"},
    {"id": "changwon", "name": "창원", "name_en": "Changwon", "lat": 35.2281, "lon": 128.6811, "nx": 91, "ny": 77, "warn_region": "경남"},
    {"id": "chuncheon", "name": "춘천", "name_en": "Chuncheon", "lat": 37.8813, "lon": 127.7298, "nx": 73, "ny": 134, "warn_region": "강원"},
    {"id": "gangneung", "name": "강릉", "name_en": "Gangneung", "lat": 37.7519, "lon": 128.8761, "nx": 92, "ny": 131, "warn_region": "강원"},
    {"id": "jeju", "name": "제주", "name_en": "Jeju", "lat": 33.4996, "lon": 126.5312, "nx": 52, "ny": 38, "warn_region": "제주"},
]


def find_location(location_id: str):
    for loc in LOCATIONS:
        if loc["id"] == location_id:
            return loc
    return None


def search_locations(query: str):
    if not query:
        return LOCATIONS
    q = query.strip().lower()
    return [
        loc
        for loc in LOCATIONS
        if q in loc["name"].lower() or q in loc["name_en"].lower()
    ]
