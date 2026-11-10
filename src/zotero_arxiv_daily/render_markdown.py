# -*- coding: utf-8 -*-
"""将结构化论文速览导出为 Markdown，供 VitePress 站点使用。"""
from datetime import datetime
from pathlib import Path
import re
from loguru import logger
from .protocol import Paper


def _one_line(value: str) -> str:
    """将速览字段压成单行，避免模型换行破坏日报结构。"""
    return " ".join(value.split())


def _escape_markdown(value: str) -> str:
    """转义用户和模型文本中的 Markdown 符号，保持卡片结构稳定。"""
    return re.sub(r"([\\`*_{}\[\]()<>])", r"\\\1", value)


def _unescape_markdown(value: str) -> str:
    """读取本程序写出的 Markdown 时还原标题和元数据文本。"""
    return re.sub(r"\\([\\`*_{}\[\]()<>])", r"\1", value)


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
        lines.append(f"## {i}. {_escape_markdown(p.title)}")
        lines.append("")
        metadata = _escape_markdown(authors)
        if p.affiliations:
            metadata += f" ｜ {_escape_markdown('; '.join(p.affiliations[:3]))}"
        lines.append(f"`相似度 {score}` ｜ {metadata}")
        lines.append("")
        if p.overview:
            overview_lines = [
                f"**研究问题**：{_escape_markdown(_one_line(p.overview.research_problem))}",
                f"**方法**：{_escape_markdown(_one_line(p.overview.method))}",
                f"**结果与证据**：{_escape_markdown(_one_line(p.overview.evidence))}",
                f"**方向关联**：{_escape_markdown(_one_line(p.overview.interest_fit))}",
            ]
            if p.code_url:
                note = p.overview.reproduction_notes or "论文文本未提供复现细节；需打开代码仓库核对。"
                overview_lines.append(f"**代码复现线索**：{_escape_markdown(_one_line(note))}")
            for line in overview_lines:
                lines.extend([line, ""])
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


def load_daily_papers(markdown_path: str | Path) -> list[Paper]:
    """从既有日报读取论文、摘要和链接，供当天重新生成速览。"""
    content = Path(markdown_path).read_text(encoding="utf-8")
    blocks = re.findall(
        r"(?ms)^##\s+\d+\.\s+(?P<title>.+?)\s*\n(?P<body>.*?)(?=^##\s+\d+\.\s+|\Z)",
        content,
    )
    papers: list[Paper] = []
    for title, body in blocks:
        meta_line = next((line for line in body.splitlines() if "相似度" in line), "")
        score_match = re.search(r"`相似度\s+([^`]+)`", meta_line)
        try:
            score = float(score_match.group(1)) if score_match else None
        except ValueError:
            score = None

        meta_parts = [part.strip() for part in meta_line.split("｜")]
        authors_text = meta_parts[1] if len(meta_parts) > 1 else ""
        authors = [
            _unescape_markdown(name.strip())
            for name in authors_text.split(",")
            if name.strip()
        ]
        if authors and authors[-1].lower() == "et al.":
            authors.pop()
        affiliations_text = "｜".join(meta_parts[2:]) if len(meta_parts) > 2 else ""
        affiliations = [
            _unescape_markdown(name.strip())
            for name in affiliations_text.split(";")
            if name.strip()
        ]

        links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", body)
        url = next((value for label, value in links if label == "原文"), None)
        if not url:
            continue
        pdf_url = next((value for label, value in links if label == "PDF"), None)
        code_url = next((value for label, value in links if "代码" in label), None)

        summary_match = re.search(
            r"<summary>原始摘要</summary>(.*?)</details>", body, flags=re.DOTALL
        )
        abstract_source = summary_match.group(1) if summary_match else body.split("[原文]", 1)[0]
        abstract = "\n".join(
            line.lstrip()[1:].lstrip()
            for line in abstract_source.splitlines()
            if line.lstrip().startswith(">")
        ).strip()
        papers.append(
            Paper(
                source="arxiv",
                title=_unescape_markdown(title.strip()),
                authors=authors,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                affiliations=affiliations or None,
                score=score,
                code_url=code_url,
            )
        )
    if not papers:
        raise ValueError(f"No papers could be read from daily digest: {markdown_path}")
    return papers
