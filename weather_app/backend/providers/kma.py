"""기상청(KMA) 공공데이터포털 provider.

Uses three data.go.kr services, all authorized with the same general
"OpenAPI 활용신청" service key (KMA_SERVICE_KEY):

- VilageFcstInfoService_2.0 / getVilageFcst   -> 3-day short-term forecast (hourly + daily)
- VilageFcstInfoService_2.0 / getUltraSrtNcst -> current observed conditions
- WthrWrnInfoService / getWthrWrnList          -> active 기상특보 (weather warnings)
- ArpltnInforInqireSvc (AirKorea)              -> nearby station + realtime PM10/PM2.5

Get a key at https://www.data.go.kr (search "기상청_단기예보 조회서비스" and
"한국환경공단_에어코리아_대기오염정보", 활용신청 -> 승인 후 발급되는 인증키를
KMA_SERVICE_KEY 에 넣으면 됩니다. 승인은 대개 즉시~1일 이내).

The real API's exact field layout can only be fully verified against a live
key, so every parsing step here is defensive: unexpected/missing fields fall
back to sensible defaults instead of raising, and get_weather() as a whole
falls back to MockProvider on any network/parsing failure so the app never
breaks because of an upstream hiccup.
"""

from datetime import datetime, timedelta, timezone

import requests

from .mock import MockProvider, _sky_code, _wind_dir_label, _grade

KST = timezone(timedelta(hours=9))

VILAGE_FCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
ULTRA_NCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
WARNING_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
AIR_STATION_URL = "https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getNearbyMsrstnList"
AIR_RLTM_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

PTY_MAP = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기", "5": "빗방울", "6": "빗방울눈날림", "7": "눈날림"}
SKY_MAP = {"1": "맑음", "3": "구름많음", "4": "흐림"}

REQUEST_TIMEOUT = 6


class KmaProvider:
    name = "kma"

    def __init__(self, service_key: str):
        self.service_key = service_key
        self._fallback = MockProvider()

    def get_weather(self, location: dict) -> dict:
        try:
            hourly, daily = self._get_forecast(location)
            current = self._get_current(location, hourly)
            alerts = self._get_alerts(location)
            aq = self._get_air_quality(location)
            current.update(aq)
            return {
                "provider": self.name,
                "location": {
                    "id": location["id"],
                    "name": location["name"],
                    "lat": location["lat"],
                    "lon": location["lon"],
                },
                "current": current,
                "hourly": hourly,
                "daily": daily,
                "alerts": alerts,
            }
        except Exception:
            # Upstream API hiccup / unexpected shape / missing key permission for
            # one of the sub-services: degrade gracefully instead of a 500.
            fallback = self._fallback.get_weather(location)
            fallback["provider"] = "mock (kma fallback)"
            return fallback

    # -- helpers ---------------------------------------------------------

    def _params(self, extra: dict) -> dict:
        return {
            "serviceKey": self.service_key,
            "dataType": "JSON",
            "numOfRows": 1000,
            "pageNo": 1,
            **extra,
        }

    def _latest_base(self) -> tuple:
        """Latest published (base_date, base_time) for getVilageFcst, allowing
        for the ~10 minute publish delay after each of the 8 daily runs."""
        now = datetime.now(KST) - timedelta(minutes=10)
        run_hours = [2, 5, 8, 11, 14, 17, 20, 23]
        candidate = now
        for h in reversed(run_hours):
            if now.hour >= h:
                candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
                break
        else:
            candidate = (now - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
        return candidate.strftime("%Y%m%d"), candidate.strftime("%H%M")

    def _get_forecast(self, location: dict):
        base_date, base_time = self._latest_base()
        resp = requests.get(
            VILAGE_FCST_URL,
            params=self._params({
                "base_date": base_date,
                "base_time": base_time,
                "nx": location["nx"],
                "ny": location["ny"],
            }),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()["response"]["body"]["items"]["item"]

        by_slot: dict = {}
        daily_extremes: dict = {}
        for it in items:
            key = (it["fcstDate"], it["fcstTime"])
            slot = by_slot.setdefault(key, {})
            slot[it["category"]] = it["fcstValue"]
            if it["category"] in ("TMN", "TMX"):
                d = daily_extremes.setdefault(it["fcstDate"], {})
                d[it["category"]] = it["fcstValue"]

        now = datetime.now(KST)
        hourly = []
        for (date, time_str), slot in sorted(by_slot.items()):
            dt = datetime.strptime(f"{date}{time_str}", "%Y%m%d%H%M").replace(tzinfo=KST)
            if dt < now or len(hourly) >= 24:
                continue
            sky = SKY_MAP.get(slot.get("SKY"), "구름많음")
            pty = PTY_MAP.get(slot.get("PTY", "0"), "없음")
            hourly.append({
                "time": dt.strftime("%H:%M"),
                "date": dt.strftime("%Y-%m-%d"),
                "temp": _to_float(slot.get("TMP"), 15.0),
                "sky": sky if pty == "없음" else pty,
                "sky_code": _sky_code(pty if pty != "없음" else sky),
                "precip_prob": _to_int(slot.get("POP"), 0),
                "precip_type": pty,
            })

        daily = []
        dates = sorted(daily_extremes.keys()) or sorted({d for d, _ in by_slot.keys()})[:7]
        weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]
        for i, date in enumerate(dates[:7]):
            dt = datetime.strptime(date, "%Y%m%d")
            extremes = daily_extremes.get(date, {})
            am_slot = by_slot.get((date, "0900"), {})
            pm_slot = by_slot.get((date, "1500"), {})
            daily.append({
                "date": dt.strftime("%Y-%m-%d"),
                "label": "오늘" if i == 0 else ("내일" if i == 1 else weekday_labels[dt.weekday()]),
                "temp_min": _to_float(extremes.get("TMN"), None),
                "temp_max": _to_float(extremes.get("TMX"), None),
                "sky_am": SKY_MAP.get(am_slot.get("SKY"), "-"),
                "sky_pm": SKY_MAP.get(pm_slot.get("SKY"), "-"),
                "precip_prob_am": _to_int(am_slot.get("POP"), 0),
                "precip_prob_pm": _to_int(pm_slot.get("POP"), 0),
            })

        return hourly, daily

    def _get_current(self, location: dict, hourly: list) -> dict:
        now = datetime.now(KST)
        base_time = (now - timedelta(minutes=40)).strftime("%H%M")[:2] + "00"
        base_date = now.strftime("%Y%m%d") if now.hour > 0 or now.minute >= 40 else (now - timedelta(days=1)).strftime("%Y%m%d")
        try:
            resp = requests.get(
                ULTRA_NCST_URL,
                params=self._params({
                    "base_date": base_date,
                    "base_time": base_time,
                    "nx": location["nx"],
                    "ny": location["ny"],
                }),
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            items = resp.json()["response"]["body"]["items"]["item"]
            vals = {it["category"]: it["obsrValue"] for it in items}
            temp = _to_float(vals.get("T1H"), hourly[0]["temp"] if hourly else 15.0)
            humidity = _to_int(vals.get("REH"), 60)
            wind_speed = _to_float(vals.get("WSD"), 1.0)
            wind_deg = _to_int(vals.get("VEC"), 0)
            pty = PTY_MAP.get(vals.get("PTY", "0"), "없음")
            sky_label = pty if pty != "없음" else (hourly[0]["sky"] if hourly else "맑음")
        except Exception:
            temp = hourly[0]["temp"] if hourly else 15.0
            humidity = 60
            wind_speed = 1.0
            wind_deg = 0
            pty = "없음"
            sky_label = hourly[0]["sky"] if hourly else "맑음"

        return {
            "temp": temp,
            "feels_like": round(temp - (0.5 if humidity > 70 else 0), 1),
            "humidity": humidity,
            "wind_speed": wind_speed,
            "wind_dir": _wind_dir_label(wind_deg),
            "sky": sky_label,
            "sky_code": _sky_code(sky_label),
            "precip_type": pty,
            "precip_prob": hourly[0]["precip_prob"] if hourly else 0,
            "updated_at": now.isoformat(),
        }

    def _get_alerts(self, location: dict) -> list:
        try:
            resp = requests.get(
                WARNING_URL,
                params=self._params({"stnId": "108"}),
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()["response"]["body"]
            raw_items = body.get("items", {}).get("item", [])
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
        except Exception:
            return []

        alerts = []
        for it in raw_items:
            area_text = it.get("t6", "") or it.get("areaName", "")
            if location["warn_region"] not in area_text and area_text:
                continue
            alerts.append({
                "level": it.get("t2", "특보"),
                "title": it.get("t1", it.get("title", "기상특보")),
                "area": area_text or location["name"],
                "description": it.get("t4", it.get("content", "")),
                "issued_at": it.get("tmFc", it.get("t3", "")),
            })
        return alerts

    def _get_air_quality(self, location: dict) -> dict:
        try:
            station_resp = requests.get(
                AIR_STATION_URL,
                params=self._params({
                    "tmX": location["lon"],
                    "tmY": location["lat"],
                    "returnType": "json",
                }),
                timeout=REQUEST_TIMEOUT,
            )
            station_resp.raise_for_status()
            station_items = station_resp.json()["response"]["body"]["items"]
            station_name = station_items[0]["stationName"]

            rltm_resp = requests.get(
                AIR_RLTM_URL,
                params=self._params({
                    "stationName": station_name,
                    "dataTerm": "DAILY",
                    "ver": "1.3",
                    "returnType": "json",
                }),
                timeout=REQUEST_TIMEOUT,
            )
            rltm_resp.raise_for_status()
            item = rltm_resp.json()["response"]["body"]["items"][0]
            pm10 = _to_int(item.get("pm10Value"), 30)
            pm25 = _to_int(item.get("pm25Value"), 15)
            return {
                "pm10": pm10,
                "pm10_grade": _grade(pm10, [30, 80, 150]),
                "pm25": pm25,
                "pm25_grade": _grade(pm25, [15, 35, 75]),
            }
        except Exception:
            return {"pm10": None, "pm10_grade": "정보없음", "pm25": None, "pm25_grade": "정보없음"}


def _to_float(value, default):
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
