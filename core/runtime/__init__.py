"""
JoyBoy runtime foundation.

This package is intentionally small and dependency-light. It gives the app a
durable notion of conversations and jobs without forcing the image/video/LLM
pipelines to be rewritten in one step.
"""

from .jobs import JobManager, get_job_manager
from .conversations import ConversationStore, get_conversation_store
from .resources import ResourceScheduler, get_resource_scheduler

__all__ = [
    "JobManager",
    "get_job_manager",
    "ConversationStore",
    "get_conversation_store",
    "ResourceScheduler",
    "get_resource_scheduler",
]
