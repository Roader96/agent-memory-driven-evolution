#!/usr/bin/env python3
"""cap_enforcer.py — 活跃库硬上限（Ratchet active-library cap）

用户 2026-09-10 明确授权 cap=120。超过 cap 时，自动软禁用"最该退役"的技能
（全历史零加载 + ≥90天未改 + 非自建/非essential），按体积降序砍——
体积越大、描述注入的检索稀释成本越高，先砍收益最大。

安全：
- 只写 config.yaml skills.disabled（软禁用，可逆，不删文件）
- essential + roader/user 前缀永不动
- 每次动作落 state.cap_log，飞书周报列撤销命令
- 不自动恢复（避免库大小在 cap 边界抖动）；恢复由用户说 undo 或 approve.py
"""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state
from approve import set_disabled

CAP = 120
MIN_AGE_DAYS = 90
ESSENTIAL = {"hermes-agent"}
SELF_PREFIX = ("roader", "Roader", "user")


def enforce_cap(facts: list, cap: int = CAP, dry_run: bool = False) -> dict:
    """超过 cap → 自动软禁用候选，直到 active 计数 == cap。
    返回 {'cap','active_before','disabled_now':[...], 'active_after','skipped':n}"""
    installed = [x for x in facts if x.get("installed") and not x.get("disabled")]
    active_before = len(installed)
    over = active_before - cap
    if over <= 0:
        return {"cap": cap, "active_before": active_before, "disabled_now": [],
                "active_after": active_before, "reason": "未超 cap，不动"}

    # 候选：零加载 + 老 + 非保护；按体积降序（大的先砍）
    def protected(name):
        return name in ESSENTIAL or name.startswith(SELF_PREFIX)

    candidates = [
        x for x in installed
        if x["load_sessions"] == 0
        and (x.get("age_days") or 0) >= MIN_AGE_DAYS
        and not protected(x["name"])
        and (x.get("vault_mentions_90d") or 0) == 0  # 冷库有痕迹=知识被激活过，宁可误留不误杀
    ]
    candidates.sort(key=lambda x: -(x.get("size_bytes") or 0))

    # 冷库痕迹冲突名单：符合所有退役硬条件但冷库提过 → 不自动砍，交用户复核
    vault_conflicts = [
        x["name"] for x in installed
        if x["load_sessions"] == 0
        and (x.get("age_days") or 0) >= MIN_AGE_DAYS
        and not protected(x["name"])
        and (x.get("vault_mentions_90d") or 0) > 0
    ]

    victims = candidates[:over]
    skipped = over - len(victims)  # 候选不够砍（不能动保护名单/不够老的）

    disabled_now = []
    if not dry_run:
        for x in victims:
            try:
                set_disabled(x["name"], True)
                disabled_now.append({
                    "name": x["name"], "size_bytes": x.get("size_bytes"),
                    "age_days": x.get("age_days"),
                })
            except Exception as e:
                print(f"⚠️ 禁用 {x['name']} 失败: {e}", file=sys.stderr)
        if disabled_now:
            doc = state.load()
            doc.setdefault("cap_log", []).append({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "cap": cap, "active_before": active_before,
                "disabled": disabled_now,
            })
            state.save(doc)

    return {
        "cap": cap, "active_before": active_before,
        "disabled_now": disabled_now if not dry_run else
                       [{"name": x["name"], "size_bytes": x.get("size_bytes"),
                         "age_days": x.get("age_days")} for x in victims],
        "active_after": active_before - len(victims),
        "skipped": skipped,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import json, metrics
    args = [a for a in sys.argv[1:]]
    # python3 cap_enforcer.py --restore <name>  恢复 cap 自动禁用的技能
    if "--restore" in args:
        i = args.index("--restore")
        try:
            name = args[i + 1]
        except IndexError:
            print("用法: --restore <技能名>", file=sys.stderr); sys.exit(1)
        set_disabled(name, False)
        # 记日志
        doc = state.load()
        doc.setdefault("cap_log", []).append({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "restored": name,
        })
        state.save(doc)
        print(f"↩️ {name} 已恢复（从 skills.disabled 移除）")
        sys.exit(0)
    dry = "--apply" not in args
    r = enforce_cap(metrics.skill_facts(), dry_run=dry)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if dry:
        print("\n(dry-run；加 --apply 真执行软禁用)")
