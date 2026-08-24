# 사용 가이드

이 문서는 이 프로젝트를 처음 보는 사람도 그대로 따라 하면 실행할 수 있도록 쓴 가이드입니다.
설계 배경이나 아키텍처가 궁금하면 [README.md](README.md)를 참고하세요. 이 문서는 "일단 실행해보기"에 집중합니다.

> **이게 뭔가요?**
> 종목의 가격 데이터를 여러 AI 애널리스트가 나눠서 분석하고, 토론을 거쳐 "이렇게 사고팔면 어떨까요?"라는
> **초안 매매 계획**을 만들어 보여주는 프로그램입니다. **실제 주문은 절대 자동으로 나가지 않습니다.**
> 사람이 화면에 뜬 내용을 보고 직접 승인해야만 (그것도 진짜 계좌가 아니라 로컬 모의투자 장부에만) 기록됩니다.
> 투자 자문이 아니라 연구/학습용 도구입니다.

---

## 0. 준비물

- Python 3.10 이상
- 터미널(명령 프롬프트) 사용 가능 환경

버전 확인:

```bash
python3 --version
```

---

## 1. 설치

```bash
# 1) 이 저장소를 내려받고 폴더로 이동
git clone <이 저장소 주소>
cd fantastic-fortnight

# 2) (권장) 가상환경 생성 — 다른 파이썬 프로젝트와 충돌 방지
python3 -m venv .venv
source .venv/bin/activate        # Windows는: .venv\Scripts\activate

# 3) 필요한 패키지 설치
pip install -r requirements.txt
```

여기까지 오류 없이 끝났다면 설치 완료입니다.

---

## 2. (선택) 환경설정 파일 만들기

```bash
cp .env.example .env
```

`.env` 파일을 열어보면 이런 항목이 있습니다:

```
ANTHROPIC_API_KEY=
```

- **비워두면**: 프로그램은 그대로 잘 동작합니다. 다만 각 애널리스트의 설명 문구가
  `[offline-stub] ...` 처럼 실제 AI가 쓴 문장이 아니라 임시 요약 문구로 나옵니다.
- **키를 입력하면**: 같은 분석 결과에 대해 실제 자연어로 된 설명이 붙습니다.

수치(신호, 신뢰도, 레버리지, 손절가 등)는 API 키 유무와 관계없이 **항상 코드로 직접 계산**되므로
키가 없어도 실습/테스트 목적으로는 아무 문제 없습니다.

---

## 3. 첫 실행

```bash
python -m trading_agent.cli signal SK_HYNIX
```

`SK_HYNIX` 자리에는 아무 이름이나 넣어도 됩니다 (지금은 실제 시세가 아니라 시뮬레이션 데이터를 쓰기 때문).

실행하면 대략 이런 화면이 나옵니다:

```
============================================================
DISCLAIMER: research/education tool output, not investment advice.
============================================================
[technical_analyst] bearish (conf 0.25) — ...
[fundamental_analyst] bullish (conf 1.00) — ...
[sentiment_analyst] neutral (conf 0.00) — ...
[forecast_analyst] neutral (conf 0.13) — ...

Aggressive view : ...
Conservative view: ...
Moderator        : ...

--- Proposed trade plan (draft, pre risk-clamp) ---
BUY SK_HYNIX @ 842.53 | target 890.77 | stop 818.01 | tranches [0.5, 0.5]

--- Risk-clamped verdict (hard limits enforced in code) ---
approved=True status=pending_approval
leverage=3.0x position_pct_of_equity=10.0%
corrections:
  - position size 100.0% of equity > max 10.0%, clamped
============================================================
```

### 이 화면 읽는 법

| 구간 | 의미 |
|---|---|
| `[technical_analyst]` 등 4줄 | 기술적 분석 / 펀더멘털 / 뉴스 심리 / 가격 예측, 4명의 애널리스트가 각자 낸 의견과 확신도 |
| `Aggressive / Conservative / Moderator` | 이 계획에 대해 "더 공격적으로 가자" vs "줄이자"는 리스크 토론 요약 |
| `Proposed trade plan (draft)` | 애널리스트 토론 결과로 나온 **1차 초안** — 아직 안전장치 적용 전 |
| `Risk-clamped verdict` | 초안이 `config.py`에 정해둔 상한선(레버리지 3배, 계좌의 10% 이내, 손절 필수 등)을 넘으면 **여기서 강제로 깎임**. `corrections:` 항목이 바로 그 조정 내역 |
| `status=pending_approval` | "이 계획, 사람이 승인해야 다음 단계로 갑니다"라는 뜻. 이 프로그램만으로는 아무것도 체결되지 않습니다 |

---

## 4. 자주 쓰는 옵션

```bash
python -m trading_agent.cli signal SK_HYNIX --leverage 5 --tranches 2
```

| 옵션 | 의미 | 예시 |
|---|---|---|
| `--leverage` | 원하는 레버리지 배수를 "요청"함 (그대로 반영되지 않고 상한선 안으로 자동 조정됨) | `--leverage 20` |
| `--tranches` | 매수/매도를 몇 번에 나눠 할지 | `--tranches 3` |
| `--approve` | 결과를 보여준 뒤 "이걸 모의 계좌에 기록할까요? (y/N)"라고 물어봄 | 아래 5번 참고 |
| `--kronos` | 가격 예측에 Kronos AI 모델을 사용 (별도 설치 필요, 없으면 자동으로 기본 방식으로 대체됨) | 아래 6번 참고 |

`--leverage 20`을 넣어도 실제로는 화면에 `leverage=3.0x`로 잘려서 나오는 걸 볼 수 있습니다.
이게 의도된 동작입니다 — 아무리 크게 요청해도 코드에 박아둔 안전 한도를 벗어날 수 없습니다.

---

## 5. 모의 체결까지 해보기 (`--approve`)

```bash
python -m trading_agent.cli signal SK_HYNIX --approve
```

분석 결과가 다 나온 뒤 마지막에 이렇게 물어봅니다:

```
Book this into the paper broker? [y/N]
```

- `y` 입력 → 이 프로세스 안에서만 존재하는 **가상의 모의투자 장부**에 기록됩니다. (프로그램을 껐다 켜면 초기화됩니다. 실제 증권사·거래소에는 아무 일도 일어나지 않습니다.)
- `y` 이외의 아무 키 → 아무 것도 기록하지 않고 종료합니다.

---

## 6. (선택, 심화) Kronos 가격 예측 모델 사용해보기

기본 상태에서는 4번째 애널리스트(`forecast_analyst`)가 간단한 추세 추정 방식으로 동작합니다.
이걸 오픈소스 금융 예측 모델인 [Kronos](https://github.com/shiyu-coder/Kronos)로 바꿀 수 있습니다.
다만 별도 설치가 필요하고(파이토치 포함, 용량 큼), **설치 안 해도 프로그램은 정상 동작**하니 처음엔 건너뛰어도 됩니다.

```bash
git clone https://github.com/shiyu-coder/Kronos.git
pip install -r Kronos/requirements.txt -r requirements-kronos.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/Kronos

python -m trading_agent.cli signal SK_HYNIX --kronos
```

설치가 안 되어 있는데 `--kronos`를 붙이면 에러로 멈추지 않고, 설치 방법을 안내하는 메시지를 띄운 뒤
자동으로 기본 방식으로 돌아갑니다.

---

## 7. 잘 설치됐는지 확인하기 (테스트)

```bash
pytest
```

인터넷 연결이나 API 키 없이도 전부 통과해야 정상입니다. (`34 passed` 같은 문구가 나오면 정상)

---

## 자주 묻는 질문

**Q. 실제 제 돈으로 거래되나요?**
아니요. 이 프로그램은 어떤 증권사·거래소 API에도 연결되어 있지 않습니다. `--approve`로 y를 눌러도
파이썬 프로세스 안의 메모리에만 가짜 계좌 기록이 남습니다.

**Q. 실시간 시세를 쓰나요?**
아니요. 기본값은 재현 가능한 가짜 가격 흐름(`SimulatedFeed`)입니다. 실제 시세를 쓰려면
`trading_agent/data/providers.py`의 `MarketDataProvider` 인터페이스를 구현해 직접 연결해야 합니다
(README.md의 "Extending this" 참고).

**Q. `--leverage 20`처럼 크게 넣었는데 왜 3배로 나오나요?**
의도된 동작입니다. `trading_agent/config.py`의 `RiskLimits`가 최종 상한선이고, 어떤 요청이 와도
`engine/risk_controls.py`가 그 안으로 깎습니다. 정말 한도를 올리고 싶으면 `config.py`를 직접,
의도적으로 수정해야 합니다.

**Q. 이거 진짜 투자 조언으로 써도 되나요?**
아니요. 화면 맨 위에 매번 뜨는 디스클레이머 그대로, 연구/학습 목적의 도구입니다.

---

더 자세한 설계 배경(왜 이런 구조인지, 각 파일이 뭘 하는지)은 [README.md](README.md)를 확인하세요.
