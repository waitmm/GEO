#!/usr/bin/env python3
"""工作流端到端烟雾测试 — 审核 → 事件/对齐确认 → 继续分析 → Gap/Action 确认 → 渠道 → 大纲 → Brief → 执行计划 → 实验。

用法：
    python3 scripts/workflow_smoke_test.py [BASE_URL] [PROJECT_ID] [PROMPT_ID]

默认 BASE_URL=http://127.0.0.1:8000。建议对数据库副本运行（避免改动真实数据）：
    cp geo_v0.db /tmp/geo_test.db
    DATABASE_URL=sqlite:////tmp/geo_test.db uvicorn app.main:app --port 8899 &
    python3 scripts/workflow_smoke_test.py http://127.0.0.1:8899 3 17

任一步骤失败以非零码退出，并打印 FAIL 原因。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def req(base: str, method: str, path: str, payload: dict | None = None, timeout: int = 300):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        f"{base}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]
    except Exception as e:  # 网络/超时
        return -1, str(e)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}")
    if not ok:
        sys.exit(1)


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    project_id = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    prompt_id = int(sys.argv[3]) if len(sys.argv) > 3 else 17
    wf = f"/api/optimization/workflow/{project_id}/{prompt_id}"
    print(f"== 工作流烟雾测试: {base} project={project_id} prompt={prompt_id} ==\n")

    # 1. 加载审核队列
    s, q = req(base, "GET", f"{wf}/review-queue")
    check("1. 审核队列加载", s == 200 and q.get("status") == "READY",
          f"status={q.get('status') if isinstance(q, dict) else q}")

    # 2. 确认所有事件（去重组）
    for e in q.get("unique_events") or []:
        s, r = req(base, "POST", "/api/optimization/workflow/review/events/confirm-batch",
                   {"event_ids": e.get("event_ids") or []})
        check("2. 事件确认", s == 200, f"entity={e.get('entity_text')} resp={r}")
    # 3. 确认所有 SUPPORTS 对齐
    aligns = q.get("alignments") or []
    for a in aligns:
        s, r = req(base, "POST", f"/api/optimization/workflow/review/alignments/{a['alignment_id']}/confirm",
                   {"relation": "SUPPORTS"})
        check("3. 对齐确认", s == 200 and (r.get("status") == "CONFIRMED" if isinstance(r, dict) else False),
              f"alignment_id={a['alignment_id']}")
    if not aligns:
        print("   (无待审对齐，跳过)")

    # 4. 竞品候选：拒绝接口（幂等）
    s, cc = req(base, "GET", f"{wf}/competitor-candidates")
    if s == 200 and isinstance(cc, list) and cc:
        first = cc[0]["entity"]
        s2, r2 = req(base, "POST", f"/api/optimization/workflow/{project_id}/competitor-candidates/reject",
                     {"name": f"__smoke_test_placeholder_{first}"})
        check("4. 竞品候选拒绝接口", s2 == 200, f"resp={r2}")
        s3, cc2 = req(base, "GET", f"{wf}/competitor-candidates")
        check("4b. 候选发现不受占位符影响", s3 == 200 and len(cc2) == len(cc), f"{len(cc2)} vs {len(cc)}")
    else:
        print("   (无竞品候选，跳过)")

    # 5. 状态：审核完成
    s, st = req(base, "GET", f"{wf}/status")
    check("5. 审核全部完成", s == 200 and st.get("all_reviews_done") is True,
          f"pending={st.get('pending_review_steps') if isinstance(st, dict) else st}")

    # 6. 继续分析 → Gap/Action
    s, r = req(base, "POST", f"{wf}/continue", {})
    ok = s == 200 and isinstance(r, dict) and r.get("gap") and r.get("action")
    check("6. 继续分析生成 Gap/Action", ok, f"gap={(r or {}).get('gap', {}).get('gap_type') if isinstance(r, dict) else r}")

    # 7. 确认 Gap / Action
    for step in ("gap", "action"):
        s, rr = req(base, "POST", f"{wf}/confirm-decision", {"step_key": step, "decision_status": "CONFIRMED"})
        check(f"7. 确认 {step}", s == 200, f"resp={rr}")

    # 8. 状态：Gap/Action 已确认（写读一致）
    s, st = req(base, "GET", f"{wf}/status")
    steps = {x["key"]: x for x in st.get("steps", [])} if isinstance(st, dict) else {}
    check("8. 状态反映 Gap/Action 已确认", s == 200 and steps.get("gap", {}).get("done") and steps.get("action", {}).get("done"),
          f"gap={steps.get('gap', {}).get('detail')} action={steps.get('action', {}).get('detail')}")

    # 9. 选择渠道 → Experiment 草案
    s, r = req(base, "GET", f"{wf}/channel-strategy")
    ok_cs = s == 200 and isinstance(r, dict) and r.get("platforms") and r.get("content_direction") and r.get("combination")
    check("9a. V3 平台×内容方向分析", ok_cs,
          f"platforms={[(p.get('label'), p.get('tier')) for p in (r or {}).get('platforms', [])] if isinstance(r, dict) else r}")
    s, r = req(base, "POST", f"{wf}/select-channels", {"channels": ["OWNED_NEW_PAGE"]})
    drafts = (r or {}).get("drafts", []) if isinstance(r, dict) else []
    ok = s == 200 and len(drafts) >= 1 and drafts[0].get("experiment_id")
    check("9. 多选渠道创建实验草案", ok, f"drafts={[d.get('channel') for d in drafts] if isinstance(r, dict) else r}")
    exp_id = drafts[0].get("experiment_id") if drafts else None
    channel = drafts[0].get("channel") if drafts else "OWNED_NEW_PAGE"

    # 10. 生成内容大纲（按渠道内容类型与对标样本）
    s, r = req(base, "POST", f"{wf}/generate-outline", {"channel": channel})
    ok = s == 200 and isinstance(r, dict) and (r.get("outline") or r.get("sections"))
    check("10. 生成内容大纲（渠道定制）", ok, f"title={(r or {}).get('title') if isinstance(r, dict) else r}")

    # 11. 生成详细 Brief
    if ok:
        s, r = req(base, "POST", f"{wf}/generate-brief", {"channel": channel, "outline": r})
        ok2 = s == 200 and isinstance(r, dict) and (r.get("sections") or r.get("brief"))
        check("11. 生成详细 Brief", ok2, f"sections={len((r or {}).get('sections') or []) if isinstance(r, dict) else r}")
    else:
        print("   (跳过 Brief：大纲失败)")

    # 12. 执行计划（执行策略页）
    s, r = req(base, "POST", f"{wf}/plan", {})
    check("12. 创建执行计划", s == 200, f"resp={(r or {}) if isinstance(r, dict) else r}")

    # 13. 状态：实验步骤展示草案信息（不再是「待 Action 确认后进入」）
    s, st = req(base, "GET", f"{wf}/status")
    exp_step = {x["key"]: x for x in st.get("steps", [])}.get("experiment", {}) if isinstance(st, dict) else {}
    detail = exp_step.get("detail", "")
    check("13. 实验步骤展示进展", s == 200 and "待 Action 确认后进入" not in detail and detail != "未开始",
          f"detail={detail}")

    # 14. 实验列表
    s, exps = req(base, "GET", f"{wf}/experiments")
    check("14. 实验列表", s == 200 and isinstance(exps, list) and len(exps) >= 1,
          f"count={len(exps) if isinstance(exps, list) else exps}")

    # 15. 实验对标（Benchmark）
    if exp_id:
        s, r = req(base, "GET", f"/api/optimization/workflow/experiments/{exp_id}/benchmark")
        check("15. 实验对标", s == 200, f"resp={(r or {}) if isinstance(r, dict) else r}")

    print("\n== 全部通过 ✅ ==")


if __name__ == "__main__":
    main()
