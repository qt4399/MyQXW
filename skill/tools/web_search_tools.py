from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - handled at runtime
    DDGS = None  # type: ignore[assignment]

MAX_RESULTS_LIMIT = 20
DEFAULT_TEXT_REGION = "cn-zh"
DEFAULT_GLOBAL_REGION = "wt-wt"
DEFAULT_TIMEOUT_SECONDS = 12
RETRY_TIMEOUT_SECONDS = 20
GENERIC_NEWS_TERMS = ("今日", "热点", "热门", "热搜", "新闻", "最新", "头条", "要闻")
LOW_QUALITY_NEWS_PATHS = {
    "news",
    "china",
    "world",
    "finance",
    "shipin",
    "video",
    "sports",
    "tech",
    "mil",
    "auto",
    "ent",
    "channel",
}


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _normalize_query(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_search_type(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in {"text", "news"} else "text"


def _pick_region(query: str) -> str:
    return DEFAULT_TEXT_REGION if _contains_cjk(query) else DEFAULT_GLOBAL_REGION


def _parse_datetime(value: str) -> tuple[str, float]:
    clean = str(value or "").strip()
    if not clean:
        return "", 0.0

    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return "", 0.0
    localized = parsed.astimezone()
    return localized.strftime("%Y-%m-%d %H:%M:%S %z"), localized.timestamp()


def _tokenize_query(query: str) -> list[str]:
    if _contains_cjk(query):
        return re.findall(r"[\u3400-\u9fffA-Za-z0-9]+", query)
    return [token for token in re.split(r"\s+", query) if token]


def _strip_generic_news_terms(token: str) -> str:
    clean = str(token or "").strip()
    for term in GENERIC_NEWS_TERMS:
        clean = clean.replace(term, "")
    return clean.strip()


def _build_news_query_plan(query: str) -> list[str]:
    clean_query = _normalize_query(query)
    plan: list[str] = []
    if clean_query:
        plan.append(clean_query)

    tokens = _tokenize_query(clean_query)
    core_tokens = []
    for token in tokens:
        stripped = _strip_generic_news_terms(token)
        if stripped:
            core_tokens.append(stripped)

    if core_tokens:
        compact_core = " ".join(core_tokens)
        plan.append(f"{compact_core} 新闻")
        if _contains_cjk(compact_core):
            plan.append(f"{compact_core} 今日 新闻")
        else:
            plan.append(f"{compact_core} latest news")

    if _contains_cjk(clean_query):
        if "中国" in clean_query:
            plan.extend(["中国新闻", "国内新闻", "今日要闻"])
        else:
            plan.extend(["今日 热门 新闻", "今日要闻", "中国新闻"])
    else:
        plan.extend(["latest news today", "breaking news today"])

    deduped: list[str] = []
    seen: set[str] = set()
    for item in plan:
        normalized = _normalize_query(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _format_text_result(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("href") or item.get("url") or "").strip()
    return {
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "domain": urlsplit(url).netloc,
        "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
    }


def _format_news_result(item: dict[str, Any], matched_query: str) -> dict[str, Any]:
    url = str(item.get("url") or item.get("href") or "").strip()
    published_at = str(item.get("date") or "").strip()
    published_at_local, timestamp = _parse_datetime(published_at)
    return {
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "domain": urlsplit(url).netloc,
        "snippet": str(item.get("body") or item.get("excerpt") or "").strip(),
        "source": str(item.get("source") or "").strip(),
        "published_at": published_at,
        "published_at_local": published_at_local,
        "matched_query": matched_query,
        "_timestamp": timestamp,
    }


def _is_low_quality_news_url(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    path = parsed.path.strip().lower()
    if not path or path == "/":
        return True

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return True

    first = segments[0]
    last = segments[-1]
    if len(segments) == 1 and first in LOW_QUALITY_NEWS_PATHS:
        return True
    if len(segments) <= 2 and first in LOW_QUALITY_NEWS_PATHS and last in LOW_QUALITY_NEWS_PATHS:
        return True
    if len(segments) <= 2 and last in {"index.html", "index.shtml", "index.htm"}:
        return True

    article_like = (
        any(char.isdigit() for char in path)
        or path.endswith((".html", ".shtml", ".htm"))
        or len(segments) >= 3
    )
    return not article_like


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip().lower()
        title = str(item.get("title") or "").strip().lower()
        source = str(item.get("source") or "").strip().lower()
        key = url or f"{title}|{source}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _sort_news_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_results = sorted(
        results,
        key=lambda item: (
            float(item.get("_timestamp") or 0.0),
            len(str(item.get("title") or "")),
        ),
        reverse=True,
    )
    for item in sorted_results:
        item.pop("_timestamp", None)
    return sorted_results


def _run_text_search(query: str, region: str, max_results: int) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    timeouts = [DEFAULT_TIMEOUT_SECONDS, RETRY_TIMEOUT_SECONDS]
    for timeout in timeouts:
        try:
            with DDGS(timeout=timeout) as ddgs:
                raw_results = list(ddgs.text(query, region=region, max_results=max_results))
            return ([_format_text_result(item) for item in raw_results], errors)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return ([], errors)


def _run_news_search(query: str, region: str, max_results: int) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    timeouts = [DEFAULT_TIMEOUT_SECONDS, RETRY_TIMEOUT_SECONDS]
    for timeout in timeouts:
        try:
            with DDGS(timeout=timeout) as ddgs:
                raw_results = list(
                    ddgs.news(
                        query,
                        region=region,
                        timelimit="d",
                        max_results=max_results,
                    )
                )
            return ([_format_news_result(item, query) for item in raw_results], errors)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return ([], errors)


def _search_news_with_fallbacks(query: str, region: str, max_results: int) -> dict[str, Any]:
    query_plan = _build_news_query_plan(query)
    query_errors: list[dict[str, str]] = []
    collected: list[dict[str, Any]] = []

    for planned_query in query_plan:
        results, errors = _run_news_search(planned_query, region, max_results=max(8, max_results))
        if errors:
            query_errors.append(
                {
                    "query": planned_query,
                    "error": " | ".join(errors),
                }
            )
        if results:
            collected.extend(results)
        if len(_dedupe_results(collected)) >= max_results:
            break

    deduped_all = _dedupe_results(collected)
    filtered = [item for item in deduped_all if not _is_low_quality_news_url(str(item.get("url") or ""))]
    used_filtered = bool(filtered)
    final_results = filtered if filtered else deduped_all
    final_results = _sort_news_results(final_results)[:max_results]
    return {
        "results": final_results,
        "query_errors": query_errors,
        "effective_queries": query_plan,
        "filtered_low_quality_count": max(0, len(deduped_all) - len(filtered)),
        "used_filtered_results": used_filtered,
    }


def search_web_duckduckgo_result(
    query: str,
    *,
    search_type: str = "text",
    max_results: int = 10,
) -> dict[str, Any]:
    clean_query = _normalize_query(query)
    if not clean_query:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "query 不能为空",
            "query": clean_query,
            "total": 0,
            "results": [],
        }

    if DDGS is None:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "缺少依赖 ddgs，请先执行 pip install -r requirements.txt",
            "query": clean_query,
            "total": 0,
            "results": [],
        }

    clean_search_type = _normalize_search_type(search_type)
    clean_max_results = max(1, min(int(max_results or 8), MAX_RESULTS_LIMIT))
    region = _pick_region(clean_query)

    if clean_search_type == "news":
        payload = _search_news_with_fallbacks(clean_query, region, clean_max_results)
        results = payload["results"]
        if not results:
            error_text = "；".join(entry["error"] for entry in payload["query_errors"][:3]).strip()
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": error_text or "未找到可用的新闻结果",
                "query": clean_query,
                "search_type": clean_search_type,
                "region": region,
                "effective_queries": payload["effective_queries"],
                "query_errors": payload["query_errors"],
                "total": 0,
                "results": [],
            }

        return {
            "returncode": 0,
            "stdout": f"DuckDuckGo news 搜索成功，返回 {len(results)} 条结果",
            "stderr": "",
            "query": clean_query,
            "search_type": clean_search_type,
            "region": region,
            "searched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "effective_queries": payload["effective_queries"],
            "query_errors": payload["query_errors"],
            "filtered_low_quality_count": payload["filtered_low_quality_count"],
            "used_filtered_results": payload["used_filtered_results"],
            "total": len(results),
            "results": results,
        }

    results, errors = _run_text_search(clean_query, region, clean_max_results)
    if not results:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "；".join(errors[:3]).strip() or "未找到搜索结果",
            "query": clean_query,
            "search_type": clean_search_type,
            "region": region,
            "total": 0,
            "results": [],
        }

    return {
        "returncode": 0,
        "stdout": f"DuckDuckGo text 搜索成功，返回 {len(results)} 条结果",
        "stderr": "",
        "query": clean_query,
        "search_type": clean_search_type,
        "region": region,
        "searched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(results),
        "results": results,
    }
