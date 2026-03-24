from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from openai import OpenAI

from skill.tools.search_literature_tools import search_arxiv_papers
from workspace.literature.store import (
    build_paper_id,
    ensure_literature_layout,
    find_duplicate_paper_id,
    now_iso,
    read_state,
    update_state,
    upsert_paper,
)
from memory.memory_store import now_dt, parse_iso

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"
WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9\\-]{1,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "via",
    "with",
    "using",
    "use",
    "based",
    "toward",
    "towards",
}
GENERIC_QUERY_TERMS = {
    "ai",
    "ml",
    "llm",
    "nlp",
    "agent",
    "agents",
    "model",
    "models",
    "system",
    "systems",
}
MIN_RELEVANCE_SCORE = 70
DEFAULT_QUERY_POOL_SIZE = 9
DEFAULT_QUERY_PLAN_REFRESH_SECONDS = 86400
DEFAULT_MAX_ANALYZED_PAPERS_PER_RUN = 6


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("模型返回为空")

    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回中没有合法 JSON 对象")

    return json.loads(clean[start : end + 1])


def _extract_completion_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        status = getattr(response, "status", None)
        msg = getattr(response, "msg", None)
        raise ValueError(f"模型返回无有效 choices，status={status}, msg={msg}")

    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, str):
                fragments.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    fragments.append(text)
        return "".join(fragments)
    if content is None:
        raise ValueError("模型返回 content 为空")
    return str(content)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _extract_keywords(*values: str) -> list[str]:
    keywords: list[str] = []
    for value in values:
        for match in WORD_PATTERN.findall(_normalize_text(value)):
            if len(match) < 3 or match in STOPWORDS:
                continue
            keywords.append(match)
    return list(dict.fromkeys(keywords))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _normalize_text(str(value))
    return text in {"1", "true", "yes", "y"}


def _to_relevance_score(value: Any) -> int:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= score <= 1.0:
        score *= 100.0
    return max(0, min(100, int(round(score))))


class LiteratureService:
    def __init__(self) -> None:
        ensure_literature_layout()
        self._config = _load_config()
        self._client = OpenAI(
            api_key=self._config["word_api_key"],
            base_url=self._config["word_base_url"],
        )

    def run_task(self, *, category: str, topic: str, **options: Any) -> dict[str, Any]:
        clean_category = str(category or "").strip()
        clean_topic = str(topic or "").strip()
        if not clean_category or not clean_topic:
            return {
                "status": "error",
                "summary": "",
                "error": "category 和 topic 不能为空",
                "new_count": 0,
                "search_queries": [],
            }

        state = read_state()
        query_count = max(1, int(options.get("search_queries_per_topic") or state.get("default_search_queries_per_topic", 3) or 3))
        query_pool_size = max(
            query_count,
            int(options.get("query_pool_size") or state.get("default_query_pool_size", DEFAULT_QUERY_POOL_SIZE) or DEFAULT_QUERY_POOL_SIZE),
        )
        query_plan_refresh_seconds = max(
            300,
            int(
                options.get("query_plan_refresh_seconds")
                or state.get("default_query_plan_refresh_seconds", DEFAULT_QUERY_PLAN_REFRESH_SECONDS)
                or DEFAULT_QUERY_PLAN_REFRESH_SECONDS
            ),
        )
        max_results = max(1, int(options.get("max_results") or state.get("default_max_results_per_query", 30) or 30))
        max_new_papers = max(1, int(options.get("max_new_papers_per_run") or state.get("default_max_new_papers_per_run", 3) or 3))
        max_analyzed_papers = max(
            max_new_papers,
            int(
                options.get("max_analyzed_papers_per_run")
                or state.get("default_max_analyzed_papers_per_run", DEFAULT_MAX_ANALYZED_PAPERS_PER_RUN)
                or DEFAULT_MAX_ANALYZED_PAPERS_PER_RUN
            ),
        )
        manual_query = str(options.get("query", "")).strip()

        try:
            search_queries = self._next_search_queries(
                topic=clean_topic,
                category=clean_category,
                queries_per_run=query_count,
                query_pool_size=query_pool_size,
                query_plan_refresh_seconds=query_plan_refresh_seconds,
                manual_query=manual_query,
            )
            print(f"[literature] 搜索文献: category={clean_category}, topic={clean_topic}, queries={search_queries}")
            candidates = self._search_new_candidates(search_queries, max_results=max_results)
            filtered_candidates = self._rank_candidates(
                candidates,
                topic=clean_topic,
                category=clean_category,
                search_queries=search_queries,
                limit=max_analyzed_papers,
            )
            print(
                f"[literature] 候选论文: raw={len(candidates)}, ranked={len(filtered_candidates)}, "
                f"topic={clean_topic}"
            )

            analysis_candidates = list(filtered_candidates[:max_analyzed_papers])
            screening_map: dict[str, dict[str, Any]] = {}
            if analysis_candidates:
                print(f"[literature] 批量筛选候选: count={len(analysis_candidates)}")
                screening_map = self._screen_papers_batch(
                    analysis_candidates,
                    topic=clean_topic,
                    category=clean_category,
                )

            relevant_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for index, paper in enumerate(analysis_candidates, start=1):
                candidate_id = self._candidate_id(paper, index)
                screening = screening_map.get(candidate_id)
                if screening is None:
                    print(f"[literature] 批量筛选缺失，回退单篇分析: {str(paper.get('title', '')).strip()[:100]}")
                    screening = self._analyze_paper(
                        paper,
                        topic=clean_topic,
                        category=clean_category,
                    )
                print(
                    f"[literature] 筛选结果 {index}/{len(analysis_candidates)}: "
                    f"score={int(screening.get('relevance_score', 0) or 0)}, "
                    f"relevant={bool(screening.get('is_relevant', False))}, "
                    f"title={str(paper.get('title', '')).strip()[:100]}"
                )
                if screening["is_relevant"]:
                    relevant_candidates.append((paper, screening))

            relevant_candidates.sort(
                key=lambda item: (
                    int(item[1].get("relevance_score", 0) or 0),
                    str(item[0].get("publish_time", "")),
                    str(item[0].get("title", "")),
                ),
                reverse=True,
            )
            summary_candidates = relevant_candidates[:max_new_papers]
            summary_map: dict[str, dict[str, Any]] = {}
            if summary_candidates:
                print(f"[literature] 批量整理入库候选: count={len(summary_candidates)}")
                summary_map = self._summarize_papers_batch(
                    [paper for paper, _ in summary_candidates],
                    topic=clean_topic,
                    category=clean_category,
                )

            new_count = 0
            new_titles: list[str] = []
            analyzed_count = len(analysis_candidates)
            for index, (paper, screening) in enumerate(summary_candidates, start=1):
                candidate_id = self._candidate_id(paper, index)
                summary_result = summary_map.get(candidate_id)
                if summary_result is None:
                    print(f"[literature] 批量整理缺失，回退单篇分析: {str(paper.get('title', '')).strip()[:100]}")
                    analysis = self._analyze_paper(
                        paper,
                        topic=clean_topic,
                        category=clean_category,
                    )
                else:
                    analysis = {
                        "is_relevant": screening["is_relevant"],
                        "relevance_score": screening["relevance_score"],
                        "relevance_reason": screening["relevance_reason"],
                        "title_zh": summary_result["title_zh"],
                        "summary_zh": summary_result["summary_zh"],
                        "key_points_zh": summary_result["key_points_zh"],
                    }
                print(
                    f"[literature] 整理结果 {index}/{len(summary_candidates)}: "
                    f"score={int(analysis.get('relevance_score', 0) or 0)}, "
                    f"title={str(paper.get('title', '')).strip()[:100]}"
                )

                record = {
                    "id": build_paper_id(
                        str(paper.get("arxiv_id", "")).strip(),
                        str(paper.get("pdf_link", "")).strip(),
                        str(paper.get("title", "")).strip(),
                    ),
                    "source": "arxiv",
                    "topic": clean_topic,
                    "topics": [clean_topic],
                    "query": str(paper.get("matched_query", "")).strip(),
                    "queries": [str(paper.get("matched_query", "")).strip()],
                    "categories": [clean_category],
                    "arxiv_id": str(paper.get("arxiv_id", "")).strip(),
                    "title_en": str(paper.get("title", "")).strip(),
                    "title_zh": analysis["title_zh"],
                    "pdf_url": str(paper.get("pdf_link", "")).strip(),
                    "summary_en": str(paper.get("summary", "")).strip(),
                    "summary_zh": analysis["summary_zh"],
                    "key_points_zh": analysis["key_points_zh"],
                    "relevance_score": analysis["relevance_score"],
                    "relevance_reason": analysis["relevance_reason"],
                    "publish_time": str(paper.get("publish_time", "")).strip(),
                    "update_time": str(paper.get("update_time", "")).strip(),
                    "created_at": now_iso(),
                }
                _, created = upsert_paper(record)
                if created:
                    new_count += 1
                    new_titles.append(record["title_zh"])

            update_state(
                {
                    "updated_at": now_iso(),
                    "last_run_at": now_iso(),
                    "last_error": "",
                    "last_new_count": new_count,
                    "last_category": clean_category,
                    "last_topic": clean_topic,
                    "last_used_queries": search_queries,
                }
            )

            summary = "LITERATURE_OK"
            if new_count > 0:
                title_preview = "；".join(new_titles[:3])
                summary = f"新增 {new_count} 篇文献：{title_preview}" if title_preview else f"新增 {new_count} 篇文献"
            elif analyzed_count == 0:
                summary = "LITERATURE_OK：本轮候选论文与主题相关性较低，未入库"
            elif not summary_candidates:
                summary = "LITERATURE_OK：批量筛选后暂无高相关论文"

            return {
                "status": "ok",
                "summary": summary,
                "error": "",
                "new_count": new_count,
                "search_queries": search_queries,
            }
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"[literature] 搜索失败: {error_text}")
            update_state(
                {
                    "updated_at": now_iso(),
                    "last_run_at": now_iso(),
                    "last_error": error_text,
                    "last_new_count": 0,
                    "last_category": clean_category,
                    "last_topic": clean_topic,
                }
            )
            return {
                "status": "error",
                "summary": "",
                "error": error_text,
                "new_count": 0,
                "search_queries": [],
            }

    def _plan_search_queries(
        self,
        *,
        topic: str,
        category: str,
        query_count: int,
        manual_query: str = "",
    ) -> list[str]:
        clean_topic = str(topic or "").strip()
        clean_category = str(category or "").strip()
        clean_manual_query = str(manual_query or "").strip()
        if not clean_topic and not clean_manual_query:
            raise ValueError("topic 和 query 不能同时为空")

        response = self._client.chat.completions.create(
            model=self._config["word_model"],
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 arXiv 检索关键词规划助手。"
                        "用户会给你一个中文或英文主题 topic，以及一个类别 category。"
                        "请生成适合 arXiv 检索的英文关键词短语。"
                        "只输出 JSON 对象，不要输出 markdown。"
                        "JSON 必须包含 queries 字段，值是英文字符串数组。"
                        f"请返回 1 到 {max(1, query_count)} 条去重后的检索短语。"
                        "每条都应尽量短，控制在 2 到 5 个英文词之间。"
                        "优先输出可检索的核心技术短语，不要输出冗长自然语言句子。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": clean_topic,
                            "category": clean_category,
                            "manual_query": clean_manual_query,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )

        content = _extract_completion_text(response)
        payload = _extract_json_object(content)
        queries = [str(item).strip() for item in payload.get("queries", []) if str(item).strip()]
        if clean_manual_query:
            queries.insert(0, clean_manual_query)

        deduped_queries: list[str] = []
        for item in queries:
            if item not in deduped_queries:
                deduped_queries.append(item)

        if not deduped_queries:
            deduped_queries = [clean_manual_query or clean_topic]

        return deduped_queries[: max(1, query_count)]

    def _next_search_queries(
        self,
        *,
        topic: str,
        category: str,
        queries_per_run: int,
        query_pool_size: int,
        query_plan_refresh_seconds: int,
        manual_query: str = "",
    ) -> list[str]:
        state = read_state()
        cache = dict(state.get("query_plan_cache", {}) if isinstance(state.get("query_plan_cache"), dict) else {})
        cache_key = self._query_cache_key(category=category, topic=topic, manual_query=manual_query)
        cache_item = dict(cache.get(cache_key, {})) if isinstance(cache.get(cache_key), dict) else {}

        cached_queries = [str(v).strip() for v in cache_item.get("queries", []) if str(v).strip()]
        last_planned_at = parse_iso(cache_item.get("last_planned_at"))
        plan_due = (
            not cached_queries
            or len(cached_queries) < queries_per_run
            or last_planned_at is None
            or (now_dt() - last_planned_at) >= timedelta(seconds=query_plan_refresh_seconds)
        )

        if plan_due:
            cached_queries = self._plan_search_queries(
                topic=topic,
                category=category,
                query_count=query_pool_size,
                manual_query=manual_query,
            )
            cache_item = {
                "category": category,
                "topic": topic,
                "queries": cached_queries,
                "cursor": 0,
                "last_planned_at": now_iso(),
                "last_used_at": None,
            }

        total = len(cached_queries)
        if total <= 0:
            return []

        cursor = max(0, int(cache_item.get("cursor", 0) or 0))
        selected: list[str] = []
        for offset in range(min(queries_per_run, total)):
            selected.append(cached_queries[(cursor + offset) % total])

        cache_item["cursor"] = (cursor + len(selected)) % total
        cache_item["last_used_at"] = now_iso()
        cache_item["queries"] = cached_queries
        cache_item["category"] = category
        cache_item["topic"] = topic
        cache[cache_key] = cache_item
        update_state({"query_plan_cache": cache})
        return selected

    def _query_cache_key(self, *, category: str, topic: str, manual_query: str = "") -> str:
        return f"{_normalize_text(category)}::{_normalize_text(topic)}::{_normalize_text(manual_query)}"

    def _candidate_id(self, paper: dict[str, Any], index: int) -> str:
        arxiv_id = str(paper.get("arxiv_id", "")).strip()
        if arxiv_id:
            return f"arxiv:{arxiv_id}"
        return f"candidate:{index}"

    def _rank_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        topic: str,
        category: str,
        search_queries: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        query_keywords = _extract_keywords(topic, category, *search_queries)
        ranked: list[tuple[int, dict[str, Any]]] = []

        for paper in candidates:
            title = _normalize_text(str(paper.get("title", "")).strip())
            summary = _normalize_text(str(paper.get("summary", "")).strip())
            if not title and not summary:
                continue

            score = 0
            matched_keywords: set[str] = set()
            for keyword in query_keywords:
                if keyword in title:
                    score += 4
                    matched_keywords.add(keyword)
                elif keyword in summary:
                    score += 2
                    matched_keywords.add(keyword)

            matched_query = _normalize_text(str(paper.get("matched_query", "")).strip())
            for keyword in _extract_keywords(matched_query):
                if keyword in title:
                    score += 3
                    matched_keywords.add(keyword)
                elif keyword in summary:
                    score += 1
                    matched_keywords.add(keyword)

            specific_matches = [keyword for keyword in matched_keywords if keyword not in GENERIC_QUERY_TERMS]
            if score <= 0 or (not specific_matches and len(matched_keywords) < 2):
                continue
            ranked.append((score, paper))

        ranked.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("publish_time", "")),
                str(item[1].get("title", "")),
            ),
            reverse=True,
        )
        return [paper for _, paper in ranked[: max(1, limit)]]

    def _search_new_candidates(self, search_queries: list[str], *, max_results: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for search_query in search_queries:
            raw_papers = search_arxiv_papers(search_query, max_results=max_results)
            for paper in raw_papers:
                arxiv_id = str(paper.get("arxiv_id", "")).strip()
                pdf_url = str(paper.get("pdf_link", "")).strip()
                title_en = str(paper.get("title", "")).strip()

                duplicate_id = find_duplicate_paper_id(
                    arxiv_id=arxiv_id,
                    pdf_url=pdf_url,
                    title_en=title_en,
                )
                if duplicate_id:
                    continue

                local_key = build_paper_id(arxiv_id, pdf_url, title_en)
                if local_key in seen_keys:
                    continue
                seen_keys.add(local_key)

                candidate = dict(paper)
                candidate["matched_query"] = search_query
                candidates.append(candidate)

        return candidates

    def _screen_papers_batch(
        self,
        papers: list[dict[str, Any]],
        *,
        topic: str,
        category: str,
    ) -> dict[str, dict[str, Any]]:
        payload_papers: list[dict[str, Any]] = []
        for index, paper in enumerate(papers, start=1):
            payload_papers.append(
                {
                    "candidate_id": self._candidate_id(paper, index),
                    "matched_query": str(paper.get("matched_query", "")).strip(),
                    "title_en": str(paper.get("title", "")).strip(),
                    "summary_en": str(paper.get("summary", "")).strip(),
                    "publish_time": str(paper.get("publish_time", "")).strip(),
                    "update_time": str(paper.get("update_time", "")).strip(),
                }
            )

        response = self._client.chat.completions.create(
            model=self._config["word_model"],
            temperature=0.15,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是论文相关性筛选助手。"
                        "你会拿到一个主题 topic、类别 category，以及多篇候选论文的标题与摘要。"
                        "请逐篇判断其是否与主题高度相关。"
                        "只输出 JSON 对象，不要输出 markdown 代码块，也不要补充解释。"
                        "JSON 顶层必须包含 analyses 字段，值是数组。"
                        "数组里的每一项都必须包含 candidate_id, is_relevant, relevance_score, relevance_reason。"
                        "candidate_id 必须原样返回。"
                        "is_relevant 是布尔值；relevance_score 是 0 到 100 的整数；relevance_reason 是一句简短中文理由。"
                        "只有当论文与主题确实高度相关时，is_relevant 才能为 true。"
                        "这是筛选阶段，不要输出标题翻译、长摘要或要点。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "category": category,
                            "papers": payload_papers,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = _extract_completion_text(response)
        payload = _extract_json_object(content)
        raw_analyses = payload.get("analyses", [])
        if not isinstance(raw_analyses, list) or not raw_analyses:
            raise ValueError("模型没有返回有效的 analyses 数组")

        analyses: dict[str, dict[str, Any]] = {}
        for item in raw_analyses:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            relevance_reason = str(item.get("relevance_reason", "")).strip()
            if not candidate_id or not relevance_reason:
                continue

            relevance_score = _to_relevance_score(item.get("relevance_score", 0))
            is_relevant = _to_bool(item.get("is_relevant", False))
            analyses[candidate_id] = {
                "is_relevant": is_relevant and relevance_score >= MIN_RELEVANCE_SCORE,
                "relevance_score": relevance_score,
                "relevance_reason": relevance_reason,
            }

        if not analyses:
            raise ValueError("模型没有返回可用的批量分析结果")
        return analyses

    def _summarize_papers_batch(
        self,
        papers: list[dict[str, Any]],
        *,
        topic: str,
        category: str,
    ) -> dict[str, dict[str, Any]]:
        payload_papers: list[dict[str, Any]] = []
        for index, paper in enumerate(papers, start=1):
            payload_papers.append(
                {
                    "candidate_id": self._candidate_id(paper, index),
                    "matched_query": str(paper.get("matched_query", "")).strip(),
                    "title_en": str(paper.get("title", "")).strip(),
                    "summary_en": str(paper.get("summary", "")).strip(),
                    "publish_time": str(paper.get("publish_time", "")).strip(),
                    "update_time": str(paper.get("update_time", "")).strip(),
                }
            )

        response = self._client.chat.completions.create(
            model=self._config["word_model"],
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是论文中文整理助手。"
                        "你会拿到一个主题 topic、类别 category，以及多篇已经确认相关的候选论文。"
                        "请逐篇输出中文标题、较完整的中文摘要和中文要点。"
                        "只输出 JSON 对象，不要输出 markdown 代码块，也不要补充解释。"
                        "JSON 顶层必须包含 analyses 字段，值是数组。"
                        "数组里的每一项都必须包含 candidate_id, title_zh, summary_zh, key_points_zh。"
                        "candidate_id 必须原样返回。"
                        "请将 summary_zh 写成更完整的中文摘要，长度控制在 220 到 420 个汉字。"
                        "key_points_zh 需要输出 4 到 6 条中文要点。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "category": category,
                            "papers": payload_papers,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = _extract_completion_text(response)
        payload = _extract_json_object(content)
        raw_analyses = payload.get("analyses", [])
        if not isinstance(raw_analyses, list) or not raw_analyses:
            raise ValueError("模型没有返回有效的摘要整理数组")

        analyses: dict[str, dict[str, Any]] = {}
        for item in raw_analyses:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            title_zh = str(item.get("title_zh", "")).strip()
            summary_zh = str(item.get("summary_zh", "")).strip()
            key_points_zh = [str(v).strip() for v in item.get("key_points_zh", []) if str(v).strip()]
            if not candidate_id or not title_zh or not summary_zh or len(key_points_zh) < 3:
                continue
            analyses[candidate_id] = {
                "title_zh": title_zh,
                "summary_zh": summary_zh,
                "key_points_zh": key_points_zh[:6],
            }

        if not analyses:
            raise ValueError("模型没有返回可用的摘要整理结果")
        return analyses

    def _analyze_paper(
        self,
        paper: dict[str, Any],
        *,
        topic: str,
        category: str,
    ) -> dict[str, Any]:
        title_en = str(paper.get("title", "")).strip()
        summary_en = str(paper.get("summary", "")).strip()
        publish_time = str(paper.get("publish_time", "")).strip()
        update_time = str(paper.get("update_time", "")).strip()
        matched_query = str(paper.get("matched_query", "")).strip()

        prompt = {
            "topic": topic,
            "category": category,
            "matched_query": matched_query,
            "title_en": title_en,
            "summary_en": summary_en,
            "publish_time": publish_time,
            "update_time": update_time,
        }

        response = self._client.chat.completions.create(
            model=self._config["word_model"],
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是论文筛选与整理助手。"
                        "你会拿到一个主题 topic、类别 category，以及一篇候选论文。"
                        "请先判断这篇论文是否真的和主题高度相关，再在相关时输出中文整理结果。"
                        "只输出 JSON 对象，不要输出 markdown 代码块，也不要补充解释。"
                        "JSON 必须包含 is_relevant, relevance_score, relevance_reason, title_zh, summary_zh, key_points_zh 六个字段。"
                        "其中 is_relevant 是布尔值；relevance_score 是 0 到 100 的整数；relevance_reason 是一句简短中文理由。"
                        "如果论文不相关，仍然要返回全部字段，但 title_zh 可直接翻译标题，summary_zh 用一句中文说明为何不相关，key_points_zh 返回空数组。"
                        "只有当论文与主题确实高度相关时，is_relevant 才能为 true。"
                        f"请将相关论文的 summary_zh 写成更完整的中文摘要，长度控制在 220 到 420 个汉字。"
                        "key_points_zh 需要输出 4 到 6 条中文要点。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
        )
        content = _extract_completion_text(response)
        payload = _extract_json_object(content)

        title_zh = str(payload.get("title_zh", "")).strip()
        summary_zh = str(payload.get("summary_zh", "")).strip()
        key_points_zh = [str(item).strip() for item in payload.get("key_points_zh", []) if str(item).strip()]
        relevance_reason = str(payload.get("relevance_reason", "")).strip()
        relevance_score = _to_relevance_score(payload.get("relevance_score", 0))
        is_relevant = _to_bool(payload.get("is_relevant", False))

        if not title_zh or not summary_zh or not relevance_reason:
            raise ValueError("模型没有返回完整的论文分析结果")

        normalized_relevant = is_relevant and relevance_score >= MIN_RELEVANCE_SCORE and len(key_points_zh) >= 3

        return {
            "is_relevant": normalized_relevant,
            "relevance_score": relevance_score,
            "relevance_reason": relevance_reason,
            "title_zh": title_zh,
            "summary_zh": summary_zh,
            "key_points_zh": key_points_zh[:6],
        }
