"""
Streamlit: visualize Stage5 mission_ontology_graph.json (nodes + edges) with Pyvis (vis.js).

Run from repo root:
  pip install -r tools/requirements-tools.txt
  streamlit run tools/ontology_graph_viewer/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_GRAPH = ROOT / "artifacts" / "stage5_constraint_ontology" / "mission_ontology_graph.json"

# Pyvis node colors by ontology node type (Stage5 build_mission_ontology_graph)
TYPE_COLORS = {
    "IP": "#e94560",
    "ExecutionUnit": "#533483",
    "Instruction": "#0f3460",
    "Field": "#16213e",
    "DataType": "#1a508b",
    "Constraint": "#c84b31",
    "node": "#444444",
}


def _defaults() -> Dict[str, Any]:
    return {
        "json_path": str(DEFAULT_GRAPH),
        "max_edges": 800,
        "physics": True,
        "directed": True,
    }


def _ensure_state() -> None:
    import streamlit as st

    for k, v in _defaults().items():
        if k not in st.session_state:
            st.session_state[k] = v


def load_graph(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(f"파일 없음: {path}")
    with path.open(encoding="utf-8") as fp:
        data = json.load(fp)
    nodes = list(data.get("nodes") or [])
    edges = list(data.get("edges") or [])
    return nodes, edges


def build_pyvis_html(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    *,
    max_edges: int,
    physics: bool,
    directed: bool,
) -> str:
    from pyvis.network import Network

    if max_edges > 0 and len(edges) > max_edges:
        edges = edges[:max_edges]

    net = Network(
        height="640px",
        width="100%",
        bgcolor="#0f0f1a",
        font_color="#eaeaea",
        directed=directed,
    )
    net.set_options(
        """
        {
          "physics": {
            "enabled": %s,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "gravitationalConstant": -38,
              "centralGravity": 0.015,
              "springLength": 120,
              "springConstant": 0.08
            },
            "minVelocity": 0.75
          },
          "edges": { "smooth": { "type": "continuous" }, "font": { "size": 10, "align": "middle" } },
          "nodes": { "font": { "size": 13 } },
          "interaction": { "hover": true, "tooltipDelay": 80 }
        }
        """
        % str(physics).lower()
    )

    seen: Set[str] = set()
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        if not nid or nid in seen:
            continue
        seen.add(nid)
        nt = str(n.get("type", "node"))
        color = TYPE_COLORS.get(nt, TYPE_COLORS["node"])
        label = nid if len(nid) <= 36 else nid[:33] + "…"
        tip = json.dumps(n, ensure_ascii=False, indent=2)[:3500]
        net.add_node(nid, label=label, color=color, title=tip)

    for e in edges:
        a = str(e.get("from", "")).strip()
        b = str(e.get("to", "")).strip()
        rel = str(e.get("rel", "")).strip() or "REL"
        if not a or not b:
            continue
        if a not in seen:
            net.add_node(a, label=a[:36], color="#555555", title=a)
            seen.add(a)
        if b not in seen:
            net.add_node(b, label=b[:36], color="#555555", title=b)
            seen.add(b)
        net.add_edge(a, b, title=rel, label=rel[:24])

    return net.generate_html()


def main() -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.set_page_config(page_title="Ontology graph viewer", layout="wide")
    _ensure_state()

    st.title("Mission ontology graph viewer")
    st.caption("Stage5 `mission_ontology_graph.json` → 인터랙티브 그래프 (Pyvis / vis.js)")

    with st.expander("사용 방법 (클릭하여 펼치기)", expanded=True):
        st.markdown(
            """
### 1. 그래프 JSON 만들기
- 파이프라인에서 **Stage5**까지 실행하면 기본 경로에 파일이 생성됩니다.  
  `artifacts/stage5_constraint_ontology/mission_ontology_graph.json`
- 또는 `python -m src.stage5_constraint_ontology.main` 을 단독 실행해 동일 산출물을 만듭니다.

### 2. 이 앱에서 할 일
1. 아래 **JSON 파일 경로**에 위 파일의 절대/상대 경로를 넣습니다 (저장소 루트 기준 상대 경로 가능).
2. **최대 엣지 수**로 렌더링 부담을 줄입니다 (노드가 많을 때).
3. **물리 엔진**을 끄면 레이아웃이 고정되어 CPU 부담이 줄어듭니다.
4. **그래프 그리기**를 누릅니다.

### 3. 화면에서
- **노드 드래그**로 배치를 바꿀 수 있습니다.
- **마우스 휠**로 줌, **노드에 마우스를 올리면** JSON 속성 툴팁이 보입니다.
- **엣지 라벨**은 관계 이름(`HAS_FIELD`, `APPLIES_TO` 등)입니다.

### 4. 노드 색 (범례)
            """
        )
        cols = st.columns(len(TYPE_COLORS))
        for (name, color), c in zip(TYPE_COLORS.items(), cols):
            c.markdown(f'<span style="color:{color};font-weight:bold">■</span> {name}', unsafe_allow_html=True)

    st.divider()

    col_a, col_b, col_c, col_d = st.columns([3, 1, 1, 1])
    with col_a:
        st.text_input(
            "mission_ontology_graph.json 경로",
            key="json_path",
            help="Stage5 산출 JSON (nodes / edges)",
        )
    with col_b:
        st.number_input("최대 엣지 수 (0=제한 없음)", min_value=0, max_value=20000, step=100, key="max_edges")
    with col_c:
        st.checkbox("물리 시뮬레이션", key="physics")
    with col_d:
        st.checkbox("방향 엣지(화살표)", key="directed")

    path = Path(st.session_state.json_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()

    run = st.button("그래프 그리기", type="primary")

    if run:
        try:
            nodes, edges = load_graph(path)
            max_e = int(st.session_state.max_edges)
            html = build_pyvis_html(
                nodes,
                edges,
                max_edges=max_e,
                physics=bool(st.session_state.physics),
                directed=bool(st.session_state.directed),
            )
            st.session_state.last_html = html
            st.session_state.last_meta = {
                "path": str(path),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "max_edges_applied": max_e if max_e > 0 else "all",
            }
        except Exception as ex:
            st.error(str(ex))
            return

    if "last_html" in st.session_state:
        meta = st.session_state.get("last_meta", {})
        st.success(
            f"로드: `{meta.get('path')}` — JSON 노드 **{meta.get('node_count')}**개, 엣지 **{meta.get('edge_count')}**개 "
            f"(표시 제한: {meta.get('max_edges_applied')})"
        )
        components.html(st.session_state.last_html, height=680, scrolling=False)
    else:
        st.info("JSON 경로를 확인한 뒤 **그래프 그리기**를 누르세요. 단계별 안내는 위 **사용 방법** Expander에 있습니다.")


if __name__ == "__main__":
    main()
