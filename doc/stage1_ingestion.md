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
  - PaddleOCR 모델 경로: `--paddle-model-dir <DIR>` (`det/rec/cls` 하위 폴더 자동 인식)
- 선택: 테이블 텍스트 엔진 `--table-text-engine`
  - `pymupdf`(기본): `find_tables().extract()` 기반
  - `pdflumber`: table bbox 기준 `pdfplumber.extract_tables()` 우선 사용 (미설치 시 자동 스킵/폴백)
  - `tesseract` / `paddleocr`: table bbox crop OCR
  - `--table-ocr-route empty_only`(기본) 또는 `always`
  - `--table-ocr-dpi`, `--table-ocr-min-chars`로 품질/비용 조절
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
- PaddleOCR은 런타임에서 GPU 가능 여부를 확인해 `use_gpu`를 자동 선택하며, 결과는 `parsing_report.json`의 `paddle_use_gpu`에 기록
