"""Deterministic mock weather provider.

Used as the default provider so the app is fully runnable and testable
without any third-party API key. Values are seeded from the location id
and the current time bucket so they stay stable within a run but still
vary sensibly by city and by day.
"""

import hashlib
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SKY_STATES = ["맑음", "구름조금", "구름많음", "흐림", "비", "소나기", "눈"]

ALERT_POOL = [
    {"level": "주의보", "title": "폭염주의보", "description": "낮 최고기온이 33도 이상으로 예상되어 온열질환에 유의해야 합니다."},
    {"level": "주의보", "title": "호우주의보", "description": "시간당 30mm 안팎의 강한 비가 예상됩니다. 저지대 침수에 유의하세요."},
    {"level": "경보", "title": "강풍경보", "description": "순간풍속 20m/s 이상의 강한 바람이 예상됩니다. 시설물 관리에 유의하세요."},
    {"level": "주의보", "title": "건조주의보", "description": "대기가 매우 건조하여 산불 등 화재 위험이 높습니다."},
    {"level": "주의보", "title": "한파주의보", "description": "아침 최저기온이 영하 12도 이하로 예상됩니다."},
]


def _seed(location_id: str, salt: str = "") -> int:
    digest = hashlib.sha256(f"{location_id}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16)


def _base_temp(location_id: str, month: int) -> float:
    # Rough seasonal curve so mock data still "feels" like Korean weather.
    seasonal = {1: 0, 2: 2, 3: 8, 4: 14, 5: 19, 6: 23, 7: 27, 8: 28, 9: 23, 10: 16, 11: 8, 12: 2}
    jitter = (_seed(location_id) % 700) / 100.0 - 3.5  # +/- 3.5 degrees per city
    return seasonal.get(month, 15) + jitter


class MockProvider:
    name = "mock"

    def get_weather(self, location: dict) -> dict:
        now = datetime.now(KST)
        base_temp = _base_temp(location["id"], now.month)
        seed = _seed(location["id"], now.strftime("%Y-%m-%d"))

        sky_idx = seed % len(SKY_STATES)
        current_sky = SKY_STATES[sky_idx]
        humidity = 40 + (seed % 45)
        wind_speed = round(0.5 + (seed % 60) / 10, 1)
        wind_dir_deg = seed % 360
        precip_prob = seed % 5 == 0 and (seed % 100) or (seed % 30)

        current = {
            "temp": round(base_temp + (seed % 40) / 10 - 2, 1),
            "feels_like": round(base_temp + (seed % 40) / 10 - 2 + (1 if humidity > 70 else -0.5), 1),
            "humidity": humidity,
            "wind_speed": wind_speed,
            "wind_dir": _wind_dir_label(wind_dir_deg),
            "sky": current_sky,
            "sky_code": _sky_code(current_sky),
            "precip_type": "없음" if current_sky not in ("비", "소나기", "눈") else current_sky,
            "precip_prob": precip_prob,
            "pm10": 15 + (seed % 90),
            "pm10_grade": _grade(15 + (seed % 90), [30, 80, 150]),
            "pm25": 8 + (seed % 60),
            "pm25_grade": _grade(8 + (seed % 60), [15, 35, 75]),
            "updated_at": now.isoformat(),
        }

        hourly = []
        for h in range(24):
            t = now + timedelta(hours=h + 1)
            hseed = _seed(location["id"], t.strftime("%Y-%m-%d %H"))
            sky = SKY_STATES[hseed % len(SKY_STATES)]
            diurnal = 4 * _diurnal_factor(t.hour)
            hourly.append({
                "time": t.strftime("%H:%M"),
                "date": t.strftime("%Y-%m-%d"),
                "temp": round(base_temp + diurnal + (hseed % 20) / 10 - 1, 1),
                "sky": sky,
                "sky_code": _sky_code(sky),
                "precip_prob": hseed % 100 if hseed % 6 == 0 else hseed % 25,
                "precip_type": "없음" if sky not in ("비", "소나기", "눈") else sky,
            })

        daily = []
        weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]
        for d in range(7):
            date = now + timedelta(days=d)
            dseed = _seed(location["id"], date.strftime("%Y-%m-%d"))
            sky_am = SKY_STATES[dseed % len(SKY_STATES)]
            sky_pm = SKY_STATES[(dseed // 7) % len(SKY_STATES)]
            spread = 6 + (dseed % 5)
            tmax = round(base_temp + spread / 2 + (dseed % 10) / 10, 1)
            tmin = round(tmax - spread, 1)
            daily.append({
                "date": date.strftime("%Y-%m-%d"),
                "label": "오늘" if d == 0 else ("내일" if d == 1 else weekday_labels[date.weekday()]),
                "temp_min": tmin,
                "temp_max": tmax,
                "sky_am": sky_am,
                "sky_pm": sky_pm,
                "precip_prob_am": dseed % 100 if dseed % 5 == 0 else dseed % 20,
                "precip_prob_pm": (dseed // 3) % 100 if dseed % 4 == 0 else (dseed // 3) % 20,
            })

        alerts = []
        if seed % 4 == 0:
            alert = dict(ALERT_POOL[seed % len(ALERT_POOL)])
            alert["area"] = location["name"]
            alert["issued_at"] = (now - timedelta(hours=seed % 12)).isoformat()
            alerts.append(alert)

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


def _diurnal_factor(hour: int) -> float:
    # Peaks mid-afternoon, lowest just before dawn.
    import math
    return math.sin((hour - 6) / 24 * 2 * math.pi)


def _sky_code(sky: str) -> str:
    return {
        "맑음": "clear",
        "구름조금": "partly_cloudy",
        "구름많음": "mostly_cloudy",
        "흐림": "cloudy",
        "비": "rain",
        "소나기": "showers",
        "눈": "snow",
    }.get(sky, "cloudy")


def _wind_dir_label(deg: int) -> str:
    dirs = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"]
    return dirs[int((deg + 22.5) // 45) % 8]


def _grade(value: int, thresholds: list) -> str:
    labels = ["좋음", "보통", "나쁨", "매우나쁨"]
    for i, t in enumerate(thresholds):
        if value <= t:
            return labels[i]
    return labels[-1]
