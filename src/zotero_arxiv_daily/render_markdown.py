# -*- coding: utf-8 -*-
"""将结构化论文速览导出为 Markdown，供 VitePress 站点使用。"""
from datetime import datetime
from loguru import logger


def _one_line(value: str) -> str:
    """将速览字段压成单行，避免模型换行破坏日报结构。"""
    return " ".join(value.split())


def render_markdown(papers) -> str:
    """把排序后的论文渲染成便于初筛的单日 Markdown。"""
    lines = [
        f"# 每日 arXiv 精选 · {datetime.now():%Y-%m-%d}",
        "",
        f"> 共 {len(papers)} 篇，按 Zotero 兴趣画像相似度排序。速览依据论文摘要生成；代码线索未经运行验证。",
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
        if p.overview:
            lines.extend([
                f"**研究问题**：{_one_line(p.overview.research_problem)}",
                f"**方法**：{_one_line(p.overview.method)}",
                f"**结果与证据**：{_one_line(p.overview.evidence)}",
                f"**方向关联**：{_one_line(p.overview.interest_fit)}",
            ])
            if p.code_url:
                note = p.overview.reproduction_notes or "论文文本未提供复现细节；需打开代码仓库核对。"
                lines.append(f"**代码复现线索**：{_one_line(note)}")
            lines.append("")
        else:
            lines.extend(["**论文速览**：暂未生成，请参考原始摘要和原文。", ""])
        snippet = (p.abstract or "").strip()
        if snippet:
            lines.extend(["<details>", "<summary>原始摘要</summary>", ""])
            lines.extend(f"> {line}" for line in snippet.splitlines())
            lines.extend(["", "</details>", ""])
        link = f"[原文]({p.url})"
        if p.pdf_url:
            link += f" ｜ [PDF]({p.pdf_url})"
        if p.code_url:
            link += f" ｜ [代码线索（未验证）]({p.code_url})"
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
