# Few-Shot Seed (Partial, Illustrative)

이 시드는 요청자가 팀에게 전달하는 **단서**다. 시드는 정답표가 아니다.

> ⚠️ **이 시드는 목표 온톨로지의 30–40% 정도일 뿐이다.** 본문에서 추가 타입을 적극 발견해야 한다. 자세한 안내는 [`workflow.md`](workflow.md) Step 2의 "시드 anchoring 회피 5요령" 참조.

## 도메인 배경

- NPU **instruction**은 **execution unit**(= function unit)에서 실행된다.
- 각 instruction은 **opcode**로 구별되며, **field**들로 구성된다 (operand / encoding bits).
- 각 field는 **datatype**을 갖는다.
- datatype은 다음을 모두 포함한다:
  - 이 NPU 고유의 explicit 타입 (예: 4-bit signed mantissa).
  - implicit 주소 표현 — unsigned integer를 address로 해석.
  - enum 타입 — 허용 값 리스트에서 하나를 선택. enum의 원소들도 다시 datatype이다.
- datatype은 sub-component를 가질 수 있다. floating-point의 경우 `exponent`, `mantissa`, 그리고 `zero_point`, `shift`, 기타 상수들이 표현식에 등장.
- datatype은 값 범위 또는 허용 값 리스트를 가진다. 명령별 override가 흔하다.
- field의 허용 값은 **같은 명령의 다른 field** 또는 **명령 인코딩 바깥의 global variable**에 의존할 수 있다.
- instruction은 입력 텐서(feature map / weight / bias / …)와 출력 텐서를 가지며, 각각 **data format**을 갖는다 (예: NHWC, NCHW, packed-int8, block-floating-point 변종 등 다수).

## 시드 엔터티 타입 (대표 일부)

```json
{
  "is_seed": true,
  "is_partial": true,
  "expected_total_entity_types_hint": "15-30",
  "entity_types": [
    {
      "name": "Instruction",
      "definition": "opcode로 식별되는 NPU 명령어.",
      "example_properties": ["opcode", "mnemonic", "instruction_kind"]
    },
    {
      "name": "ExecutionUnit",
      "definition": "명령을 실행하는 하드웨어 유닛 (= function unit).",
      "example_properties": ["name"]
    },
    {
      "name": "Field",
      "definition": "명령 안의 operand / encoding 슬롯.",
      "example_properties": ["name", "bit_position", "bit_width"]
    },
    {
      "name": "DataType",
      "definition": "field 또는 텐서 원소의 타입.",
      "example_properties": ["name", "kind", "value_range", "allowed_values"]
    },
    {
      "name": "DataFormat",
      "definition": "입력/출력 텐서의 레이아웃/포맷.",
      "example_properties": ["name"]
    }
  ]
}
```

## 시드 관계 타입 (대표 일부)

```json
{
  "is_seed": true,
  "is_partial": true,
  "expected_total_relation_types_hint": "20-40",
  "relation_types": [
    {"name": "EXECUTES_ON",       "domain": "Instruction", "range": "ExecutionUnit",
     "definition": "명령이 특정 실행 유닛에 디스패치된다."},
    {"name": "HAS_FIELD",         "domain": "Instruction", "range": "Field",
     "definition": "명령은 하나 이상의 field로 구성된다."},
    {"name": "HAS_DATATYPE",      "domain": "Field",       "range": "DataType",
     "definition": "field 값은 주어진 datatype으로 해석된다."},
    {"name": "HAS_SUBCOMPONENT",  "domain": "DataType",    "range": "DataType",
     "definition": "datatype은 타입이 있는 부분들로 구성된다 (예: FP의 exponent/mantissa)."},
    {"name": "HAS_ENUM_MEMBER",   "domain": "DataType",    "range": "DataType",
     "definition": "enum datatype의 원소들 — 자체도 타입이 있다."},
    {"name": "HAS_INPUT_FORMAT",  "domain": "Instruction", "range": "DataFormat",
     "definition": "명령이 소비하는 텐서의 포맷."},
    {"name": "HAS_OUTPUT_FORMAT", "domain": "Instruction", "range": "DataFormat",
     "definition": "명령이 생성하는 텐서의 포맷."}
  ]
}
```

## 의도적으로 시드에서 뺀 항목 (LLM이 발견해야 함)

다음은 실제 NPU 스펙에 흔하지만 **일부러 시드에서 제외**했다. 파이프라인은 본문에서 이런 종류를 직접 찾아내야 한다 — 이 목록 자체도 일부에 불과하다.

- **Constraint** 엔터티와 `APPLIES_TO` / `DEPENDS_ON` 관계.
- **GlobalVariable** 엔터티 (명령 인코딩 바깥의 설정값) 및 `CONSTRAINS` 관계.
- **Tensor / FeatureMap / Weight / Bias** 엔터티와 `CONSUMES` / `PRODUCES` 관계.
- 명령별 datatype override (`OVERRIDES_DATATYPE_FOR` 같은 관계).
- 메모리 / 주소 공간 엔터티, 스케줄링 관련 엔터티 등.

## 출력 형태 grounding (Step 4 프롬프트에 함께 넣을 단일 예시)

산출 모양을 구체화하기 위한 **하나의** 인스턴스 예시 — 이 또한 한정 형식이 아니다:

```json
{
  "entities": [
    {"id": "Instruction:CONV2D",       "type": "Instruction",
     "name": "CONV2D", "properties": {"opcode": 12, "mnemonic": "conv2d"},
     "evidence": "CONV2D performs 2D convolution on the MAC array."},
    {"id": "ExecutionUnit:MAC_ARRAY",  "type": "ExecutionUnit",
     "name": "MAC array", "properties": {},
     "evidence": "CONV2D performs 2D convolution on the MAC array."}
  ],
  "relations": [
    {"from_id": "Instruction:CONV2D",  "type": "EXECUTES_ON",
     "to_id": "ExecutionUnit:MAC_ARRAY", "properties": {},
     "evidence": "CONV2D performs 2D convolution on the MAC array."}
  ]
}
```

## 시드 사용 규약 (팀에게)

1. 이 시드를 **프롬프트에 그대로 임베드**하되, `is_seed`/`is_partial`/`expected_total_*_hint` 메타를 같이 넘긴다.
2. workflow.md Step 2의 "시드 anchoring 회피 5요령"을 모두 적용한다.
3. 시드 정의가 본문 사용과 충돌하면 **본문을 신뢰**하고 새 타입을 만든다 (시드를 우격다짐 적용하지 않는다).
