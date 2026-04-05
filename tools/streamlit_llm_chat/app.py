"""
Streamlit: remote LLM (5 company profiles) + page_blocks.jsonl → selected_page_blocks → chat.

Run from repo root:
  streamlit run tools/streamlit_llm_chat/app.py
"""

from __future__ import annotations

import json
import traceback
from typing import Dict, List

import streamlit as st

from llm_backend import (
    DEFAULT_PROFILES,
    LLMProfile,
    assistant_content_from_response,
    chat_completion,
    resolve_profile,
    response_to_full_json,
)
from page_block_loader import load_jsonl_from_bytes, parse_block_selection_spec

DEFAULT_SYSTEM = """\
You work with a Python-provided dictionary called selected_page_blocks.
- Interpret selected_page_blocks as a mapping from page/block keys (e.g. p1_b10) to that block's raw_text string.
- Follow the user instructions using only that content unless the user asks otherwise."""

DEFAULT_USER = """\
Using selected_page_blocks, check whether any text describes constraints on NPU instruction fields.
- If yes, reply with the category and the relevant content.
- If not, reply exactly: no restrictions found"""

SELECTION_HELP = """
**한 줄에 입력** (쉼표로 여러 조각을 합칩니다). 영어/한글·대소문자 무시.

| 예시 | 의미 |
|------|------|
| `페이지 1`, `p1`, `1` | 1페이지의 모든 블록 |
| `p1_20` | 블록 `p1_b20` 한 개 |
| `p1, p2` 또는 `p1-p2` | 페이지 1·2(또는 연속 구간)의 모든 블록 |
| `p1_10, p2_20` | `p1_b10`과 `p2_b20` 두 블록만 |
| `p1_10-p2_20` | 읽기 순서로 `p1_b10`부터 `p2_b20`까지(중간 페이지 블록 전부 포함) |
"""


def _inject_styles() -> None:
    st.markdown(
        """
<style>
  div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(49, 51, 63, 0.2) !important;
    border-radius: 10px !important;
  }
</style>
        """,
        unsafe_allow_html=True,
    )


def _bordered_container():
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _init_session() -> None:
    if "turn_history" not in st.session_state:
        st.session_state.turn_history = []
    if "last_assistant_text" not in st.session_state:
        st.session_state.last_assistant_text = ""
    if "last_full_json" not in st.session_state:
        st.session_state.last_full_json = ""
    if "last_api_error_json" not in st.session_state:
        st.session_state.last_api_error_json = ""
    if "last_python_debug" not in st.session_state:
        st.session_state.last_python_debug = ""
    if "last_selected_page_blocks_json" not in st.session_state:
        st.session_state.last_selected_page_blocks_json = ""
    # 프롬프트·선택 식: 세션 동안 유지 (전송 후에도 편집 내용 보존)
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = DEFAULT_SYSTEM
    if "user_prompt" not in st.session_state:
        st.session_state.user_prompt = DEFAULT_USER
    if "block_spec" not in st.session_state:
        st.session_state.block_spec = "p1"


def main() -> None:
    _init_session()
    st.set_page_config(page_title="LLM · page blocks", layout="wide", initial_sidebar_state="collapsed")
    _inject_styles()

    st.markdown("## 🤖 원격 LLM · Stage1 page blocks")
    st.caption(
        "회사 LLM 게이트웨이와 page_blocks.jsonl을 연결해 selected_page_blocks를 만들고 질의합니다."
    )

    # --- LLM ---
    with _bordered_container():
        st.markdown("### 🔌 LLM 서비스")
        st.caption("환경 변수 `COMPANY_LLM_1` … `COMPANY_LLM_5` 로 베이스 URL / API 키 / 모델을 설정합니다.")
        labels = [p.label for p in DEFAULT_PROFILES]
        idx = st.selectbox("연결할 서비스", range(len(labels)), format_func=lambda i: labels[i], label_visibility="collapsed")
        profile: LLMProfile = DEFAULT_PROFILES[idx]
        base, _key, model = resolve_profile(profile)
        st.markdown(
            f'<span style="font-size:0.9rem;">🔑 `{profile.base_url_env}` → **{base or "*(미설정)*"}** · 모델: `{model}`</span>',
            unsafe_allow_html=True,
        )

    # --- File ---
    with _bordered_container():
        st.markdown("### 📄 입력 파일 (Stage1 산출물)")
        st.caption("JSON Lines: 각 줄에 `page`, `block_id`, `raw_text`, `bbox` 등.")
        uploaded = st.file_uploader("page_blocks.jsonl", type=["jsonl", "txt"], label_visibility="collapsed")

    # --- Selection ---
    with _bordered_container():
        st.markdown("### 📑 페이지 · 블록 선택")
        st.caption("아래 **한 칸**에만 조건을 적습니다 (라디오/분기 없음).")
        with st.expander("📖 입력 형식 도움말", expanded=False):
            st.markdown(SELECTION_HELP)
        st.text_input(
            "선택 식",
            placeholder="예: 페이지 1  /  p1_20  /  p1-p2  /  p1_10, p2_20  /  p1_10-p2_20",
            label_visibility="collapsed",
            key="block_spec",
        )

    # --- Prompts ---
    with _bordered_container():
        st.markdown("### ✉️ 프롬프트")
        st.caption("멀티턴 중에도 여기서 수정한 문구는 세션 동안 유지됩니다 (다음 전송에 반영).")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🛡️ System prompt**")
            st.text_area("system", height=140, label_visibility="collapsed", key="system_prompt")
        with c2:
            st.markdown("**👤 User prompt**")
            st.text_area("user", height=140, label_visibility="collapsed", key="user_prompt")

    # --- Options ---
    with _bordered_container():
        st.markdown("### ⚙️ 옵션")
        o1, o2, o3 = st.columns(3)
        with o1:
            multi_turn = st.checkbox("🔁 멀티턴 (이전 user/assistant 유지)", value=False)
        with o2:
            show_full_response = st.checkbox("📋 전체 LLM 응답 JSON 표시", value=False)
        with o3:
            include_json_in_user = st.checkbox("📎 User 메시지에 `selected_page_blocks` JSON 포함", value=True)

    st.markdown("")
    send = st.button("🚀 전송", type="primary", use_container_width=True)

    if send:
        st.session_state.last_python_debug = ""
        st.session_state.last_api_error_json = ""
        st.session_state.last_full_json = ""
        st.session_state.last_assistant_text = ""

        try:
            if uploaded is None:
                raise ValueError("page_blocks.jsonl 파일을 업로드하세요.")

            system_prompt = str(st.session_state.system_prompt)
            user_prompt = str(st.session_state.user_prompt)
            block_spec = str(st.session_state.block_spec)

            raw_bytes = uploaded.getvalue()
            rows = load_jsonl_from_bytes(raw_bytes)
            selected_page_blocks: Dict[str, str] = parse_block_selection_spec(block_spec, rows)

            blocks_json = json.dumps(selected_page_blocks, ensure_ascii=False, indent=2)
            st.session_state.last_selected_page_blocks_json = blocks_json

            if include_json_in_user:
                user_final = (
                    user_prompt.strip()
                    + "\n\n---\nselected_page_blocks (JSON):\n"
                    + blocks_json
                )
                system_final = system_prompt.strip()
            else:
                user_final = user_prompt.strip()
                system_final = (
                    system_prompt.strip()
                    + "\n\n---\nselected_page_blocks (JSON):\n"
                    + blocks_json
                )

            messages: List[Dict[str, str]] = [{"role": "system", "content": system_final}]
            if multi_turn:
                for m in st.session_state.turn_history:
                    messages.append({"role": m["role"], "content": m["content"]})
            messages.append({"role": "user", "content": user_final})

            resp, api_err = chat_completion(profile, messages)
            if api_err is not None:
                st.session_state.last_api_error_json = json.dumps(api_err, ensure_ascii=False, indent=2)
                st.session_state.last_assistant_text = st.session_state.last_api_error_json
                st.session_state.last_full_json = ""
            else:
                st.session_state.last_assistant_text = assistant_content_from_response(resp)
                st.session_state.last_full_json = response_to_full_json(resp)

            if multi_turn and api_err is None and resp is not None:
                st.session_state.turn_history.append({"role": "user", "content": user_final})
                st.session_state.turn_history.append(
                    {"role": "assistant", "content": st.session_state.last_assistant_text}
                )
            elif not multi_turn:
                st.session_state.turn_history.clear()

        except Exception:
            st.session_state.last_python_debug = traceback.format_exc()

    # --- Output ---
    st.markdown("---")
    st.markdown("### 📤 출력")

    with _bordered_container():
        st.markdown("#### 💬 ① LLM 답변 (content · 또는 API 오류 본문)")
        st.text_area(
            "out1",
            value=st.session_state.last_assistant_text,
            height=220,
            label_visibility="collapsed",
        )

    with _bordered_container():
        st.markdown("#### 📦 ② 전체 응답 (원시 JSON)")
        if show_full_response:
            st.text_area(
                "out2",
                value=st.session_state.last_full_json,
                height=220,
                label_visibility="collapsed",
            )
        else:
            st.info("위 **옵션**에서 「전체 LLM 응답 JSON 표시」를 켜면 여기에 표시됩니다.")

    with _bordered_container():
        st.markdown("#### 🐞 ③ 코드/파싱 오류 (디버그 · API 오류 제외)")
        st.caption("Python 예외·파일 파싱 오류만 표시합니다. LLM HTTP/API 오류는 ①에 나옵니다.")
        st.text_area(
            "out3",
            value=st.session_state.last_python_debug,
            height=160,
            label_visibility="collapsed",
        )

    with _bordered_container():
        st.markdown("#### 🗂️ `selected_page_blocks` 미리보기 (마지막 전송)")
        st.text_area(
            "preview",
            value=st.session_state.last_selected_page_blocks_json or "(아직 전송 없음)",
            height=200,
            label_visibility="collapsed",
        )

    if st.button("🧹 멀티턴 히스토리만 초기화 (프롬프트는 유지)"):
        st.session_state.turn_history.clear()
        st.rerun()


if __name__ == "__main__":
    main()
