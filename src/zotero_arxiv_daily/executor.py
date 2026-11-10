from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig, ListConfig
from .utils import glob_match
from .retriever import get_retriever_cls
from .protocol import CorpusPaper
import random
import re
from datetime import datetime
from pathlib import Path
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email
from openai import OpenAI
from tqdm import tqdm

# 日报中 [原文](https://arxiv.org/abs/2611.08483) / [PDF](https://arxiv.org/pdf/...) 链接里的论文编号（不含版本号）
_ARXIV_ID_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})")


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        self.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
        self.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        # timeout/max_retries 显式收紧, 避免端点异常时单请求挂 10 分钟
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url,
                                    timeout=60, max_retries=2)

    def _overview_research_context(self) -> str:
        """优先使用明确方向描述，否则从画像集合名和 arXiv 分类构造提示。"""
        overview_config = self.config.llm.get("paper_overview", {}) or {}
        if research_context := overview_config.get("research_context"):
            return str(research_context)

        context_parts = []
        if self.include_path_patterns:
            collections = [pattern.removesuffix("/**") for pattern in self.include_path_patterns]
            context_parts.append("Zotero research collections: " + ", ".join(collections))
        categories = self.config.source.arxiv.get("category")
        if categories:
            context_parts.append("Selected arXiv categories: " + ", ".join(str(value) for value in categories))
        return "; ".join(context_parts)

    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    
    def _load_known_paper_ids(self) -> set[str]:
        """从往期日报提取已推送 ID；跳过当天文件以支持重跑覆盖。"""
        md_dir = self.config.executor.get("markdown_out_dir", None)
        if not md_dir:
            return set()
        root = Path(md_dir)
        if not root.is_dir():
            return set()
        ids: set[str] = set()
        today = datetime.now().strftime("%Y-%m-%d")
        for md_file in root.glob("*.md"):
            # 当天日报可能正被重跑覆盖，不能把它自己的论文提前去重掉。
            if md_file.stem == today:
                continue
            ids.update(_ARXIV_ID_PATTERN.findall(md_file.read_text(encoding="utf-8", errors="ignore")))
        return ids

    def run(self):
        corpus = self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
        if len(corpus) == 0:
            logger.error(f"No zotero papers found. Please check your zotero settings:\n{self.config.zotero}")
            return
        known_ids = self._load_known_paper_ids()
        if known_ids:
            logger.info(f"Loaded {len(known_ids)} paper ids from previous digests for dedup")
        all_papers = []
        for source, retriever in self.retrievers.items():
            retriever.set_known_ids(known_ids)
            logger.info(f"Retrieving {source} papers...")
            papers = retriever.retrieve_papers()
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            # 有开源代码的论文加权(在截断前重排, 使其排名更靠前)
            code_bonus = self.config.executor.get("code_bonus", 1.15)
            if code_bonus and code_bonus != 1.0:
                for p in reranked_papers:
                    if p.code_url:
                        p.score = (p.score or 0.0) * code_bonus
                reranked_papers.sort(key=lambda x: x.score or 0.0, reverse=True)
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            logger.info("Generating paper overviews and affiliations...")
            # LLM 关闭或连续失败时保留原始摘要，避免生成未经核验的速览。
            llm_enabled = self.config.llm.get("enabled", True)
            research_context = self._overview_research_context()
            consecutive_failures = 0
            for p in tqdm(reranked_papers):
                if not llm_enabled:
                    continue
                overview = p.generate_overview(
                    self.openai_client,
                    self.config.llm,
                    research_context=research_context,
                )
                failed = overview is None
                if failed:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        logger.warning("LLM 连续 3 次失败, 本次运行降级为纯摘要模式(不再调用 LLM)")
                        llm_enabled = False
                        continue
                else:
                    consecutive_failures = 0
                    p.generate_affiliations(self.openai_client, self.config.llm)
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. No email will be sent.")
            return
        # Markdown 输出（VitePress 站点数据源），配置 executor.markdown_out_dir 即启用
        if md_dir := self.config.executor.get("markdown_out_dir", None):
            from .render_markdown import write_daily_markdown
            write_daily_markdown(reranked_papers, md_dir)
        # 邮件输出默认保留，executor.send_email=false 可关闭
        if self.config.executor.get("send_email", True):
            logger.info("Sending email...")
            email_content = render_email(reranked_papers)
            send_email(self.config, email_content)
            logger.info("Email sent successfully")
        else:
            logger.info("Email disabled (executor.send_email=false)")
