"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also: duplicated (item, seed) rows, a manifest that disagrees with the baseline's, graded
    values that are not booleans, and reported metrics that do not match a recount of the rows."""
    problems: list[str] = []
    rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. NaN / inf anywhere a number is reported
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (a crashed grader or a divide by zero, not a score)")

    # 2. evaluator failures, even on a green run: a grader that crashed did not grade anything
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")

    # 3. row count, duplicates, and the (item, seed) set against the manifest and the baseline
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0]}")
    if (man.get("items"), sorted(man.get("seeds") or [])) != (bman.get("items"), sorted(bman.get("seeds") or [])):
        problems.append(f"manifest items/seeds {man.get('items')}/{man.get('seeds')} differ from the baseline's "
                        f"{bman.get('items')}/{bman.get('seeds')}")
    pr_set, base_set = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pr_set != base_set:
        missing, extra = sorted(base_set - pr_set, key=str), sorted(pr_set - base_set, key=str)
        problems.append(f"(item, seed) set differs from the baseline: {len(missing)} missing"
                        f"{' e.g. ' + str(missing[0]) if missing else ''}, {len(extra)} extra"
                        f"{' e.g. ' + str(extra[0]) if extra else ''}")

    # 4. every graded metric has a real verdict on every row
    for m in graded:
        bad = [r for r in rows if not isinstance(r.get(m), bool)]
        if bad:
            problems.append(f"{len(bad)} row(s) with no boolean {m} (e.g. {bad[0].get('item_id')}@{bad[0].get('seed')}"
                            f" = {bad[0].get(m)!r}): an ungraded row drops out of the mean")

    # 5. reported metrics must equal a recount of the rows (hand-edited or recomputed-after-drop numbers)
    present = [m for m in graded if rows and all(isinstance(r.get(m), bool) for r in rows)]
    if present:
        try:
            recount = aggregate(rows, present, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            recount = {}
        for k, v in recount.items():
            got = (pr.get("metrics") or {}).get(k)
            if isinstance(v, (int, float)) and isinstance(got, (int, float)) and math.isfinite(got) \
                    and abs(got - v) > 1e-3:
                problems.append(f"metric {k} reported {got} but the rows give {v}")

    # 6. slice tags per item must match the baseline's
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    retagged = sorted({r.get("item_id") for r in rows
                       if r.get("item_id") in base_tags and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]},
                      key=str)
    if retagged:
        problems.append(f"slice tags changed on {len(retagged)} item(s), first {retagged[0]}")

    # 7. ratchet: on the same eval-set version thresholds may only get stricter
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


_STRICTER_FLAGS = ("no_significant_drop", "no_item_regression")


def _looser(where: str, new: dict | None, old: dict) -> list[str]:
    if new is None:
        return [f"RATCHET {where} removed"]
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"RATCHET {where} no longer blocking")
    nt = new.get("threshold", new) if "threshold" in old or "threshold" in new else new
    ot = old.get("threshold", old) if "threshold" in old or "threshold" in new else old
    for key in ("max", "max_increase"):
        if key in ot and (key not in nt or nt[key] > ot[key]):
            out.append(f"RATCHET {where} {key} {ot[key]} -> {nt.get(key)}")
    if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
        out.append(f"RATCHET {where} min {ot['min']} -> {nt.get('min')}")
    for flag in _STRICTER_FLAGS:
        if ot.get(flag) and not nt.get(flag):
            out.append(f"RATCHET {where} dropped {flag}")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every metric and slice of base_spec must still exist and be at least
    as strict. A new eval-set version starts a new ratchet (and needs a new baseline anyway)."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out: list[str] = []
    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        out += _looser(f"metric {m['id']}", new_m.get(m["id"]), m)
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for sl in base_spec.get("slices") or []:
        out += _looser(f"slice {sl['name']}/{sl['metric']}", new_s.get((sl["name"], sl["metric"])), sl)
    for key in ("seeds", "eval_set", "labels"):
        if key in base_spec and spec.get(key) != base_spec[key]:
            out.append(f"RATCHET {key} changed on the same eval-set version")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                       # an empty slice proves nothing: never a pass
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "missing", "no items shared with baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if th.get("no_item_regression") and val is not None:
            # An item that passes on fewer seeds than on main is a regression even when another item
            # improved by the same amount and the mean stays put. Valid only while the A/A per-item
            # noise is 0 (MockLLM; docs/eval_card.md#v2) -- with a real LLM use a paired test instead.
            a, b = per_item(pr, mid), per_item(base, mid)
            worse = sorted(k for k in set(a) & set(b) if a[k] < b[k] - 1e-9)
            if worse:
                verdict = "fail"
                note = (note + " " if note else "") + f"worse: {','.join(worse[:4])}{'…' if len(worse) > 4 else ''}"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
