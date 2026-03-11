import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from beanie import PydanticObjectId
from beanie.operators import In

from server.src.models.device import Device, DeviceStatus
from server.src.models.script import Script
from server.src.models.strategy import Strategy, StrategyPhase, StrategyStatus
from server.src.models.task import Task, TaskSource, TaskStatus
from server.src.services.command_dispatcher import dispatch_command
from server.src.ws.admin_handler import broadcast_to_admins

logger = logging.getLogger(__name__)

EFFECTIVENESS_DECLINE_THRESHOLD = 0.20


# ---------------------------------------------------------------------------
# Explore
# ---------------------------------------------------------------------------

async def start_explore(
    script_id: str,
    device_count: int,
    rounds: int,
    param_variations: list[dict],
) -> dict:
    script_oid = PydanticObjectId(script_id)
    script = await Script.get(script_oid)
    if not script:
        raise ValueError(f"Script {script_id} not found")

    session_id = str(uuid4())
    strategies: list[Strategy] = []

    for idx, params in enumerate(param_variations):
        strategy = Strategy(
            name=f"{script.name}_explore_{idx}",
            script_id=script_oid,
            script_version=script.current_version,
            params=params,
            phase=StrategyPhase.EXPLORE,
            status=StrategyStatus.ACTIVE,
            explore_session_id=session_id,
        )
        await strategy.insert()
        strategies.append(strategy)

    available_devices = await Device.find(
        Device.status == DeviceStatus.ONLINE,
    ).limit(device_count).to_list()

    tasks_created = 0
    for _round in range(rounds):
        for strategy in strategies:
            for device in available_devices:
                try:
                    await dispatch_command(
                        device_id=device.id,
                        script_id=strategy.script_id,
                        script_version=strategy.script_version,
                        params=strategy.params,
                        source=TaskSource.EXPLORE,
                        strategy_id=strategy.id,
                    )
                    tasks_created += 1
                except Exception as e:
                    logger.error(
                        f"Explore dispatch failed (strategy={strategy.id}, "
                        f"device={device.id}): {e}"
                    )

    return {
        "explore_session_id": session_id,
        "strategies_created": len(strategies),
        "devices_assigned": len(available_devices),
        "tasks_created": tasks_created,
    }


async def stop_explore(session_id: str) -> None:
    strategies = await Strategy.find(
        Strategy.explore_session_id == session_id,
    ).to_list()

    strategy_ids = [s.id for s in strategies]

    for s in strategies:
        s.status = StrategyStatus.PAUSED
        s.updated_at = datetime.now(timezone.utc)
        await s.save()

    pending_tasks = await Task.find(
        In(Task.strategy_id, strategy_ids),
        In(Task.status, [TaskStatus.PENDING, TaskStatus.DISPATCHED]),
    ).to_list()

    now = datetime.now(timezone.utc)
    for task in pending_tasks:
        task.status = TaskStatus.CANCELLED
        task.completed_at = now
        await task.save()


async def get_explore_analysis(session_id: str) -> dict:
    strategies = await Strategy.find(
        Strategy.explore_session_id == session_id,
    ).to_list()

    analysis: list[dict] = []
    for s in strategies:
        tasks = await Task.find(Task.strategy_id == s.id).to_list()
        total_exec = len(tasks)
        success_count = sum(1 for t in tasks if t.status == TaskStatus.SUCCESS)
        total_downloads = sum(
            t.result.download_count for t in tasks if t.result
        )
        score = (total_downloads / total_exec) if total_exec > 0 else 0.0

        s.total_executions = total_exec
        s.successful_executions = success_count
        s.total_downloads = total_downloads
        s.effectiveness_score = round(score, 4)
        s.updated_at = datetime.now(timezone.utc)
        await s.save()

        analysis.append({
            "strategy_id": str(s.id),
            "name": s.name,
            "params": s.params,
            "total_executions": total_exec,
            "success_count": success_count,
            "total_downloads": total_downloads,
            "effectiveness_score": s.effectiveness_score,
        })

    analysis.sort(key=lambda x: x["effectiveness_score"], reverse=True)
    recommended = [a["strategy_id"] for a in analysis if a["effectiveness_score"] > 0]

    return {
        "explore_session_id": session_id,
        "strategies": analysis,
        "recommended_strategy_ids": recommended[:3],
    }


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

async def start_execute(
    strategy_ids: list[str],
    device_ids: Optional[list[str]] = None,
) -> dict:
    strategies: list[Strategy] = []
    for sid in strategy_ids:
        s = await Strategy.get(PydanticObjectId(sid))
        if not s:
            raise ValueError(f"Strategy {sid} not found")
        s.phase = StrategyPhase.EXECUTE
        s.status = StrategyStatus.ACTIVE
        s.updated_at = datetime.now(timezone.utc)
        await s.save()
        strategies.append(s)

    if device_ids:
        devices = [
            await Device.get(PydanticObjectId(d)) for d in device_ids
        ]
        devices = [d for d in devices if d is not None]
    else:
        devices = await Device.find(
            Device.status == DeviceStatus.ONLINE,
        ).to_list()

    tasks_created = 0
    for strategy in strategies:
        for device in devices:
            try:
                await dispatch_command(
                    device_id=device.id,
                    script_id=strategy.script_id,
                    script_version=strategy.script_version,
                    params=strategy.params,
                    source=TaskSource.EXECUTE,
                    strategy_id=strategy.id,
                )
                tasks_created += 1
            except Exception as e:
                logger.error(
                    f"Execute dispatch failed (strategy={strategy.id}, "
                    f"device={device.id}): {e}"
                )

    return {
        "strategies_deployed": len(strategies),
        "tasks_created": tasks_created,
    }


async def get_effectiveness_monitor(strategy_id: str) -> dict:
    s = await Strategy.get(PydanticObjectId(strategy_id))
    if not s:
        raise ValueError(f"Strategy {strategy_id} not found")

    tasks = await Task.find(Task.strategy_id == s.id).to_list()
    total_exec = len(tasks)
    success_count = sum(1 for t in tasks if t.status == TaskStatus.SUCCESS)
    total_downloads = sum(t.result.download_count for t in tasks if t.result)
    current_score = (total_downloads / total_exec) if total_exec > 0 else 0.0
    current_score = round(current_score, 4)

    historical = s.effectiveness_score
    decline = 0.0
    if historical > 0:
        decline = round((historical - current_score) / historical, 4)

    alerts: list[str] = []
    if decline >= EFFECTIVENESS_DECLINE_THRESHOLD:
        alerts.append(
            f"Effectiveness declined {decline:.1%} "
            f"(from {historical} to {current_score})"
        )

    return {
        "strategy_id": str(s.id),
        "name": s.name,
        "phase": s.phase.value,
        "status": s.status.value,
        "historical_score": historical,
        "current_score": current_score,
        "decline_pct": decline,
        "total_executions": total_exec,
        "success_count": success_count,
        "total_downloads": total_downloads,
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Background effectiveness monitor (Phase 8 / T074)
# ---------------------------------------------------------------------------

async def monitor_effectiveness_loop() -> None:
    """Check all active execute-phase strategies for effectiveness decline."""
    strategies = await Strategy.find(
        Strategy.phase == StrategyPhase.EXECUTE,
        Strategy.status == StrategyStatus.ACTIVE,
    ).to_list()

    for s in strategies:
        try:
            monitor = await get_effectiveness_monitor(str(s.id))
            new_score = monitor["current_score"]

            if new_score != s.effectiveness_score:
                s.effectiveness_score = new_score
                s.updated_at = datetime.now(timezone.utc)
                await s.save()

            if monitor["alerts"]:
                await broadcast_to_admins({
                    "type": "alert",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "level": "warning",
                        "source": "strategy_monitor",
                        "strategy_id": str(s.id),
                        "strategy_name": s.name,
                        "alerts": monitor["alerts"],
                    },
                })
        except Exception as e:
            logger.error(f"Monitor error for strategy {s.id}: {e}")
