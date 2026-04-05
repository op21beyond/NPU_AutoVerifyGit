# Tools (비파이프라인)

파이프라인에 직접 포함되지 않지만 개발·검증에 쓰는 스크립트와 앱을 둡니다.

## `page_coverage_viewer`

Stage 2가 생성하는 `page_coverage.json`을 **줌/브러시** 가능한 막대 차트로 봅니다(긴 문서용). 기본 PNG와 동일 데이터입니다.

**요구:** Node.js(LTS 권장) + npm — `pip`으로 설치하지 않습니다. (`tools/requirements-tools.txt` 주석 참고.)

```bash
cd tools/page_coverage_viewer
npm install
npm run dev
```

브라우저에서 `artifacts/stage2_instruction_extraction/page_coverage.json`을 파일 선택으로 엽니다. 자세한 설명은 [`tools/page_coverage_viewer/README.md`](page_coverage_viewer/README.md).

## `streamlit_llm_chat`

회사 원격 LLM(최대 5종, OpenAI 호환 Chat Completions)과 Stage1 `page_blocks.jsonl`을 연결하는 챗 UI입니다.

### 설정

환경 변수(각 서비스별):

| 변수 | 의미 |
|------|------|
| `COMPANY_LLM_N_BASE_URL` | API 베이스 URL (예: `https://gateway/v1`, 끝의 `/v1` 포함 여부는 게이트웨이에 맞출 것) |
| `COMPANY_LLM_N_API_KEY` | API 키 |
| `COMPANY_LLM_N_MODEL` | 모델 ID (미설정 시 기본 `gpt-4o`) |

`N` = `1` … `5`.

### 실행

저장소 루트에서:

```bash
pip install streamlit openai
streamlit run tools/streamlit_llm_chat/app.py
```

### 페이지·블록 선택 (한 줄)

쉼표로 여러 조각을 합칩니다. 예: `페이지 1` / `p1` / `1` → 1페이지 전체 · `p1_20` → `p1_b20` 한 블록 · `p1-p2` 또는 `p1, p2` → 페이지 구간 · `p1_10, p2_20` → 두 블록 · `p1_10-p2_20` → 읽기 순서 구간(중간 페이지 포함). 영어·한글·대소문자 구분 없음.

### 동작

- 업로드한 `page_blocks.jsonl`과 위 선택 식으로 **`selected_page_blocks`** 딕셔너리를 만듭니다. 키는 Stage1의 `block_id`(예: `p1_b10`), 값은 비어 있지 않은 `raw_text`입니다.
- System / User 프롬프트에 따라, JSON은 **User 메시지**에 붙거나(기본), “User에 포함 안 함”이면 **System** 메시지에 붙습니다.
- **싱글턴**(기본): 매 전송 시 히스토리 없음. **멀티턴**: 이전 user/assistant 쌍을 유지합니다.
- **출력1**: 어시스턴트 `content` 또는 API 오류 JSON. **출력2**: 전체 응답 JSON(옵션). **출력3**: Python 예외 traceback(API 오류는 출력3에 넣지 않음).
