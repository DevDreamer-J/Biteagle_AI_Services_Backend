"""Celery 应用：RabbitMQ 作 broker。

任务状态以 PostgreSQL 为唯一事实来源，因此不启用结果后端，
Redis 只作为状态读缓存（见 clients/task_cache.py）。
"""

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import get_settings

settings = get_settings()

task_exchange = Exchange("ai", type="direct", durable=True)
dead_letter_exchange = Exchange("ai.dlx", type="direct", durable=True)

celery_app = Celery(
    "ai_services_backend",
    broker=settings.broker_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    # 可靠性：执行完才 ack；worker 掉线时消息重回队列
    # 失败/超时的消息仍要 ack：重试由业务状态机显式重投（见 workers/tasks.py），
    # 若这里不 ack，attempts 用尽的任务会无限重回队列形成毒消息循环
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # 业务队列挂了死信交换机，超过重试次数的任务落到 ai.dead 供排查
    task_queues=(
        Queue(
            "ai.tasks",
            task_exchange,
            routing_key="ai.tasks",
            queue_arguments={
                "x-dead-letter-exchange": "ai.dlx",
                "x-dead-letter-routing-key": "ai.dead",
            },
        ),
        Queue("ai.dead", dead_letter_exchange, routing_key="ai.dead"),
    ),
    task_default_queue="ai.tasks",
    task_default_exchange="ai",
    task_default_routing_key="ai.tasks",
    task_routes={"tasks.*": {"queue": "ai.tasks"}},
    # 超时保护：软超时抛异常走重试，硬超时兜底杀进程
    task_soft_time_limit=60,
    task_time_limit=90,
    # 周期性维护任务
    beat_schedule={
        "cleanup-expired-sessions": {"task": "tasks.cleanup_expired", "schedule": 600.0},
        "requeue-stale-tasks": {"task": "tasks.requeue_stale", "schedule": 120.0},
    },
)
