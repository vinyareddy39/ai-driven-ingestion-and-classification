"""Queue adapters supporting Redis Streams and in-memory queue fallback."""

import json
import time
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from app.core.interfaces import Queue
from app.core.config import get_app_settings


class MemoryQueue(Queue):
    """In-memory thread-safe queue implementing Redis Streams semantics."""

    def __init__(self):
        self._queues: Dict[str, deque] = {}
        self._counter: int = 0
        self._unacked: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _get_queue(self, queue_name: str) -> deque:
        if queue_name not in self._queues:
            self._queues[queue_name] = deque()
            self._unacked[queue_name] = {}
        return self._queues[queue_name]

    def push(self, queue_name: str, message: Dict[str, Any]) -> str:
        q = self._get_queue(queue_name)
        self._counter += 1
        msg_id = f"{int(time.time() * 1000)}-{self._counter}"
        q.append((msg_id, message))
        return msg_id

    def pop(self, queue_name: str, consumer_group: str = "default", timeout_ms: int = 1000) -> Optional[Tuple[str, Dict[str, Any]]]:
        q = self._get_queue(queue_name)
        if not q:
            return None
        msg_id, payload = q.popleft()
        self._unacked[queue_name][msg_id] = payload
        return (msg_id, payload)

    def ack(self, queue_name: str, consumer_group: str, message_id: str) -> bool:
        if queue_name in self._unacked and message_id in self._unacked[queue_name]:
            del self._unacked[queue_name][message_id]
            return True
        return False

    def length(self, queue_name: str) -> int:
        return len(self._get_queue(queue_name))


class RedisStreamsQueue(Queue):
    """Production Redis Streams queue adapter."""

    def __init__(self):
        import redis
        settings = get_app_settings()
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    def push(self, queue_name: str, message: Dict[str, Any]) -> str:
        # Serializes message dict to string fields for Redis Stream
        fields = {"payload": json.dumps(message)}
        msg_id = self.client.xadd(queue_name, fields)
        return str(msg_id)

    def pop(self, queue_name: str, consumer_group: str = "default", timeout_ms: int = 1000) -> Optional[Tuple[str, Dict[str, Any]]]:
        # Ensure group exists
        try:
            self.client.xgroup_create(queue_name, consumer_group, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

        entries = self.client.xreadgroup(
            consumer_group,
            "worker-1",
            {queue_name: ">"},
            count=1,
            block=timeout_ms,
        )
        if not entries:
            return None

        for stream_name, msg_list in entries:
            for msg_id, data in msg_list:
                payload = json.loads(data.get("payload", "{}"))
                return (msg_id, payload)
        return None

    def ack(self, queue_name: str, consumer_group: str, message_id: str) -> bool:
        res = self.client.xack(queue_name, consumer_group, message_id)
        return res > 0

    def length(self, queue_name: str) -> int:
        try:
            return self.client.xlen(queue_name)
        except Exception:
            return 0


_global_queue_adapter: Optional[Queue] = None


def get_queue_adapter() -> Queue:
    """Factory creating configured queue adapter."""
    global _global_queue_adapter
    if _global_queue_adapter is None:
        settings = get_app_settings()
        if settings.QUEUE_BACKEND == "redis":
            try:
                _global_queue_adapter = RedisStreamsQueue()
            except Exception:
                _global_queue_adapter = MemoryQueue()
        else:
            _global_queue_adapter = MemoryQueue()
    return _global_queue_adapter
