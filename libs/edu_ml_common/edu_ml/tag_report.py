from __future__ import annotations

from typing import Any

from edu_ml.tag_stats import clamp_tag_score


def _scores_from_tag_alignment(ta: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, cell in ta.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(cell, dict):
            c = clamp_tag_score(cell.get("score"))
            if c is not None:
                out[name.strip()] = c
        else:
            c = clamp_tag_score(cell)
            if c is not None:
                out[name.strip()] = c
    return out


def extract_tag_mastery_from_report(obj: dict[str, Any]) -> dict[str, float]:
    merged: dict[str, float] = {}
    sols = obj.get("solutions")
    if isinstance(sols, list):
        for sol in sols:
            if not isinstance(sol, dict):
                continue
            an = sol.get("analysis")
            if not isinstance(an, dict):
                continue
            tc = an.get("task_compliance")
            if isinstance(tc, dict):
                ta = tc.get("tag_alignment")
                if isinstance(ta, dict):
                    merged.update(_scores_from_tag_alignment(ta))
            ta_top = an.get("tag_alignment")
            if isinstance(ta_top, dict):
                merged.update(_scores_from_tag_alignment(ta_top))
    tc_top = obj.get("task_compliance")
    if isinstance(tc_top, dict):
        ta = tc_top.get("tag_alignment")
        if isinstance(ta, dict):
            merged.update(_scores_from_tag_alignment(ta))
    if merged:
        return merged
    for key in ("tag_mastery", "tags", "per_tag", "scores_by_tag", "tag_scores", "mastery_by_tag"):
        block = obj.get(key)
        if not isinstance(block, dict):
            continue
        out: dict[str, float] = {}
        for k, v in block.items():
            if not isinstance(k, str) or not k.strip():
                continue
            m = clamp_tag_score(v)
            if m is not None:
                out[k.strip()] = m
        if out:
            return out
    return {}
