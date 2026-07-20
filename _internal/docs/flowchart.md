# Sovereign-Scraper — 프로그램 플로우차트

> 데이터 주권을 위한 자가 치유형 웹 스크래퍼. 아래 다이어그램은 실제 코드 흐름을 요약한다.
> (진입점 `start.py`/`cli.py`/`replay.py`, 내부 모듈은 `_internal/`.)

## 1. 최상위 흐름 — 실행 → 첫 실행(venv) → 메뉴

```mermaid
flowchart TD
    Start(["start.bat · python start.py"]) --> Lang{".env 에 LANG 있음?"}
    Lang -- "아니오 (첫 실행)" --> AskLang["언어 선택<br/>1) 한국어 · 2) English"] --> Boot
    Lang -- "예" --> Boot{".venv 첫 실행?"}
    Boot -- "예 (권장·기본)" --> Venv[".venv 생성 + 의존성 자동설치<br/>(pip + playwright chromium)<br/>→ venv 로 재실행"]
    Boot -- "아니오 / 이미 venv" --> Menu["메 뉴"]
    Venv --> Menu
    Menu --> M1["1. 크롤링<br/>(URL/HTML 한 페이지·목록)"]
    Menu --> M2["2. 체인 크롤링<br/>(목록 CSV → 상세페이지)"]
    Menu --> M3["3. 과거 작업 다시하기<br/>(replay)"]
    Menu --> M4["4. 예약 실행<br/>(Windows 작업 스케줄러<br/>등록·조회·삭제)"]
    Menu --> M5["5. 레시피<br/>(읽어들이기·공유·검색)"]
    Menu --> M6["6. 설정<br/>(LLM·기본값·개발자도구)"]
    M1 --> Crawl["크롤 파이프라인<br/>(그림 2)"]
    M2 --> Chain["체인 파이프라인<br/>(목록 링크 → 상세 단일 레코드)"]
    M3 --> Replay["_runs.csv 성공건 → 입력 없이 재현"]
    M4 --> Sched["scheduler.py(섬)이 schtasks 등록<br/>실행 명령=replay.py <선택> · SHC_ 접두사로만 조회/삭제"]
    Replay -. "정기 자동화하려면" .-> M4
    M5 --> Reg["레시피 공유<br/>(그림 3)"]
    M6 --> Set["LLM 공급자 · 저장/로드 기본값<br/>· doctor · 역량 매트릭스"]
```

## 2. 핵심 크롤 파이프라인 — by-example → 자가 치유 → 저장

```mermaid
flowchart TD
    A["대상 입력<br/>(URL 또는 로컬 HTML)"] --> B{"DOM 로드 방식"}
    B -- "auto (정적, 대부분)" --> L["파싱된 DOM"]
    B -- "render (JS-SPA)" --> L
    B -- "chrome Save As<br/>(안티봇·로그인)" --> L
    B -. "차단 감지 시 auto→chrome 자동전환" .-> L
    L --> C["보이는 값 한 줄 입력<br/>예: 제목@#12,000@#강남구"]
    C --> D["파서 역설계 (사이트 하드코딩 없음)"]
    D --> D1["① 결정적 매칭<br/>(앵커=첫 값, 반복 조상 = 레코드)"]
    D1 -- 실패 --> D2["② 마커(data-testid)/렌더 재시도"]
    D2 -- 실패 --> D3["③ LLM 역할 매핑"]
    D1 --> E
    D2 --> E
    D3 --> E["추출 + 페이지네이션 + 중복제거<br/>+ 이미지 구조매칭·아카이브"]
    E --> F{"성공 가드<br/>'원한 필드를 실제로 가져왔나?'"}
    F -- "유효" --> G["저장<br/>CSV(4종 저장방식) + 레시피 + _runs.csv + 이미지"]
    F -- "무효<br/>(커버리지/차단/형태)" --> H{"AUTO_HEAL ON?"}
    H -- "예" --> I["save_as HTML(라이브 추가접속 0)<br/>오프라인 LLM 통째 분석 → 스키마 재발견"]
    I --> F
    H -- "아니오" --> J["중단 안내<br/>(좋은 레시피 보호)"]
    G --> K["replay / 스케줄러로 정기 재현<br/>(레시피 자동 로드)"]
```

## 3. 레시피 공유 — 읽어들이기(inbox) / 공유하기(outbox → 게시판) / 게시판 검색

```mermaid
flowchart LR
    subgraph IN ["읽어들이기 (받은 것 → 내 것)"]
      direction TB
      R1["inbox/*.csv 목록<br/>(파일명=사이트_필드…)"] --> R2["매니페스트 표시<br/>사이트·필드"]
      R2 --> R3["내 URL 입력"]
      R3 --> R4{"그대로?"}
      R4 -- "Enter" --> R5["retarget→설치→실행<br/>= _runs 기록+내 레시피(고아 해소)"]
      R4 -- "입력" --> R6["처음부터 새로 학습"]
    end
    subgraph OUT ["공유하기 (내 것 → 남에게)"]
      direction TB
      P1["마스킹 export<br/>(검색어·example 제거)"] --> P2["자기설명 이름<br/>Enter=사이트_필드…/직접입력"]
      P2 --> P3["→ recipes/shared/outbox/"]
      P3 --> P4["Discussions '새 글쓰기' 브라우저 열기<br/>제목·본문(매니페스트+CSV) 프리필<br/>사람이 검수 후 직접 제출(승인 없이 즉시 게시)"]
    end
    subgraph FIND ["온라인에서 찾기 (기본 활성 · 이 repo 자체 Discussions, .env 로 재정의 가능)"]
      direction TB
      S1["Discussions 'Recipes' 카테고리<br/>브라우저로 열기(검색어 포함)"] --> S2["사람이 글을 훑어보고<br/>CSV 코드블록 복사"]
      S2 --> S3["inbox/ 에 .csv 로 저장"]
    end
    FIND -.->|inbox 채움| IN
```

> Discussions 는 public repo 라도 API 검색에 GitHub 토큰이 필요해(무인증 원칙과 충돌) 검색은
> 브라우저를 여는 것까지만 자동화하고, 나머지(글 훑어보기·CSV 복사)는 사람이 한다.

## 4. 배포 구조 — front / _internal

```mermaid
flowchart TD
    Root["프로젝트 루트 (사용자가 여는 폴더)"]
    Root --> F1["start.bat · start.py · cli.py · replay.py"]
    Root --> F2["output/ · recipes/"]
    Root --> F3["requirements.txt · README · .env"]
    Root --> INT["_internal/ (내부 · 사용자 미접촉)"]
    INT --> I1["engine · locators · structure · values · paths ..."]
    INT --> I2["crawlers/ · core/ · services/"]
    INT --> I3["tests/ · docs/ · fixtures/"]
    F1 -. "sys.path += _internal (shim)" .-> INT
```

## 5. 모듈 의존 구조(계층) — v6.8 전수 감사 반영

> 화살표 = import 방향(위→아래로만, 순환 없음 — 경계는 주석이 아니라 테스트가 강제).
> **노란 테두리** = v6.8 에서 신설/역할이 확대된 모듈. 세부 규율은 SRS §5-b.

```mermaid
flowchart TD
    classDef changed fill:#fff8e1,stroke:#f9a825,stroke-width:2px

    subgraph FRONT ["진입점 (front)"]
        START["start.py<br/>메뉴 런처"]
        REPLAY["replay.py<br/>재현 배치"]
        CLI["cli.py — 단발 크롤 컨트롤러<br/>main = 흐름 조율만<br/>(가드 _validate_run · 저장 _persist_success 분리)"]
        CHAIN["chain.py<br/>체인 컨트롤러 (cli 의 동료)"]
    end
    START -. "subprocess" .-> CLI
    START -. "subprocess" .-> REPLAY
    REPLAY -. "subprocess<br/>(레시피 주입)" .-> CLI
    CLI -- "target=.csv<br/>(지연 import)" --> CHAIN

    subgraph SHARED ["공유 실행 계층 (cli·chain 이 둘 다 사용)"]
        LOADER["loader<br/>DOM 획득 · 차단 시 save_as 전환"]
        AUTOHEAL["autoheal<br/>자동 재학습(최후 사다리)"]
        GUARDS["guards<br/>성공 가드 판정"]
        LLMLOC["llm_locators<br/>DOM+LLM 접착층"]
    end
    CLI --> LOADER
    CLI --> AUTOHEAL
    CLI --> GUARDS
    CLI --> LLMLOC
    CHAIN --> LOADER

    subgraph SIBLING ["엔진 형제 계층 (서로 모름 — 탈결합)"]
        ENGINE["engine<br/>추출·자가치유 (LLM-FREE, 훅만 호출)"]
        LOCATORS["locators<br/>by-example 위치탐색"]
    end
    AUTOHEAL --> ENGINE
    LLMLOC --> ENGINE
    CLI --> LOCATORS

    subgraph STRATEGY ["수집 전략 · 서비스 · 데이터 계약"]
        CRAWLERS["crawlers/*<br/>static · dynamic · picker<br/>chrome = Save As 단일<br/>(CDP profile 경로 v6.8 제거)"]
        SVC["services/llm_service<br/>LLM 전송(OpenAI 호환)"]
        SCHEMA["core/schema<br/>레시피 직렬화"]
    end
    LOADER --> CRAWLERS
    ENGINE --> CRAWLERS
    ENGINE --> SCHEMA
    LLMLOC --> SVC
    class CRAWLERS changed

    subgraph LEAF ["leaf 계층 (상위를 모름)"]
        STRUCT["structure · values · hooks<br/>segment · field_heuristics"]
        PATHS["paths<br/>경로 규칙"]
        OUTPUT["output<br/>save_csv + resolve_save_mode<br/>(저장방식 결정 단일 출처)"]
        RUNLOG["runlog<br/>record_run · resolve_batch<br/>(기록+회차 단일 출처)"]
        MISC["dedup · safe_io<br/>heal_knowledge"]
        CFG["crawl_config<br/>기본 저장/로드 방식"]
        I18N["i18n<br/>다국어 t()"]
    end
    ENGINE --> STRUCT
    LOCATORS --> STRUCT
    CLI --> OUTPUT
    CLI --> RUNLOG
    CHAIN --> OUTPUT
    CHAIN --> RUNLOG
    CLI --> PATHS
    class OUTPUT,RUNLOG changed

    ENVF["envfile — 루트 .env 단일 파서 (v6.8 신설)<br/>start/llm_service/crawl_config/i18n 의 4벌 복제 통합 · 최하위 leaf"]
    START --> ENVF
    SVC --> ENVF
    I18N --> ENVF
    CFG --> ENVF
    class ENVF changed
    class CLI changed
```

> v6.8 변경 요지: ① `crawlers/chrome.py` 의 CDP profile 경로(-181줄)를 제거해 '진짜 크롬' 진입점을
> Save As 하나로 확정(부활 방지 테스트 포함). ② `.env` 파서 4벌을 `envfile`(최하위 leaf)로 통합 —
> leaf 규율이 복제를 유발하면 규율을 깨는 대신 '더 낮은 공용 leaf'를 만든다. ③ 저장방식/회차/기록
> 규칙을 `output`·`runlog` 단일 출처로 옮겨 cli·chain 중복 제거, cli.main 은 가드·저장을 함수로
> 분리해 흐름 조율만 남김.
