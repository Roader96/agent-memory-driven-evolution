#!/usr/bin/env python3
"""
增强版每日总结生成器
不只统计数字，还读归档正文提炼实质内容
"""

import os
import sys
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "skill_evolution"))
import paths
from datetime import datetime

VAULT = paths.VAULT
DATE = os.environ.get('DATE_OVERRIDE', datetime.now().strftime('%Y-%m-%d'))
TIME = os.environ.get('TIME_OVERRIDE', datetime.now().strftime('%H:%M'))

def read_archive_content(file_path: Path) -> dict:
    """读取归档文件，提取标题和核心内容"""
    try:
        content = file_path.read_text(encoding='utf-8')

        # 提取标题（第一个 # 开头）
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else file_path.stem

        # 优先提取"## 摘要"段落
        summary_match = re.search(r'^##\s+摘要\s*\n(.+?)(?=^##|\Z)', content, re.MULTILINE | re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
        else:
            # 没有摘要段落，提取"## 完成内容"或"## 完成工作"
            work_match = re.search(r'^##\s+(完成内容|完成工作)\s*\n(.+?)(?=^##|\Z)', content, re.MULTILINE | re.DOTALL)
            if work_match:
                summary = work_match.group(2).strip()[:300] + ('...' if len(work_match.group(2)) > 300 else '')
            else:
                # 兜底：去掉归档头，取前300字符
                lines = content.split('\n')
                body_lines = []
                skip_header = True
                for line in lines:
                    if skip_header and (line.startswith('>') or line.startswith('#') or not line.strip()):
                        continue
                    skip_header = False
                    body_lines.append(line)
                body = '\n'.join(body_lines).strip()
                summary = body[:300] + ('...' if len(body) > 300 else '')

        # 提取产出物（如果有）
        deliverables_match = re.search(r'^##\s+产出物\s*\n(.+?)(?=^##|\Z)', content, re.MULTILINE | re.DOTALL)
        deliverables = deliverables_match.group(1).strip() if deliverables_match else None

        # 提取关键段落（## 开头的部分）
        sections = re.findall(r'^##\s+(.+)$', content, re.MULTILINE)

        return {
            'title': title,
            'summary': summary,
            'deliverables': deliverables,
            'sections': sections,
            'path': str(file_path.relative_to(VAULT)),
            'category': file_path.parent.name
        }
    except Exception as e:
        return {
            'title': file_path.stem,
            'summary': f'(读取失败: {e})',
            'deliverables': None,
            'sections': [],
            'path': str(file_path.relative_to(VAULT)),
            'category': file_path.parent.name
        }

def generate_daily_summary():
    """生成有实质内容的每日总结"""

    # 统计数字
    total = len(list(VAULT.rglob('*.md')))
    projects = len([d for d in (VAULT / 'projects').iterdir() if d.is_dir()]) if (VAULT / 'projects').exists() else 0
    prefs = len(list((VAULT / 'preferences').glob('*.md'))) if (VAULT / 'preferences').exists() else 0
    incidents = len(list((VAULT / 'incidents').glob('*.md'))) if (VAULT / 'incidents').exists() else 0

    errors_file = VAULT / '.checkpoints' / 'errors.json'
    errors = len(json.loads(errors_file.read_text())) if errors_file.exists() else 0

    # 找今日新增的文件
    today_files = []
    for pattern in [f'{DATE}-*.md', f'*{DATE}*.md']:
        today_files.extend(VAULT.rglob(pattern))

    # 去重并排除 .obsidian 和 .checkpoints
    today_files = list(set([
        f for f in today_files
        if '.obsidian' not in str(f) and '.checkpoints' not in str(f)
    ]))

    # 读取每个文件的内容
    archives = [read_archive_content(f) for f in sorted(today_files)]

    # 按分类分组
    by_category = {}
    for arch in archives:
        cat = arch['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(arch)

    # 生成总结
    output = f"""# {DATE} 每日总结

> **生成时间**：{TIME}
> **类型**：cron 自动生成（增强版）

## 📊 今日归档统计

- 总文件：{total}
- 项目：{projects}
- 偏好：{prefs}
- 踩坑：{incidents}
- 错误记录：{errors}
- 今日新增：{len(archives)} 条

## 📝 今日工作内容

"""

    if not archives:
        output += "_今日无新增归档_\n"
    else:
        for category, items in sorted(by_category.items()):
            output += f"\n### {category} ({len(items)} 条)\n\n"
            for item in items:
                output += f"**{item['title']}**\n\n"
                if item['sections']:
                    output += f"核心内容：{' / '.join(item['sections'][:3])}\n\n"
                output += f"{item['summary']}\n\n"
                output += f"📂 `{item['path']}`\n\n"
                output += "---\n\n"

    output += "\n---\n_由 cron 每日 23:50 自动生成（增强版，含正文提炼）_\n"

    return output

if __name__ == '__main__':
    summary = generate_daily_summary()

    # 写入文件
    daily_file = VAULT / 'daily' / f'{DATE}-每日总结.md'
    daily_file.parent.mkdir(parents=True, exist_ok=True)

    if daily_file.exists():
        print(f"⏭️ 今日 daily 已存在，跳过: {daily_file}")
    else:
        daily_file.write_text(summary, encoding='utf-8')
        print(f"✅ 写 daily 总结: {daily_file}")
