# HermesMemory 迁出 iCloud（2026-08-12 验证）

## 为什么 vault 会受 iCloud 卡死影响

`~/Documents` 被 iCloud Drive「桌面与文稿」接管，读写该目录要经过 `fileproviderd / bird`。
这两个守护进程死锁时（典型症状：连续开机 20+ 天 + 频繁睡眠唤醒），
`ls ~/Documents` 和 `ls ~/Library/Mobile Documents/` 全部 hang；`bird/fileproviderd` 0% CPU 躺平；
`killall bird fileproviderd` 无效。**文件在本地但路径卡死**。`~/.hermes` 不走 iCloud，所以 Hermes 本体不受影响。

## 决策

- 只迁 vault，不动整个 Documents、不关 iCloud。
- 目标：`~/HermesMemory`（非 iCloud、Finder 可见，不用隐藏目录）。
- 前提：vault 只在这台 Mac 用（无多端同步需求）。要多端同步就保持 iCloud，接受偶发卡死。

## 完整步骤（已验证）

1. **盘点 + 确认**：`du -sh ~/Documents/HermesMemory`、文件数；目标 `~/HermesMemory` 不存在；磁盘够；Obsidian 是否运行。
2. **先优雅退出 Obsidian**（避免复制中写文件 / 后面 obsidian.json 被覆盖）：
   ```bash
   osascript -e 'tell application "Obsidian" to quit'
   ```
3. **rsync 复制 + 校验**：
   ```bash
   rsync -a --delete "$HOME/Documents/HermesMemory/" "$HOME/HermesMemory/"
   find ~/Documents/HermesMemory -type f | wc -l   # 源
   find ~/HermesMemory -type f | wc -l             # 目标，必须一致
   rsync -a --delete --dry-run --itemize-changes "$SRC/" "$DST/"  # 空 = 一致
   ```
4. **脚本统一 `HERMES_VAULT`**（以后迁路径只改一处）：
   - bash：`VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"`
   - python：`VAULT = Path(os.environ.get("HERMES_VAULT", Path.home() / "HermesMemory"))`（缺 `import os` 要补）
   - 覆盖 `~/.hermes/scripts/` 下所有引用；跑 `bash -n *.sh` + `python3 -m py_compile *.py`
5. **cron prompt 更新**：用 `cron.jobs.update_job` 而不是手改 jobs.json：
   ```bash
   cd ~/.hermes/hermes-agent && venv/bin/python - <<'PY'
   from cron.jobs import list_jobs, update_job
   for job in list_jobs(include_disabled=True):
       p = job.get('prompt') or ''
       if 'Documents/HermesMemory' in p:
           update_job(job['id'], {'prompt': p.replace('~/Documents/HermesMemory','~/HermesMemory')})
   PY
   ```
   注意 prompt 里的模板可能写成 `$HOME/Documents/HermesMemory`（没有 `~/`），三种形式都要替换。
6. **Obsidian 配置**：改 `~/Library/Application Support/obsidian/obsidian.json` 里 `hermesmemory` vault 的 `path` → `/Users/<username>/HermesMemory`，保持 `open:true`（先备份再改）。改完 `open -a Obsidian` 重开。
7. **跑后处理**：`bash ~/.hermes/scripts/daily_summary.sh`（或直接 `vault_postprocess.py`）→ README/INDEX/TIMELINE 刷新。
8. **旧目录处置**：`mv ~/Documents/HermesMemory ~/.hermes/backups/HermesMemory-<ts>` 移出 Documents（不删，留回滚）；验证 `~/Documents/HermesMemory` 已不存在、备份文件数 = 新 vault 文件数。
9. **最终验证**：脚本 / cron / 当前 skill 目录无 `Documents/HermesMemory` 残留（.archive / .curator_backups / *.bak 可忽略）；`obsidian.json` 指向新路径；`hermes cron status` 正常。

## 注意

- 复制后旧 vault 的 md 内容里可能还残留旧绝对路径（历史 daily「今日新增」段），对新 vault 全量 replace 一遍再跑 postprocess。
- Smart Connections 首次打开新路径会重建本地索引（无需联网）。
- 批量 sed/replace 要防“二次嵌套”：先搜 `Path.home() / "Documents" / "HermesMemory"` 一次性替换成 env 形式，别对已含 `os.environ.get("HERMES_VAULT"` 的文本再套一层。
