import os

from runic import context
from runic.adapters import create_adapter

adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)
context.configure(adapter)
