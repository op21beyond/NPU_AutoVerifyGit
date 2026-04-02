# Stage 1 - Ingestion and Segmentation

## Plan
- 목표: PDF 페이지/블록 단위로 텍스트, 표, 이미지 영역을 분리해 후속 단계 입력 생성
- 입력: Architecture PDF
- 출력: `page_blocks` (필수: page, block_type, block_id, bbox, raw_text, extraction_method, confidence, trace_id 등; 선택: `relationships`)
- 완료 기준:
  - 페이지 단위 파싱 성공률 보고
  - OCR 라우팅 대상 페이지 목록 생성

## Status
- 상태: Implemented (core path)
- 구현률: ~85%
- 구현 내용:
  - `PyMuPDF`: 텍스트/이미지 블록(`get_text("dict")`), `find_tables()` 기반 표 블록(지원되는 PDF에서)
  - `artifacts/stage1_ingestion/page_blocks.jsonl`, `parsing_report.json`, `ocr_routing.json` 출력
  - 선택: `--ocr-full-page` 시 Tesseract 전면 OCR(라우팅된 페이지만, Tesseract PATH 필요)
  - 선택: `--text-backend`로 `pymupdf4llm` 보조 코퍼스(`pymupdf4llm_corpus.json`) 생성 가능 (`pymupdf4llm`/`hybrid`)
  - 선택: 헤더/푸터 제거 `--header-footer-mode`
    - `position`: 페이지 상/하단 비율(`--header-top-ratio`, `--footer-bottom-ratio`) 기준
    - `repeat`: 페이지 간 반복되는 짧은 문자열(`--repeat-min-pages`, `--repeat-max-chars`) 기준
- 선택: 이미지 기반 OCR `--image-ocr-engine` + `--image-ocr-route`
  - `none`(기본), `tesseract`, `paddleocr` (선택 엔진 미설치 시 OCR 스킵)
  - `--image-ocr-route needs_ocr`(기본) 또는 `always` (페이지 OCR 라우팅 여부에 따라 image block bbox OCR 수행)
  - `--image-ocr-dpi`, `--image-ocr-min-chars`로 품질/비용 조절
  - PaddleOCR 장치 선택: `--paddle-device auto|cpu|gpu` (`auto`는 CUDA 가능 시 GPU 사용)
  - PaddleOCR GPU 인덱스(3.x): `--paddle-gpu-id N` — 3.x에서는 `device=gpu:N` 형태로 전달(2.x는 `use_gpu`만 사용)
  - PaddleOCR 모델 경로: `--paddle-model-dir <DIR>` (`det/rec/cls` 하위 폴더 자동 인식)
  - 설치된 `paddleocr` 메이저 버전에 따라 초기화 분기: **2.x**는 `use_gpu`, **3.x**는 `device`(코드 자동). `parsing_report.json`에 `paddleocr_major_version`, `paddle_device_resolved` 등 기록
  - 내부 예외(선택 의존성·OCR 실패)는 **stderr**에 `[함수명] Exception: ...` 형태로 로그(동일 ImportError는 한 번만)
- 선택: 테이블 텍스트 엔진 `--table-text-engine`
  - `pymupdf`(기본): `find_tables().extract()` 기반
  - `pdflumber`: table bbox 기준 `pdfplumber.extract_tables()` 우선 사용 (미설치 시 자동 스킵/폴백)
  - `tesseract` / `paddleocr`: table bbox crop OCR
  - `--table-ocr-route empty_only`(기본) 또는 `always`
  - `--table-ocr-dpi`, `--table-ocr-min-chars`로 품질/비용 조절
- 테이블 bbox 후처리(기본 ON): `find_tables()`가 **겹치거나** 세로로 인접한 조각을 **하나의 bbox**로 병합한 뒤, 그 bbox로 `pdflumber`/OCR/`get_text(clip)` 등을 수행한다. 겹침·nested로 동일 영역에 원시 table이 여러 개여도 병합 후 **논리 표 하나**로 맞춘다.
  - `--table-merge-bypass`: 병합을 끄고 예전처럼 원시 table 개수만큼 행을 출력(전후 비교용).
  - `--table-merge-gap`: 기본 `5`(pt) — 수직/수평 인접 병합 시 허용 간격.
  - `--table-merge-horizontal`: **좌우로만 인접**한 두 bbox를 합치는 규칙(기본 OFF). 기본 경로에서는 겹침·세로 인접 병합만 사용한다.
  - `--table-expand-x-to-page`: 병합 **이후** 각 표 bbox의 **y는 유지**하고 **x만** 페이지 좌우(또는 `margin`만큼 안쪽)로 넓힌다. 가로로 나란히 독립 표가 없는 문서(예: Architecture PDF)에서만 권장.
  - `--table-page-margin-left`, `--table-page-margin-right`: `--table-expand-x-to-page`와 함께 사용(기본 `0`).
  - `parsing_report.json`에 `table_merge_enabled`, `table_expand_x_enabled`, `table_detector_raw_count`(원시 `find_tables` 개수 합), `table_output_count`(병합 후 표 블록 행 수 합), `table_merge_gap`, `table_merge_horizontal` 기록.
- 텍스트 본문 상·아래첨자(기본 ON): `get_text("dict")` 스팬의 `flags`(예: `TEXT_FONT_SUPERSCRIPT`)와 크기·세로 위치 휴리스틱으로 `<sup>`, `<sub>` 태그를 붙인 뒤 `raw_text`에 반영한다. NPU 명령명 등과의 `_` 혼동을 줄이려면 태그로 구분하는 편이 유리하다.
  - `--text-span-script-bypass`: 태그 후처리를 끄고 기존처럼 스팬을 평탄하게 이어붙인 텍스트만 사용(전후 비교용).
  - `parsing_report.json`에 `text_span_script_enabled` 기록.
- 오픈 이슈:
  - 이미지 표 구조 복원(`img2table`)은 미연동 (현재 table OCR은 텍스트 라인 추출 중심)
  - 표·본문 중복 억제는 bbox 휴리스틱 수준
- 다음 액션:
  - 실제 Architecture PDF로 라우팅 임계값(`--min-chars-ocr`) 튜닝
  - 헤더/푸터 필터 파라미터(`position`/`repeat`) 문서별 튜닝
  - Stage 3과 표 블록 품질 공동 검증

## Technical Note
- 텍스트 레이어 우선, 부족 시 OCR 보강 전략
- 블록 분리 품질이 전체 정확도에 미치는 영향이 크므로 bbox 보존 필수
- `block_id`로 블록 간 참조; `relationships`로 표-설명-수식 등 연결(각 항목 `type`, `target` = 대상 `block_id`)
- 구현 모듈: `src/stage1_ingestion/table_merge.py`(표 bbox 병합·가로 확장), `src/stage1_ingestion/text_span_scripts.py`(본문 첨자 태깅), `ingestion.py`에서 조합.
- PaddleOCR은 버전별로 CPU/GPU를 선택하고, 결과는 `parsing_report.json`의 `paddle_use_gpu`, `paddle_device_resolved`, `paddleocr_major_version`에 기록
