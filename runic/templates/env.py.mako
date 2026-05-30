import os

from falkordb import FalkorDB
from runic import context

FALKORDB_URL = os.getenv("FALKORDB_URL", "falkor://localhost:6379")
FALKORDB_GRAPH = os.getenv("FALKORDB_GRAPH", "my_graph")

db = FalkorDB.from_url(FALKORDB_URL)
graph = db.select_graph(FALKORDB_GRAPH)
context.configure(connection=db, graph=graph)
