# Ontology graph viewer

Stage5가 만든 `mission_ontology_graph.json`을 **Pyvis(vis.js)** 로 드래그·줌 가능한 그래프로 봅니다.

## 실행

저장소 루트에서:

```bash
pip install -r tools/requirements-tools.txt
streamlit run tools/ontology_graph_viewer/app.py
```

브라우저에서 **사용 방법**은 앱 상단 Expander에 정리되어 있습니다.

## 입력

- 기본 경로: `artifacts/stage5_constraint_ontology/mission_ontology_graph.json`
- JSON 형식: `{ "nodes": [ { "id", "type", ... } ], "edges": [ { "from", "to", "rel" } ] }`
