# 기여 가이드 / 코딩 컨벤션 (모듈화 리팩터 규율)

이 프로젝트는 정적 fetch · Playwright 렌더 · pywin32 Save As · 마커 탐지 · LLM 자가치유가
얽힌 **운영형 엔진**이다. 안정성을 위해 **한 번에 다 바꾸지 않고, 단계적으로 격리**한다.
아래 규율은 오픈소스 기여자와 LLM 도구가 흐름을 정확히 추적하도록 돕는 안전장치다.

---

## 0. 황금 규칙: 테스트가 그린일 때만 옮긴다

```
python _internal/tests/run_tests.py   # 리팩터 각 단계 '전/후'에 반드시 그린(루트에서 실행)
```

- 자동 테스트가 최우선 안전망이다(과거 `_extract_single` 미정의가 잠복했던 교훈).
- 리팩터로 깨질 수 있는 **경계(seam)**를 먼저 테스트로 고정한 뒤 코드를 옮긴다.
- LLM 같은 외부·비결정적 의존은 **심을 모킹**해 테스트한다(라이브 서버 의존 = flaky).

---

## 1. 타겟 아키텍처 & 의존성 방향 (한 방향, 아래로만)

```
cli.py / replay.py          (컨트롤러 — 오케스트레이션/엔트리포인트만)
        │  import
        ▼
engine.py / core/ / crawlers/   (DOM 추출·치유·수집 전략)
        │  import
        ▼
services/llm_service.py         (LLM 서비스 — leaf)   utils/ (logger 등 — leaf)
        │
        ▼
requests / lxml / playwright / pywin32  (외부 라이브러리)
```

**순환 의존 차단 2대 규칙**
1. `services/*`·`utils/*`(leaf)는 **내부 모듈을 import하지 않는다**(cli/engine/crawlers 금지).
2. `services/llm_service`는 **평범한 타입(문자열/리스트/딕트)으로만 대화**한다. lxml 노드·
   engine 클래스를 경계 너머로 넘기지 않는다 → DOM 이 필요한 로직은 engine 에 남긴다.

**분리 대상 모듈(계획)**: `crawlers/{base,static,dynamic,chrome}.py`,
`services/llm_service.py`, `core/`(스키마·감사로그), `utils/`(로거).

---

## 2. 규칙 A — 모듈별 자기 식별 헤더 (신규 파일 필수)

분리되는 모든 신규 파일 최상단에 아래 양식을 넣는다. **검증된 대표 사이트/케이스**를 명시해
향후 수정 시 회귀 기준으로 삼는다.

```python
"""
MODULE_NAME: [경로/파일명]
PURPOSE: [핵심 목적·역할]
DEPENDENCY: [필수 라이브러리: Playwright / pywin32 / lxml 등]

[검증된 주요 사이트 및 케이스]
- [사이트]: [성공 건수 및 핵심 방식]   예) 이커머스(Akamai): 60건, chrome Save As·1p

[테스트/운영 교훈]
- [교훈]: [실전에서 파악된 버그/조치]
"""
```

## 3. 규칙 B — 함수/클래스 독스트링에 [역할]과 협력자

```python
def example():
    """
    [사용처/협력자]
    - 누가 부르고(caller), 무엇을 부르는지(collaborator)를 '개략적으로'.
    [역할]
    이 함수가 담당하는 명확한 기능.
    """
```

- **주의(중요):** `[사용처]`에 **호출처를 손으로 낱낱이 나열하지 말 것.** 코드가 바뀌면
  금방 낡아(stale) 오히려 기여자·LLM 을 오도한다. *정확한 호출 그래프는 grep/코드에 맡기고*,
  독스트링에는 **역할과 주요 협력자(대략)**만 적는다. (예: "cli 의 by-example 흐름에서 호출,
  실패 시 LLM 폴백" 수준.)

---

## 4. 단계적 리팩터 로드맵

- [x] **Phase 0** — 스모크 테스트 골격(`tests/`): 임포트 + LLM 심 모킹(폴백 포함) + 결정적 추출.
- [x] **Phase 1a** — `llm.py` → `services/llm_service.py` **순수 이동**(동작 0 변경). engine 4곳
      `from services import llm_service as llm` 로 갱신, `llm.py` 는 재-export 심으로 잔류. 14/14 그린.
- [x] **Phase 1b** — **engine 을 LLM-FREE 로**. LLM 오케스트레이션 4함수를 `llm_locators.py`(engine+
      service 를 잇는 층)로 이관. engine 의 `llm_relocate` 3호출은 **주입 훅**(`set_relocator`/`_relocate`)
      으로 치환 → engine 은 llm 을 import 안 함. 상단 불변식 선언 + `test_engine_llm_free.py` 가 강제. 19/19 그린.
- [x] **Phase 2** — `crawlers/{base,static,dynamic,chrome}` 전략 분리(전략 패턴). engine 은 수집 코드를
      전혀 직접 갖지 않음(전부 위임). `test_crawlers_*`(표면·배선·**leaf 규율 강제**). 32/32 그린.
  - [x] **2a static** — `crawlers/base.py`(공용 `_UA`/`default_headers`) + `crawlers/static.py`(`static_fetch`).
        engine 의 `_static_fetch`/`_UA` 제거 → 위임. `test_crawlers_static.py`(leaf 규율 강제). 23/23 그린 + 뉴스 애그리게이터 실스모크.
  - [x] **2b dynamic** — `_playwright_fetch` → `crawlers/dynamic.py`(`playwright_fetch`). engine·cli 가 위임,
        engine 은 `_UA` 도 더는 직접 안 씀. `test_crawlers_dynamic.py`. 27/27 그린 + example.com 실렌더 스모크.
  - [x] **2c chrome** — `block_reason`(+시그니처)→`crawlers/base.py`(순수 DOM 검사), chrome fetch 일체
        (`chrome_profile_fetch`/`chrome_save_as_fetch`+사설 헬퍼)→`crawlers/chrome.py`. engine 에서 426줄 제거.
        `test_crawlers_chrome.py`(block_reason 판정 결정적 테스트 포함). 32/32 그린.
        (실제 Save As/디버그 attach 는 키입력·창포커스 의존이라 자동 스모크 불가 → 실사이트 수동 확인 영역.)
- [x] **Phase 3** — `core/schema.py` 로 데이터 계약(`Schema`/`FieldSchema`) 이관(engine.py 163줄 제거,
      동작 0 변경). engine·cli 가 `core.schema` 위임. `test_core_schema.py`(레시피 왕복 결정적 +
      **core leaf 규율 강제**). 37/37 그린 + 뉴스 애그리게이터 실빌드/추출/레시피 왕복 스모크(30행 동일).
  - 범위 판단: '로거'는 실체가 `print`/`self.log` 콜백뿐이라 옮길 코드가 없음(추상화 신설은 불필요한
    복잡도) → 보류. '감사로그(_runs.csv)'는 cli 오케스트레이션 결합이 커 가치 대비 리스크가 높아 보류.
    실제로 가치 있는 '데이터 계약 격리'만 수행.
- [x] **행동(골든) 테스트 보강** — 구조/스모크로 못 잡던 '핵심 알고리즘'을 결정적으로 고정.
      · `test_heal_golden.py` — 클래스 난독화로 CSS 깨져도 구조 경로로 값 보존 + 셀렉터 자가 갱신.
      · `test_chain_golden.py` — URL 정련 by-example, 단일추출 **고정 스키마 + 이미지 미디어 폴백**(#20 가드).
      · `test_runlog.py` — P-k 계층번호(부모-자식) 규칙.
      · `test_pagination_golden.py` — dedup 키(가짜 링크 배제)·dedup 필드 선택·결과 유효성 가드·
        페이지네이션 파라미터 학습(page/offset)·학습패턴 다음URL(무-LLM).
      · `test_locate_golden.py` — mixed-rows 감지(#9 동영상 플랫폼: 서로 다른 레코드 값 섞임을 '예시값 불일치'로).
      · `test_load_routing_golden.py` — smart_load 차단 감지→크롬 Save As 라우팅(모킹), 정상은 auto 유지.
      **69개 테스트 그린**. 모듈화 리팩터의 회귀 안전망을 구조→행동 수준으로 폭넓게 끌어올림.

- [~] **Phase 4** — cli.py 모놀리스(~1494줄) 분리. *슬라이스로 진행 → 현재 856줄.*
  - [x] **4a chain** — 체인 크롤링(목록CSV→상세) 일체를 `chain.py`(동료 컨트롤러)로 이관. cli 1494→1024줄.
        **순환 회피**: `chain` 이 `cli` 를 import, `cli.main` 은 `run_chain_crawl` 을 지연 import.
        cli 의 안정 헬퍼/상수는 `from cli import`(1회 바인딩), **가변 전역**(`LAST_LOAD_METHOD`/`RENDER_REQUIRED`)만
        `cli.<name>` 실시간 참조. `_looks_like_csv`(dispatch)/번호매기기는 cli 유지. 48/48 그린(순환 실증 포함).
  - [x] **4b paths** — 사이트키→파일경로 헬퍼+경로상수(그룹 A) → `paths.py`(**leaf**). cli 953줄로 축소.
        cli 는 재-export(`from paths import ...`) → 기존 `from cli import` 무변경. chain 은 경로 심볼을
        paths 에서 직접(결합 축소). cli 의 hashlib/urlparse import 제거. `test_paths.py`(결정성+leaf 규율). 53/53 그린.
  - [x] **4c runlog** — 감사로그(_runs.csv)·계층번호(그룹 B) → `runlog.py`(**leaf**, paths 만 의존).
        cli 856줄로 축소. cli 재-export + chain/replay 재사용(단일 규칙). `test_runlog.py`(P-k 계층번호
        골든 + leaf 규율). 58/58 그린 + `replay --list` 실스모크(채용정보 사이트 체인 '6-1' 정확 표시).
  - (보류) D/E/F(대화형 선택·로드전략·목록크롤)는 컨트롤러 본질이라 cli 유지. E 전역플래그는 별도 정리 대상.

각 단계 완료의 정의(DoD): **`python _internal/tests/run_tests.py` 그린 + 실사이트 1건 스모크**.
(4a 는 verbatim 이동 + 순환/전역 배선 확인 + 체인 골든테스트가 회귀 안전망 → 실사이트는 대화형이라 사용자 수동 영역.)
