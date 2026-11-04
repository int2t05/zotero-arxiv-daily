# -*- coding: utf-8 -*-
"""每日精选导出为 Markdown（供 VitePress 站点渲染），替代邮件输出"""
import re
from datetime import datetime
from loguru import logger


def render_markdown(papers) -> str:
    """把排序后的 Paper 列表渲染成单日 Markdown"""
    lines = [
        f"# 每日 arXiv 精选 · {datetime.now():%Y-%m-%d}",
        "",
        f"> 共 {len(papers)} 篇，按与你 Zotero 兴趣画像的相似度排序；TL;DR 由 LLM 生成，仅供快速筛选。",
        "",
    ]
    for i, p in enumerate(papers, 1):
        score = f"{p.score:.3f}" if p.score is not None else "-"
        authors = ", ".join(p.authors[:6]) + (" et al." if len(p.authors) > 6 else "")
        aff = f" ｜ { '; '.join(p.affiliations[:3])}" if p.affiliations else ""
        lines.append(f"## {i}. {p.title}")
        lines.append("")
        lines.append(f"`相似度 {score}` ｜ {authors}{aff}")
        lines.append("")
        if p.tldr:
            tldr = re.sub(r"^\*{0,2}\s*TL;?DR\s*[:：]?\*{0,2}\s*", "", p.tldr.strip())
            lines.append(f"**TL;DR**：{tldr}")
            lines.append("")
        snippet = (p.abstract or "").strip()
        if snippet:
            lines.append(f"> {snippet[:500]}{'…' if len(snippet) > 500 else ''}")
            lines.append("")
        link = f"[原文]({p.url})"
        if p.pdf_url:
            link += f" ｜ [PDF]({p.pdf_url})"
        if p.code_url:
            link += f" ｜ [代码]({p.code_url})"
        lines.append(link)
        lines.append("")
    return "\n".join(lines)


def write_daily_markdown(papers, out_dir: str) -> str:
    """写入 <out_dir>/YYYY-MM-DD.md，返回文件路径"""
    from pathlib import Path
    path = Path(out_dir) / f"{datetime.now():%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(papers), encoding="utf-8")
    logger.info(f"Markdown digest written: {path}")
    return str(path)
