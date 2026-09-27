"""巡检计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检编号", "巡检站点", "巡检类型"]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已漏检"]
ACTION_RULES = {"开始巡检": "执行中", "完成巡检": "已完成", "标记漏检": "已漏检"}
NEGATIVE_ACTIONS = []

# 幂等缓存只保留最近一次批量提交的结果，避免重复点击生成两份安排；
# 缓存条数设上限，防止长期运行时无限增长。
_TOKEN_CACHE_LIMIT = 1000


class InspectionService:
    def __init__(self) -> None:
        self._batch_cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = threading.Lock()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡检编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡检计划可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡检任务已{action}"

    def stats(self) -> dict[str, int]:
        """数量卡片口径：按内部状态统计全部巡检任务，与列表筛选条件无关。"""
        rows = store.rows(MODULE)
        return {
            "pending": sum(1 for row in rows if row.get("status") == "待执行"),
            "in_progress": sum(1 for row in rows if row.get("status") == "执行中"),
            "completed": sum(1 for row in rows if row.get("status") == "已完成"),
            "missed": sum(1 for row in rows if row.get("status") == "已漏检"),
            "total": len(rows),
        }

    def batch_arrange(
        self,
        *,
        entry_ids: list[int],
        inspector: str,
        route: str,
        client_token: str | None = None,
    ) -> dict[str, Any]:
        """批量安排执行人员与巡检路线。

        逐条校验：任务不存在、缺少计划日期的会被拦截并说明原因，不影响同批其他任务。
        携带 client_token 的重复提交直接返回首次结果，不会生成第二份安排。
        """
        if client_token:
            cached = self._cached_result(client_token)
            if cached is not None:
                return cached

        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for entry_id in entry_ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({
                    "entry_id": entry_id,
                    "ok": False,
                    "message": f"巡检任务 {entry_id} 不存在或已归档，已拦截",
                })
                continue
            if not str(entry.get("计划日期") or "").strip():
                results.append({
                    "entry_id": entry_id,
                    "ok": False,
                    "message": f"巡检任务 {entry_id}（{entry.get('巡检编号', '—')}）缺少计划日期，已拦截，请补充后再安排",
                })
                continue
            entry["巡检人员"] = inspector
            entry["巡检路线"] = route
            results.append({
                "entry_id": entry_id,
                "ok": True,
                "message": f"巡检任务 {entry_id}（{entry.get('巡检编号', '—')}）已安排：{inspector} / {route}",
            })

        success_count = sum(1 for item in results if item["ok"])
        failed_count = len(results) - success_count
        result = {
            "ok": True,
            "message": f"批量安排完成：成功 {success_count} 条，拦截 {failed_count} 条",
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }
        if client_token:
            self._remember_result(client_token, result)
        return result

    def _cached_result(self, client_token: str) -> dict[str, Any] | None:
        with self._cache_lock:
            cached = self._batch_cache.get(client_token)
            if cached is None:
                return None
            # 返回副本，避免调用方改动缓存内容
            return {**cached, "results": [dict(item) for item in cached["results"]]}

    def _remember_result(self, client_token: str, result: dict[str, Any]) -> None:
        with self._cache_lock:
            if len(self._batch_cache) >= _TOKEN_CACHE_LIMIT:
                oldest = next(iter(self._batch_cache))
                self._batch_cache.pop(oldest, None)
            self._batch_cache[client_token] = result
