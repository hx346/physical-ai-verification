"""结构化 JSON 日志 + traceId 上下文（contextvar，协程安全）。"""

import contextvars
import logging

import structlog

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("traceId", default="")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_trace_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )


def _inject_trace_id(_, __, event_dict: dict) -> dict:
    event_dict["traceId"] = trace_id_var.get()
    return event_dict


def get_logger(name: str):
    return structlog.get_logger(name)
