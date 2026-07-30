"""Agent 调度器模块。

对外导出：
  - PipelineScheduler  全局流水线调度器
  - scheduler           全局唯一实例（模块级单例）

使用方式：
  from backend.src.scheduler import scheduler

  result = await scheduler.run_pipeline(
      user_input={"learner_data": {...}, "resource_types": [...]},
      task_id="xxx",
  )
"""

from backend.src.scheduler.pipeline import PipelineScheduler, scheduler

__all__ = ["PipelineScheduler", "scheduler"]
