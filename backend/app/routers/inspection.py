"""巡检计划接口：维护巡检任务，覆盖批量安排、开始巡检、完成巡检、标记漏检等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchAssignPayload, BatchAssignResult, EntryPayload, PageResult
from app.services.inspection import InspectionService

router = APIRouter(prefix="/api/inspection", tags=["巡检计划"])

service = InspectionService()

LIST_FIELDS = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
STATUSES = ["待执行", "执行中", "已完成", "已漏检"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡检编号检索"),
    status: str | None = Query(default=None, description="待执行、执行中、已完成、已漏检"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡检编号与状态过滤巡检计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 固定路径要放在 /{entry_id} 之前，否则会被当成 entry_id 抢走（export 之前就踩过这个坑）
@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """数量卡片：按状态实时统计，批量安排或状态流转后前端会重新拉取。"""
    return {"cards": service.stats()}


@router.get("/assignments")
def list_assignments() -> dict[str, Any]:
    """安排留痕：每一次成功安排记一笔，用来核对同一次批量动作没有生成两份安排。"""
    items = service.assignments()
    return {"total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出巡检计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inspection", "total": total, "items": items}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡检任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="巡检任务已登记", entry=entry)


@router.post("/batch-assign", response_model=BatchAssignResult)
def batch_assign(payload: BatchAssignPayload) -> BatchAssignResult:
    """批量安排执行人员与巡检路线：一次提交多条，逐条返回成功或拦截原因。

    某条缺计划日期只拦截自己；带相同 batch_id 的重复提交复用首次结果，不重复安排。
    """
    return BatchAssignResult(**service.batch_assign(payload.ids, payload.values, payload.batch_id))


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡检任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡检任务 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检任务执行开始巡检、完成巡检、标记漏检；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
