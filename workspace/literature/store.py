from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
LITERATURE_DIR = WORKSPACE_DIR / "literature"
CATEGORIES_DIR = LITERATURE_DIR / "categories"
STATE_PATH = LITERATURE_DIR / "state.yaml"
INDEX_PATH = LITERATURE_DIR / "index.yaml"
README_PATH = LITERATURE_DIR / "README.md"

STORE_LOCK = RLock()
TITLE_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_yaml(path, default)
        return dict(default)

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        _write_yaml(path, default)
        return dict(default)

    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        return dict(default)

    merged = dict(default)
    merged.update(loaded)
    return merged


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "last_run_at": None,
        "last_error": "",
        "last_new_count": 0,
        "last_category": "",
        "last_topic": "",
        "last_used_queries": [],
        "default_search_queries_per_topic": 3,
        "default_query_pool_size": 9,
        "default_query_plan_refresh_seconds": 86400,
        "default_max_results_per_query": 30,
        "default_max_new_papers_per_run": 3,
        "default_max_analyzed_papers_per_run": 6,
        "query_plan_cache": {},
    }


def _default_index() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "papers": {},
    }


def _default_category(category: str) -> dict[str, Any]:
    return {
        "version": 1,
        "category": category,
        "updated_at": None,
        "papers": [],
    }


def _readme_text() -> str:
    return (
        "# literature workspace\n\n"
        "- `state.yaml`: 文献整理的全局状态与默认参数。\n"
        "- `index.yaml`: 全局去重后的论文索引。\n"
        "- `categories/*.yaml`: 按类别整理后的中文论文条目。\n"
        "- `learn/learn_tasks.yaml`: 真正控制哪些主题会被巡检，以及频率是多少。\n\n"
        "现在文献整理由 learn 服务调度；`workspace/literature` 只负责存储和执行。\n"
    )


def _normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    root = dict(_default_state())
    root.update(data if isinstance(data, dict) else {})
    root["default_search_queries_per_topic"] = max(1, int(root.get("default_search_queries_per_topic", 3) or 3))
    root["default_query_pool_size"] = max(
        root["default_search_queries_per_topic"],
        int(root.get("default_query_pool_size", 9) or 9),
    )
    root["default_query_plan_refresh_seconds"] = max(300, int(root.get("default_query_plan_refresh_seconds", 86400) or 86400))
    root["default_max_results_per_query"] = max(1, int(root.get("default_max_results_per_query", 30) or 30))
    root["default_max_new_papers_per_run"] = max(1, int(root.get("default_max_new_papers_per_run", 3) or 3))
    root["default_max_analyzed_papers_per_run"] = max(
        root["default_max_new_papers_per_run"],
        int(root.get("default_max_analyzed_papers_per_run", 6) or 6),
    )
    root["last_error"] = str(root.get("last_error", "") or "")
    root["last_category"] = str(root.get("last_category", "") or "")
    root["last_topic"] = str(root.get("last_topic", "") or "")
    root["last_used_queries"] = [str(v).strip() for v in root.get("last_used_queries", []) if str(v).strip()]
    raw_cache = root.get("query_plan_cache", {})
    cache: dict[str, dict[str, Any]] = {}
    if isinstance(raw_cache, dict):
        for cache_key, item in raw_cache.items():
            if not isinstance(item, dict):
                continue
            clean_key = str(cache_key).strip()
            if not clean_key:
                continue
            queries = [str(v).strip() for v in item.get("queries", []) if str(v).strip()]
            cache[clean_key] = {
                "category": str(item.get("category", "") or ""),
                "topic": str(item.get("topic", "") or ""),
                "queries": queries,
                "cursor": max(0, int(item.get("cursor", 0) or 0)),
                "last_planned_at": item.get("last_planned_at"),
                "last_used_at": item.get("last_used_at"),
            }
    root["query_plan_cache"] = cache
    return root


def _normalize_index(data: dict[str, Any]) -> dict[str, Any]:
    root = dict(_default_index())
    root.update(data if isinstance(data, dict) else {})
    papers: dict[str, dict[str, Any]] = {}
    raw_papers = root.get("papers")
    if isinstance(raw_papers, dict):
        for paper_id, item in raw_papers.items():
            if not isinstance(item, dict):
                continue
            record = dict(item)
            record["id"] = str(record.get("id") or paper_id).strip()
            if not record["id"]:
                continue
            record["categories"] = [str(v).strip() for v in record.get("categories", []) if str(v).strip()]
            record["topics"] = [str(v).strip() for v in record.get("topics", []) if str(v).strip()]
            record["queries"] = [str(v).strip() for v in record.get("queries", []) if str(v).strip()]
            record["key_points_zh"] = [str(v).strip() for v in record.get("key_points_zh", []) if str(v).strip()]
            papers[record["id"]] = record
    root["papers"] = papers
    return root


def _safe_category_name(category: str) -> str:
    clean = str(category or "").strip()
    clean = clean.replace("/", "_").replace("\\", "_")
    clean = re.sub(r"\s+", "_", clean)
    return clean or "misc"


def normalize_title_key(title: str) -> str:
    normalized = TITLE_NORMALIZE_PATTERN.sub(" ", str(title or "").strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def build_paper_id(arxiv_id: str, pdf_url: str, title_en: str) -> str:
    clean_arxiv_id = str(arxiv_id or "").strip()
    if clean_arxiv_id:
        return f"arxiv:{clean_arxiv_id}"

    raw = str(pdf_url or "").strip() or normalize_title_key(title_en)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"paper:{digest}"


def ensure_literature_layout() -> None:
    with STORE_LOCK:
        CATEGORIES_DIR.mkdir(parents=True, exist_ok=True)
        _read_yaml(STATE_PATH, _default_state())
        _read_yaml(INDEX_PATH, _default_index())
        if not README_PATH.exists():
            README_PATH.write_text(_readme_text(), encoding="utf-8")


def read_state() -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        return _normalize_state(_read_yaml(STATE_PATH, _default_state()))


def write_state(payload: dict[str, Any]) -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        normalized = _normalize_state(payload)
        _write_yaml(STATE_PATH, normalized)
        return normalized


def update_state(patch: dict[str, Any]) -> dict[str, Any]:
    with STORE_LOCK:
        state = read_state()
        merged = dict(state)
        merged.update(patch)
        return write_state(merged)


def read_index() -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        return _normalize_index(_read_yaml(INDEX_PATH, _default_index()))


def write_index(payload: dict[str, Any]) -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        normalized = _normalize_index(payload)
        normalized["updated_at"] = now_iso()
        _write_yaml(INDEX_PATH, normalized)
        return normalized


def read_category(category: str) -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        category_path = CATEGORIES_DIR / f"{_safe_category_name(category)}.yaml"
        return _read_yaml(category_path, _default_category(category))


def write_category(category: str, payload: dict[str, Any]) -> dict[str, Any]:
    with STORE_LOCK:
        ensure_literature_layout()
        category_path = CATEGORIES_DIR / f"{_safe_category_name(category)}.yaml"
        normalized = dict(_default_category(category))
        normalized.update(payload if isinstance(payload, dict) else {})
        normalized["category"] = category
        normalized["updated_at"] = now_iso()
        papers = normalized.get("papers", [])
        normalized["papers"] = [item for item in papers if isinstance(item, dict)]
        _write_yaml(category_path, normalized)
        return normalized


def find_duplicate_paper_id(*, arxiv_id: str = "", pdf_url: str = "", title_en: str = "") -> str | None:
    clean_arxiv_id = str(arxiv_id or "").strip()
    clean_pdf_url = str(pdf_url or "").strip()
    title_key = normalize_title_key(title_en)
    index = read_index()
    papers = index.get("papers", {})
    if not isinstance(papers, dict):
        return None

    for paper_id, item in papers.items():
        if not isinstance(item, dict):
            continue
        if clean_arxiv_id and str(item.get("arxiv_id", "")).strip() == clean_arxiv_id:
            return str(paper_id)
        if clean_pdf_url and str(item.get("pdf_url", "")).strip() == clean_pdf_url:
            return str(paper_id)
        if title_key and normalize_title_key(item.get("title_en", "")) == title_key:
            return str(paper_id)
    return None


def upsert_paper(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    with STORE_LOCK:
        ensure_literature_layout()
        index = read_index()
        papers = dict(index.get("papers", {}))

        duplicate_id = find_duplicate_paper_id(
            arxiv_id=str(record.get("arxiv_id", "")).strip(),
            pdf_url=str(record.get("pdf_url", "")).strip(),
            title_en=str(record.get("title_en", "")).strip(),
        )
        paper_id = duplicate_id or str(record.get("id", "")).strip() or build_paper_id(
            str(record.get("arxiv_id", "")).strip(),
            str(record.get("pdf_url", "")).strip(),
            str(record.get("title_en", "")).strip(),
        )

        existing = dict(papers.get(paper_id, {}))
        merged = dict(existing)
        merged.update(record)
        merged["id"] = paper_id

        categories = [str(v).strip() for v in merged.get("categories", []) if str(v).strip()]
        topics = [str(v).strip() for v in merged.get("topics", []) if str(v).strip()]
        queries = [str(v).strip() for v in merged.get("queries", []) if str(v).strip()]
        merged["categories"] = list(dict.fromkeys(categories))
        merged["topics"] = list(dict.fromkeys(topics))
        merged["queries"] = list(dict.fromkeys(queries))
        merged["created_at"] = str(existing.get("created_at") or record.get("created_at") or now_iso())
        merged["updated_at"] = now_iso()
        papers[paper_id] = merged

        index["papers"] = papers
        write_index(index)

        for category in merged["categories"]:
            _refresh_category_file(category, papers)

        return dict(merged), paper_id not in existing


def _category_entry(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(record.get("id", "")).strip(),
        "title_zh": str(record.get("title_zh", "")).strip(),
        "title_en": str(record.get("title_en", "")).strip(),
        "pdf_url": str(record.get("pdf_url", "")).strip(),
        "publish_time": str(record.get("publish_time", "")).strip(),
        "update_time": str(record.get("update_time", "")).strip(),
        "topics": [str(v).strip() for v in record.get("topics", []) if str(v).strip()],
        "summary_zh": str(record.get("summary_zh", "")).strip(),
        "key_points_zh": [str(v).strip() for v in record.get("key_points_zh", []) if str(v).strip()],
        "queries": [str(v).strip() for v in record.get("queries", []) if str(v).strip()],
        "source": str(record.get("source", "")).strip(),
        "created_at": str(record.get("created_at", "")).strip(),
    }


def _refresh_category_file(category: str, papers: dict[str, Any]) -> None:
    category_items: list[dict[str, Any]] = []
    for record in papers.values():
        if not isinstance(record, dict):
            continue
        categories = [str(v).strip() for v in record.get("categories", []) if str(v).strip()]
        if category not in categories:
            continue
        category_items.append(_category_entry(record))

    category_items.sort(
        key=lambda item: (
            str(item.get("publish_time", "")),
            str(item.get("created_at", "")),
            str(item.get("id", "")),
        ),
        reverse=True,
    )
    write_category(category, {"papers": category_items})
