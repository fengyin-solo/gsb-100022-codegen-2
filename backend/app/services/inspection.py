"""巡检计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检编号", "巡检站点", "巡检类型"]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已漏检"]
ACTION_RULES = {"开始巡检": "执行中", "完成巡检": "已完成", "标记漏检": "已漏检"}
NEGATIVE_ACTIONS = []
ASSIGN_FIELDS = ["巡检人员", "巡检路线"]
BATCH_SIZE_MAX = 200
STAT_CARDS = [("待巡检任务", "待执行"), ("已完成巡检", "已完成"), ("漏检任务", "已漏检")]


class InspectionService:
    def __init__(self) -> None:
        # 安排留痕与幂等缓存都挂在服务实例上：进程内唯一，重启后随内存数据一起重置
        self._assignments: list[dict[str, Any]] = []
        self._batches: dict[str, dict[str, Any]] = {}

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

    def stats(self) -> list[dict[str, Any]]:
        """数量卡片按状态实时统计，批量安排、状态流转后重新拉取即可同步。"""
        rows = store.rows(MODULE)
        return [
            {"label": label, "value": sum(1 for row in rows if row.get("status") == status)}
            for label, status in STAT_CARDS
        ]

    def batch_assign(
        self,
        ids: list[int],
        values: dict[str, Any],
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """批量安排执行人员与巡检路线。

        逐条处理、逐条给结果：单条缺计划日期只拦截自己，不拖累同批其他任务。
        带 batch_id 的重复提交直接复用首次结果，同一次批量动作不会生成两份安排。
        """
        if batch_id and batch_id in self._batches:
            return {**self._batches[batch_id], "duplicated": True}

        person = str(values.get("巡检人员") or "").strip()
        route = str(values.get("巡检路线") or "").strip()
        if not person or not route:
            return self._reject("请同时填写执行人员与巡检路线，整批未生效")
        # 同一次提交里的重复 id 只安排一次，避免一次点击就留下两条安排记录
        unique_ids = list(dict.fromkeys(int(entry_id) for entry_id in ids))
        if not unique_ids:
            return self._reject("未选择任何巡检任务，整批未生效")
        if len(unique_ids) > BATCH_SIZE_MAX:
            return self._reject(f"单批最多 {BATCH_SIZE_MAX} 条，请分批安排")

        results: list[dict[str, Any]] = []
        for entry_id in unique_ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({
                    "id": entry_id,
                    "code": "",
                    "ok": False,
                    "message": f"巡检任务 {entry_id} 不存在或已归档",
                })
                continue
            code = str(entry.get("巡检编号") or "")
            if not str(entry.get("计划日期") or "").strip():
                results.append({
                    "id": entry_id,
                    "code": code,
                    "ok": False,
                    "message": "缺少计划日期，先补齐计划日期再安排",
                })
                continue
            if entry.get("巡检人员") == person and entry.get("巡检路线") == route:
                results.append({
                    "id": entry_id,
                    "code": code,
                    "ok": True,
                    "message": "已是相同的执行人员与巡检路线，未重复登记",
                })
                continue
            entry["巡检人员"] = person
            entry["巡检路线"] = route
            self._assignments.append({
                "id": len(self._assignments) + 1,
                "task_id": entry_id,
                "巡检编号": code,
                "巡检人员": person,
                "巡检路线": route,
                "安排时间": datetime.now().isoformat(timespec="seconds"),
                "batch_id": batch_id or "",
            })
            results.append({
                "id": entry_id,
                "code": code,
                "ok": True,
                "message": f"已安排 {person} 按「{route}」执行",
            })

        succeeded = sum(1 for item in results if item["ok"])
        blocked = len(results) - succeeded
        summary = {
            "ok": True,
            "message": f"批量安排完成：成功 {succeeded} 条，拦截 {blocked} 条",
            "results": results,
            "succeeded": succeeded,
            "blocked": blocked,
            "duplicated": False,
        }
        if batch_id:
            self._batches[batch_id] = summary
        return summary

    def assignments(self) -> list[dict[str, Any]]:
        """安排留痕：每一条成功安排都在这里记一笔，用来核对没有重复安排。"""
        return list(self._assignments)

    @staticmethod
    def _reject(message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "message": message,
            "results": [],
            "succeeded": 0,
            "blocked": 0,
            "duplicated": False,
        }
