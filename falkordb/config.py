from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FalkorDBSettings:
    host: str = "localhost"
    port: int = 6379
    graph_name: str = "voyager"
    username: str | None = None
    password: str | None = None
    index_poll_interval: float = 0.5
    index_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> FalkorDBSettings:
        return cls(
            host=os.getenv("FALKORDB_HOST", cls.host),
            port=int(os.getenv("FALKORDB_PORT", str(cls.port))),
            graph_name=os.getenv("FALKORDB_GRAPH", cls.graph_name),
            username=os.getenv("FALKORDB_USERNAME") or None,
            password=os.getenv("FALKORDB_PASSWORD") or None,
            index_poll_interval=float(
                os.getenv(
                    "FALKORDB_INDEX_POLL_INTERVAL",
                    str(cls.index_poll_interval),
                )
            ),
            index_timeout=float(
                os.getenv("FALKORDB_INDEX_TIMEOUT", str(cls.index_timeout))
            ),
        )
