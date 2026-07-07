# -*- coding: utf-8 -*-
"""
MODULE_NAME: llm.py  (DEPRECATED 하위호환 심)
PURPOSE: LLM 전송 계층은 Phase 1a 에서 services/llm_service.py 로 이동했다. 이 파일은
         기존 `import llm` / `python llm.py` 를 깨지 않기 위한 얇은 재-export 심이다.
DEPENDENCY: services.llm_service.

[안내]
- 신규 코드는 `from services import llm_service` 를 쓸 것. 이 심은 외부 스크립트 호환용.
- 함수 모킹(테스트)은 반드시 '실제로 호출되는 모듈'(engine 이 쓰는 services.llm_service)을
  패치해야 한다. 이 심의 속성을 패치해도 engine 에는 반영되지 않는다(바인딩이 다름).
"""
from services.llm_service import (          # noqa: F401  (하위호환 재-export)
    LM_STUDIO_BASE_URL, LM_STUDIO_MODEL,
    chat, ask, ask_json, available, _strip, _THINK_RE,
)

if __name__ == "__main__":
    import runpy
    runpy.run_module("services.llm_service", run_name="__main__")
