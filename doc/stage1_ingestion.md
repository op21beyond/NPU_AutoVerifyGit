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
- 오픈 이슈:
  - PaddleOCR 등 2차 OCR 엔진·이미지 표(`img2table`)는 미연동
  - 표·본문 중복 억제는 bbox 휴리스틱 수준
- 다음 액션:
  - 실제 Architecture PDF로 라우팅 임계값(`--min-chars-ocr`) 튜닝
  - Stage 3과 표 블록 품질 공동 검증

## Technical Note
- 텍스트 레이어 우선, 부족 시 OCR 보강 전략
- 블록 분리 품질이 전체 정확도에 미치는 영향이 크므로 bbox 보존 필수
- `block_id`로 블록 간 참조; `relationships`로 표-설명-수식 등 연결(각 항목 `type`, `target` = 대상 `block_id`)
