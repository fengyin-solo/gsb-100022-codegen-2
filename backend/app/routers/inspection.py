"""巡检计划接口：维护巡检任务，覆盖开始巡检、完成巡检、标记漏检等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchArrangePayload,
    BatchArrangeResult,
    EntryPayload,
    InspectionStats,
    PageResult,
)
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


@router.get("/stats", response_model=InspectionStats)
def get_stats() -> InspectionStats:
    """巡检任务数量卡片：批量安排完成后前端据此重算。"""
    return InspectionStats(**service.stats())


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出巡检计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inspection", "total": total, "items": items}


@router.post("/batch/arrange", response_model=BatchArrangeResult)
def batch_arrange(payload: BatchArrangePayload) -> BatchArrangeResult:
    """批量安排执行人员与巡检路线：一次提交多条，逐条返回成功或拦截信息。

    没有勾选任务、执行人员或巡检路线为空时整组拦下；
    个别任务缺少计划日期只拦截该条，不影响同批其他任务。
    """
    if not payload.entry_ids:
        return BatchArrangeResult(
            ok=False,
            message="未选择任何巡检任务，请先勾选需要安排的任务",
            success_count=0,
            failed_count=0,
            results=[],
        )
    inspector = payload.inspector.strip()
    route = payload.route.strip()
    missing: list[str] = []
    if not inspector:
        missing.append("执行人员")
    if not route:
        missing.append("巡检路线")
    if missing:
        return BatchArrangeResult(
            ok=False,
            message=f"批量安排缺少必填信息：{'、'.join(missing)}，未提交任何安排",
            success_count=0,
            failed_count=0,
            results=[],
        )
    data = service.batch_arrange(
        entry_ids=payload.entry_ids,
        inspector=inspector,
        route=route,
        client_token=payload.client_token,
    )
    return BatchArrangeResult(**data)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡检任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡检任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡检任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="巡检任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检任务执行开始巡检、完成巡检、标记漏检；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
