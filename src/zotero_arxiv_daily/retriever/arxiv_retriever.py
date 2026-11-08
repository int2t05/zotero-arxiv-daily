from .base import BaseRetriever, register_retriever
import arxiv
from arxiv import Result as ArxivResult
from ..protocol import Paper
from ..utils import extract_code_url, extract_markdown_from_pdf, extract_tex_code_from_tar
import calendar
from datetime import datetime, timezone
import multiprocessing
import os
from queue import Empty
import re
from tempfile import TemporaryDirectory
import time
from time import sleep
from typing import Any, Callable, TypeVar
from loguru import logger
import requests
import feedparser
from tqdm import tqdm

T = TypeVar("T")

DOWNLOAD_TIMEOUT = (10, 60)
PDF_EXTRACT_TIMEOUT = 180
TAR_EXTRACT_TIMEOUT = 180

HTML_TAG_PATTERN = re.compile(
    r"</?(?:p|a|span|div|b|i|strong|em|br|hr|h[1-6]|ul|ol|li|sub|sup|table|tr|td|th)\b(?:\s+[^>]*)?/?>",
    flags=re.IGNORECASE,
)
ARXIV_HEADER_PATTERN = re.compile(
    r"^(?:arxiv:\s*\S+(?:\s+\[[^\]]*\])?)?\s*(?:announce\s+type:\s*[\w-]+)?\s*(?:abstract:\s*)?",
    flags=re.IGNORECASE,
)
# 从各来源的论文标识中截取 arXiv 编号（含版本号），兼容 RSS 的 oai: 前缀与 API 的 abs 链接两种形态
ARXIV_ID_IN_URL_PATTERN = re.compile(r"abs/(\d{4}\.\d{4,5}(?:v\d+)?)$")


def _normalize_paper_id(raw_id: str) -> str:
    """把 oai:arXiv.org:2611.08483v1 / http://arxiv.org/abs/2611.08483v1 统一成 2611.08483v1"""
    if raw_id.startswith("oai:arXiv.org:"):
        return raw_id.removeprefix("oai:arXiv.org:")
    if match := ARXIV_ID_IN_URL_PATTERN.search(raw_id):
        return match.group(1)
    return raw_id


def _paper_key(paper_id: str) -> str:
    """去重键：剥离版本号，v1/v2 视为同一篇"""
    return re.sub(r"v\d+$", "", paper_id)


def _download_file(url: str, path: str) -> None:
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with open(path, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def _run_in_subprocess(
    result_queue: Any,
    func: Callable[..., T | None],
    args: tuple[Any, ...],
) -> None:
    try:
        result_queue.put(("ok", func(*args)))
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_with_hard_timeout(
    func: Callable[..., T | None],
    args: tuple[Any, ...],
    *,
    timeout: float,
    operation: str,
    paper_title: str,
) -> T | None:
    start_methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context("fork" if "fork" in start_methods else start_methods[0])
    result_queue = context.Queue()
    process = context.Process(target=_run_in_subprocess, args=(result_queue, func, args))
    process.start()

    try:
        status, payload = result_queue.get(timeout=timeout)
    except Empty:
        if process.is_alive():
            process.kill()
        process.join(5)
        result_queue.close()
        result_queue.join_thread()
        logger.warning(f"{operation} timed out for {paper_title} after {timeout} seconds")
        return None

    process.join(5)
    result_queue.close()
    result_queue.join_thread()

    if status == "ok":
        return payload

    logger.warning(f"{operation} failed for {paper_title}: {payload}")
    return None


def _extract_text_from_pdf_worker(pdf_url: str) -> str:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.pdf")
        _download_file(pdf_url, path)
        return extract_markdown_from_pdf(path)


def _extract_text_from_html_worker(html_url: str) -> str | None:
    import trafilatura

    downloaded = trafilatura.fetch_url(html_url)
    if downloaded is None:
        raise ValueError(f"Failed to download HTML from {html_url}")
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if not text:
        raise ValueError(f"No text extracted from {html_url}")
    return text


def _extract_text_from_tar_worker(source_url: str, paper_id: str, paper_title: str | None = None) -> str | None:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.tar.gz")
        _download_file(source_url, path)
        file_contents = extract_tex_code_from_tar(path, paper_id, paper_title=paper_title)
        if not file_contents or "all" not in file_contents:
            raise ValueError("Main tex file not found.")
        return file_contents["all"]


def _clean_abstract(summary_raw: str) -> str:
    cleaned = HTML_TAG_PATTERN.sub(" ", summary_raw).strip()
    cleaned = ARXIV_HEADER_PATTERN.sub("", cleaned).strip()
    cleaned = re.sub(r"^abstract:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return " ".join(cleaned.split())


def _extract_authors(entry: Any) -> list[ArxivResult.Author]:
    author_str = getattr(entry, "author", "") or ""
    if not author_str and hasattr(entry, "authors") and entry.authors:
        author_str = ", ".join(
            a.get("name", "") if isinstance(a, dict) else getattr(a, "name", str(a))
            for a in entry.authors
        )
    author_names = [a.strip() for a in author_str.split(",") if a.strip()]
    if not author_names:
        author_names = ["Unknown"]
    return [ArxivResult.Author(name=name) for name in author_names]


def _parse_entry_time(struct_time: Any) -> datetime:
    if struct_time:
        try:
            return datetime.fromtimestamp(calendar.timegm(struct_time), tz=timezone.utc)
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _entry_to_arxiv_result(entry: Any) -> ArxivResult:
    raw_id = getattr(entry, "id", "") or ""
    paper_id = _normalize_paper_id(raw_id)
    title_raw = getattr(entry, "title", "") or ""
    title = " ".join(title_raw.split())

    authors = _extract_authors(entry)
    summary = _clean_abstract(getattr(entry, "summary", "") or "")

    link = getattr(entry, "link", "") or f"https://arxiv.org/abs/{paper_id}"
    pdf_url = f"https://arxiv.org/pdf/{paper_id}"
    source_url = f"https://arxiv.org/src/{paper_id}"

    tags = getattr(entry, "tags", []) or []
    categories = [
        t.get("term") for t in tags
        if isinstance(t, dict) and t.get("term")
    ]
    # Prefer Atom's authoritative arxiv:primary_category field, with fallback to first category
    primary_category = ""
    arxiv_primary = getattr(entry, "arxiv_primary_category", None)
    if isinstance(arxiv_primary, dict):
        primary_category = arxiv_primary.get("term", "") or ""
    elif hasattr(arxiv_primary, "term"):
        primary_category = getattr(arxiv_primary, "term", "") or ""
    elif isinstance(arxiv_primary, str):
        primary_category = arxiv_primary

    if not primary_category and categories:
        primary_category = categories[0]

    published = _parse_entry_time(getattr(entry, "published_parsed", None))
    updated = _parse_entry_time(getattr(entry, "updated_parsed", None))
    comment = getattr(entry, "arxiv_comment", "") or ""
    journal_ref = getattr(entry, "arxiv_journal_reference", "") or getattr(entry, "arxiv_journal_ref", "") or ""
    doi = getattr(entry, "arxiv_doi", "") or ""

    links = [
        ArxivResult.Link(href=link, rel="alternate"),
        ArxivResult.Link(href=pdf_url, title="pdf", rel="related"),
        ArxivResult.Link(href=source_url, title="source", rel="related"),
    ]

    return ArxivResult(
        entry_id=link,
        updated=updated,
        published=published,
        title=title,
        authors=authors,
        summary=summary,
        comment=comment,
        journal_ref=journal_ref,
        doi=doi,
        primary_category=primary_category,
        categories=categories,
        links=links,
    )


@register_retriever("arxiv")
class ArxivRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        if self.config.source.arxiv.category is None:
            raise ValueError("category must be specified for arxiv.")

    def _retrieve_raw_papers(self) -> list[ArxivResult]:
        query = '+'.join(self.config.source.arxiv.category)
        include_cross_list = self.config.source.arxiv.get("include_cross_list", False)
        rss_url = f"https://rss.arxiv.org/atom/{query}"

        # Get latest papers from arxiv RSS feed with retry
        retry_num = 5
        delay_time = 5
        feed = None
        for attempt in range(retry_num):
            feed = feedparser.parse(rss_url)
            status = getattr(feed, "status", None)
            bozo = getattr(feed, "bozo", False)
            bozo_exc = getattr(feed, "bozo_exception", None)
            feed_meta = getattr(feed, "feed", None)
            title = getattr(feed_meta, "title", "") if feed_meta else ""

            if title and "Feed error for query" in title:
                raise Exception(f"Invalid ARXIV_QUERY: {query}.")

            # Validate HTTP status and parser state before accepting the feed
            is_http_error = status is not None and status >= 400
            is_parser_error = bool(bozo and not getattr(feed, "entries", None))
            has_valid_feed = bool(feed_meta and title and not is_http_error and not is_parser_error)

            if has_valid_feed:
                break

            error_msg = f"status={status}" if status is not None else f"bozo_exception={bozo_exc}"
            if attempt < retry_num - 1:
                logger.warning(
                    f"Failed to fetch valid arxiv RSS feed ({error_msg}), retrying in {delay_time}s..."
                )
                sleep(delay_time)
        else:
            status = getattr(feed, "status", None)
            bozo_exc = getattr(feed, "bozo_exception", None)
            raise RuntimeError(
                f"Failed to fetch valid arxiv RSS feed from {rss_url} after {retry_num} attempts "
                f"(status={status}, bozo_exception={bozo_exc})"
            )

        allowed_announce_types = {"new", "cross"} if include_cross_list else {"new"}
        target_entries = [
            i for i in feed.entries
            if i.get("arxiv_announce_type", "new") in allowed_announce_types
        ]
        if self.config.executor.debug:
            target_entries = target_entries[:10]

        seen_paper_ids = set()
        raw_papers = []
        for entry in target_entries:
            raw_id = getattr(entry, "id", "") or ""
            paper_id = _normalize_paper_id(raw_id)
            if paper_id and paper_id in seen_paper_ids:
                continue
            if paper_id:
                seen_paper_ids.add(paper_id)
            raw_papers.append(_entry_to_arxiv_result(entry))

        # 跨日去重：历史日报已推送过的论文不再进入候选（避免 RSS 重复公告时重发）
        if self.known_ids:
            raw_papers = [
                p for p in raw_papers
                if _paper_key(_normalize_paper_id(p.entry_id)) not in self.known_ids
            ]

        if raw_papers:
            return raw_papers

        # RSS 只保留最近一次公告，公告空窗日（arXiv 现为周一至周四晚公告，周五起
        # RSS 变空直到下一次公告）检索为 0 篇。此时回退 arXiv API 做"积压排空"：
        # 取最新一批公告中历史日报尚未推送过的论文补位，保证每日产出连续且不重复
        return self._retrieve_via_api()

    # API 回退不做公告类型过滤（API 无 announce type），语义等同于 include_cross_list=true
    def _retrieve_via_api(self) -> list[ArxivResult]:
        categories = list(self.config.source.arxiv.category)
        max_results = int(self.config.source.arxiv.get("fallback_max_results", 300))
        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        # 注：不用 submittedDate 区间语法做服务端过滤——arXiv API 对该语法返回恒 0
        # （2026-11-08 实测），且空窗日本就没有新公告，日历窗口无意义；
        # 按提交时间倒序取最新 N 条，靠 known_ids 去重出"未推送过"的积压论文
        params = {
            "search_query": cat_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        entries: list[Any] = []
        for attempt in range(3):
            try:
                response = requests.get("https://export.arxiv.org/api/query", params=params, timeout=30)
                response.raise_for_status()
                entries = list(feedparser.parse(response.content).entries)
                break
            except Exception as exc:
                logger.warning(f"arXiv API fallback request failed (attempt {attempt + 1}/3): {exc}")
                if attempt < 2:
                    sleep(5)
        else:
            return []

        papers = []
        seen_paper_ids = set()
        for entry in entries:
            paper_id = _normalize_paper_id(getattr(entry, "id", "") or "")
            if not paper_id or paper_id in seen_paper_ids:
                continue
            seen_paper_ids.add(paper_id)
            if _paper_key(paper_id) in self.known_ids:
                continue
            papers.append(_entry_to_arxiv_result(entry))

        logger.info(f"arXiv API fallback (backlog drain): {len(papers)} not-yet-shown papers")
        return papers

    def convert_to_paper(self, raw_paper: ArxivResult) -> Paper:
        title = raw_paper.title
        authors = [a.name for a in raw_paper.authors]
        abstract = raw_paper.summary
        pdf_url = raw_paper.pdf_url
        full_text = extract_text_from_tar(raw_paper)
        if full_text is None:
            full_text = extract_text_from_html(raw_paper)
        if full_text is None:
            full_text = extract_text_from_pdf(raw_paper)
        # 代码链接采集: 摘要 > arXiv comment > 正文(LaTeX 源码)
        code_url = (extract_code_url(abstract)
                    or extract_code_url(raw_paper.comment or "")
                    or extract_code_url(full_text or ""))
        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=raw_paper.entry_id,
            pdf_url=pdf_url,
            full_text=full_text,
            code_url=code_url,
        )


def extract_text_from_html(paper: ArxivResult) -> str | None:
    html_url = paper.entry_id.replace("/abs/", "/html/")
    try:
        return _extract_text_from_html_worker(html_url)
    except Exception as exc:
        logger.warning(f"HTML extraction failed for {paper.title}: {exc}")
        return None


def extract_text_from_pdf(paper: ArxivResult) -> str | None:
    if paper.pdf_url is None:
        logger.warning(f"No PDF URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_pdf_worker,
        (paper.pdf_url,),
        timeout=PDF_EXTRACT_TIMEOUT,
        operation="PDF extraction",
        paper_title=paper.title,
    )


def extract_text_from_tar(paper: ArxivResult) -> str | None:
    source_url = paper.source_url()
    if source_url is None:
        logger.warning(f"No source URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_tar_worker,
        (source_url, paper.entry_id, paper.title),
        timeout=TAR_EXTRACT_TIMEOUT,
        operation="Tar extraction",
        paper_title=paper.title,
    )
