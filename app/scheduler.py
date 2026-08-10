"""
【P4-L3 2026-08-08】后台调度器: 自动跑案件超时关闭 + 告警检查.

设计:
- 不引入 APScheduler / Celery 等重依赖, 用 asyncio.create_task 简单循环
- 启动时由 scripts/main.py 的 lifespan 调用 start_scheduler()
- 优雅停止: stop_scheduler() 设标志 + 等当前任务完成
- 间隔可配: settings.ALERT_SCHEDULER_INTERVAL_MIN, 设 0 关闭
- 日志: 每次执行打印 [scheduled] 跑了啥 + 几个告警
"""
import asyncio
import logging
from typing import Optional

from app.config import settings
from app.database import AsyncSessionLocal
from app.service.alert import run_all_alert_checks
from app.service.case import auto_close_timeout_cases

logger = logging.getLogger(__name__)


# 全局状态: 调度器后台 task 和停止标志
_scheduler_task: Optional[asyncio.Task] = None
_stop_flag: bool = False


async def _run_once() -> dict:
    """跑一轮: 案件超时关闭 + 告警检查, 返回执行结果 (用于测试 + 日志)."""
    result = {"closed_cases": 0, "alerts_created": 0, "errors": []}
    async with AsyncSessionLocal() as db:
        try:
            result["closed_cases"] = await auto_close_timeout_cases(db)
        except Exception as e:
            result["errors"].append(f"auto_close: {e}")
            logger.exception("[scheduled] auto_close_timeout_cases 失败")
        try:
            result["alerts_created"] = await run_all_alert_checks(db)
        except Exception as e:
            result["errors"].append(f"alert_check: {e}")
            logger.exception("[scheduled] run_all_alert_checks 失败")
    return result


async def _scheduler_loop() -> None:
    """主循环: 每 N 分钟跑一轮, 直到 stop_flag=True."""
    global _stop_flag
    interval_min = settings.ALERT_SCHEDULER_INTERVAL_MIN
    if interval_min <= 0:
        logger.info("[scheduled] ALERT_SCHEDULER_INTERVAL_MIN=0, 调度器未启动")
        return

    interval_sec = interval_min * 60
    logger.info("[scheduled] 启动: 间隔 %d 分钟 (案件超时 + 告警检查)", interval_min)

    while not _stop_flag:
        try:
            result = await _run_once()
            # P4-L4 2026-08-08 修复: alerts_created 是 list[RiskAlert], 用 len() 转 int
            logger.info(
                "[scheduled] 本轮: 关案 %d, 告警 %d, 错误 %d",
                result["closed_cases"], len(result["alerts_created"]), len(result["errors"]),
            )
        except Exception as e:
            logger.exception("[scheduled] _run_once 失败: %s", e)

        # 优雅等 N 分钟 (每 1s 检查 stop_flag, 避免长 sleep 卡停服)
        for _ in range(interval_sec):
            if _stop_flag:
                break
            await asyncio.sleep(1)

    logger.info("[scheduled] 停止")


def start_scheduler() -> asyncio.Task:
    """启动后台调度 task, 返回 task 句柄 (给 main.py 的 lifespan 用)."""
    global _scheduler_task, _stop_flag
    _stop_flag = False
    if _scheduler_task and not _scheduler_task.done():
        logger.warning("[scheduled] 已在运行, 跳过重复启动")
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="scheduler_loop")
    return _scheduler_task


async def stop_scheduler() -> None:
    """优雅停止: 设标志 + 等当前 task 完成 (最多 10s)."""
    global _stop_flag, _scheduler_task
    _stop_flag = True
    if _scheduler_task and not _scheduler_task.done():
        try:
            await asyncio.wait_for(_scheduler_task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("[scheduled] 10s 未停止, 强制 cancel")
            _scheduler_task.cancel()
    _scheduler_task = None
    logger.info("[scheduled] stop_scheduler() 完成")


def is_running() -> bool:
    """调度器是否在跑 (供健康检查端点用)."""
    return _scheduler_task is not None and not _scheduler_task.done()


# ============================================================
# Demo: 演示 _run_once() 跑一轮 (用真实 DB) + start/stop 生命周期
# 跑法: python app/scheduler.py
# ============================================================
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Scheduler — 自动跑 案件超时关闭 + 告警检查")
    print("=" * 60)

    print(f"\n[1] 配置:")
    print(f"  ALERT_SCHEDULER_INTERVAL_MIN = {settings.ALERT_SCHEDULER_INTERVAL_MIN} 分钟")
    print(f"  CASE_TIMEOUT_HOURS          = {settings.CASE_TIMEOUT_HOURS} 小时")
    print(f"  → 调度器启动后每 {settings.ALERT_SCHEDULER_INTERVAL_MIN} 分钟跑一轮")

    print(f"\n[2] 一轮执行内容 (_run_once):")
    print(f"  1. auto_close_timeout_cases(db)  → 关超时'待审核'案件")
    print(f"  2. run_all_alert_checks(db)       → 跑 3 个告警检查 (待审积压/规则命中率/撞黑比例)")

    print(f"\n[3] 启停 API (给 main.py 用):")
    print(f"  start_scheduler()  → 返回 asyncio.Task, 在事件循环里跑")
    print(f"  stop_scheduler()   → 优雅停 (等当前 task 完, 最多 10s)")
    print(f"  is_running()       → 健康检查")

    # 实际跑一轮 (需要 DB 连得上)
    async def _demo_run_once():
        try:
            result = await _run_once()
            print(f"\n[4] 实际跑一轮结果: {result}")
        except Exception as e:
            print(f"\n[4] 跑一轮失败: {e} (可能 DB 没连, 教学演示可忽略)")

    asyncio.run(_demo_run_once())

    print("\n" + "=" * 60)
    print("生产部署: K8s CronJob 也可替代本调度器 (K8s 标准化更好)")
