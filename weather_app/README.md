# 날씨알리미 (Weather Alert)

한국 날씨 종합 정보(현재 날씨·시간별/주간 예보·기상특보·미세먼지)를 한 화면에서
보여주는 아이폰 전용 웹앱(PWA)입니다. Safari에서 "홈 화면에 추가"로 설치하면
네이티브 앱처럼 아이콘으로 실행됩니다.

데이터는 **AccuWeather** 또는 **기상청(KMA) 공공데이터포털** 중 설정된 provider에서
가져오며, 둘 다 설정하지 않으면 앱을 바로 체험할 수 있도록 결정론적 **샘플(mock)
데이터**로 동작합니다.

## 왜 네이티브 iOS 앱이 아니라 PWA인가

이 프로젝트는 Xcode/iOS 시뮬레이터가 없는 Linux 환경에서 개발되었습니다. 네이티브
Swift 앱은 코드만 작성할 뿐 빌드·실행 확인이 불가능하지만, PWA는 이 환경에서 실제로
서버를 켜고 Safari(모바일 뷰포트)에서 동작을 검증할 수 있어 이 방식을 선택했습니다.
iPhone Safari에서는 일반 웹앱과 동일하게 완전히 동작하고, 홈 화면에 추가하면 별도
앱스토어 배포 없이 아이콘 실행·전체화면·오프라인 캐싱까지 지원합니다.

## 기능

- **현재 날씨**: 기온, 체감온도, 습도, 바람, 강수확률, 하늘 상태
- **미세먼지 / 초미세먼지**: 등급별 색상 표시 (좋음/보통/나쁨/매우나쁨)
- **시간별 예보**: 24시간
- **주간 예보**: 7일 (최저/최고 기온 막대 그래프)
- **기상특보 알림 배너**: 호우/폭염/한파/강풍 등 특보 발효 시 상단에 표시
- **지역 검색 + 즐겨찾기**: 24개 주요 도시, localStorage에 즐겨찾기 저장
- **알림**: 브라우저 알림 권한을 허용하면 앱이 열려 있는 동안 5분마다 특보를 확인해 알려줍니다
- **iPhone 최적화 UI**: 다크모드 대응, 하단 탭바, safe-area(노치/홈 인디케이터) 대응

## 빠른 시작 (샘플 데이터로 바로 체험)

```bash
cd weather_app
pip install -r requirements.txt
python backend/app.py
```

`http://localhost:8080` 을 iPhone Safari로 열거나(같은 네트워크에서 컴퓨터의
IP로 접속), 컴퓨터 브라우저의 모바일 보기로 확인하세요.

## 실제 날씨 데이터 연동하기

두 provider 모두 **선택 사항**이며, `.env.example` 을 `.env` 로 복사한 뒤 키를
입력하면 됩니다. 키는 서버(`.env`)에만 저장되고 프론트엔드로는 절대 전달되지
않습니다.

```bash
cp .env.example .env
# .env 파일을 열어 아래 키 중 하나 이상을 입력
```

### 기상청(KMA) 공공데이터포털 — 한국 날씨에 가장 정확 (추천)

1. https://www.data.go.kr 회원가입 및 로그인
2. "기상청_단기예보 조회서비스" 검색 → 활용신청 (승인은 보통 즉시~1일 이내)
3. 미세먼지까지 보려면 "한국환경공단_에어코리아_대기오염정보"도 함께 활용신청
4. 마이페이지 > 개발계정에서 발급된 **일반 인증키(Decoding)** 를 `.env`의
   `KMA_SERVICE_KEY` 에 입력

### AccuWeather

1. https://developer.accuweather.com 가입
2. My Apps → Add a new App (Limited Trial로 충분) → API Key 발급
3. 발급된 키를 `.env`의 `ACCUWEATHER_API_KEY` 에 입력
4. 무료 티어는 **하루 50 콜**로 제한되어 있어 서버가 지역별로 5분간 응답을
   캐시합니다 (`backend/app.py`의 `_CACHE_TTL_SECONDS`)

두 키가 모두 설정되면 기본적으로 AccuWeather를 우선 사용합니다. 우선순위를
바꾸려면 `.env`의 `DEFAULT_WEATHER_PROVIDER` 를 `kma` 또는 `accuweather` 로
지정하세요.

> **참고**: 이 저장소를 만든 환경에는 실제 API 키가 없어 KMA/AccuWeather
> 연동 코드는 공식 문서 기준으로 작성 후 유닛 테스트(고정 fixture)로 파싱 로직만
> 검증했습니다. 실제 키로 첫 실행 시 `/api/weather` 응답이 비정상적이면(예:
> `"provider": "mock (kma fallback)"` 로 표시되면 실패 후 자동 폴백된 것이므로)
> `backend/providers/kma.py` / `accuweather.py` 의 요청 파라미터를 최신
> data.go.kr / AccuWeather 문서와 대조해 조정해주세요. 모든 provider는 에러 시
> 앱이 죽지 않고 자동으로 샘플 데이터로 대체되도록 설계되어 있습니다.

## iPhone 홈 화면에 앱으로 설치하기

1. 배포된 주소(또는 같은 네트워크의 로컬 서버 주소)를 **Safari**로 엽니다
   (Chrome 등 다른 브라우저는 홈 화면 추가 시 PWA 기능이 제한됩니다)
2. 하단 공유 버튼(⬆️)을 탭합니다
3. "홈 화면에 추가"를 선택합니다
4. 홈 화면 아이콘을 탭하면 주소창 없이 전체화면 앱처럼 실행됩니다

로컬에서만 실행 중이라면(`localhost`) 같은 Wi-Fi의 아이폰에서 접속하려면
HTTPS 또는 실제 배포가 필요합니다 (iOS는 `localhost`가 아닌 주소에서 서비스
워커/알림 권한에 HTTPS를 요구합니다). Render, Fly.io, Railway 등에 무료로
배포하거나 `ngrok http 8080` 같은 터널로 임시 HTTPS 주소를 만들어 테스트할 수
있습니다.

## 알림에 대한 제약사항

- 이 앱의 알림은 **앱이 열려 있는 동안** 5분 간격으로 서버를 확인해 기상특보가
  있으면 브라우저 알림을 띄우는 방식입니다.
- iOS 16.4+ 는 홈 화면에 설치된 PWA에 대해 실제 백그라운드 웹 푸시(Web Push)도
  지원하지만, 이를 위해서는 VAPID 키 발급과 항상 켜져 있는 푸시 서버 인프라가
  필요해 이번 범위에는 포함하지 않았습니다. 필요하면 `backend/`에 push 구독
  저장 + 발송 로직을 추가하는 식으로 확장할 수 있습니다.

## 프로젝트 구조

```
weather_app/
  backend/
    app.py                 # Flask: 정적 파일 서빙 + /api/* 엔드포인트
    locations.py            # 24개 도시의 좌표 (KMA 격자, 위경도)
    providers/
      base.py               # provider 공통 인터페이스
      mock.py                # 키 없이도 바로 쓸 수 있는 샘플 데이터
      kma.py                 # 기상청 공공데이터포털 연동
      accuweather.py         # AccuWeather 연동
  static/
    index.html, css/, js/   # PWA 프론트엔드
    manifest.webmanifest, sw.js, icons/
  tests/                    # pytest (provider 파싱 + API 엔드포인트)
  requirements.txt
  .env.example
```

## API

- `GET /api/health` — 상태 + 사용 가능한 provider 목록
- `GET /api/locations?q=검색어` — 도시 검색 (빈 값이면 전체 목록)
- `GET /api/weather?location_id=seoul&provider=kma` — 종합 날씨 데이터
  (`provider` 생략 시 자동 선택)

## 테스트

```bash
cd weather_app
python -m pytest tests/ -v
```

13개 테스트가 mock provider의 데이터 형태, KMA/AccuWeather 응답 파싱(고정
fixture 기준), Flask API 엔드포인트를 검증합니다. 실제 UI 동작은 Playwright로
iPhone 뷰포트에서 홈 화면 로딩·지역 검색·전환·설정 화면까지 수동 검증했습니다.
