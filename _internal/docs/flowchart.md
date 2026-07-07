# Sovereign-Scraper — 프로그램 플로우차트

> 데이터 주권을 위한 자가 치유형 웹 스크래퍼. 아래 다이어그램은 실제 코드 흐름을 요약한다.
> (진입점 `start.py`/`cli.py`/`replay.py`, 내부 모듈은 `_internal/`.)

## 1. 최상위 흐름 — 실행 → 첫 실행(venv) → 메뉴

```mermaid
flowchart TD
    Start(["start.bat · python start.py"]) --> Boot{".venv 첫 실행?"}
    Boot -- "예 (권장·기본)" --> Venv[".venv 생성 + 의존성 자동설치<br/>(pip + playwright chromium)<br/>→ venv 로 재실행"]
    Boot -- "아니오 / 이미 venv" --> Menu["메 뉴"]
    Venv --> Menu
    Menu --> M1["1. 크롤링<br/>(URL/HTML 한 페이지·목록)"]
    Menu --> M2["2. 체인 크롤링<br/>(목록 CSV → 상세페이지)"]
    Menu --> M3["3. 과거 작업 다시하기<br/>(replay)"]
    Menu --> M4["4. 레시피<br/>(읽어들이기·공유·검색)"]
    Menu --> M5["5. 설정<br/>(LLM·기본값·개발자도구)"]
    M1 --> Crawl["크롤 파이프라인<br/>(그림 2)"]
    M2 --> Chain["체인 파이프라인<br/>(목록 링크 → 상세 단일 레코드)"]
    M3 --> Replay["_runs.csv 성공건 → 입력 없이 재현<br/>→ 윈도우 스케줄러로 정기 수집"]
    M4 --> Reg["레시피 레지스트리<br/>(그림 3)"]
    M5 --> Set["LLM 공급자 · 저장/로드 기본값<br/>· doctor · 역량 매트릭스"]
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

## 3. 레시피 공유 — 읽어들이기(inbox) / 공유하기(outbox) / 온라인 검색

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
      P3 --> P4["업로드 페이지 브라우저 열기<br/>사람이 검수 후 PR"]
    end
    subgraph FIND ["온라인에서 찾기 (선택 · .env 설정 시)"]
      direction TB
      S1["공개 repo index.json<br/>HTTPS fetch"] --> S2["키워드 검색"]
      S2 --> S3["다운로드 → inbox/"]
    end
    FIND -.->|inbox 채움| IN
```

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
