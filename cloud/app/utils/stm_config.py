"""Short-term-memory size/TTL constants.

STM lives in MongoDB (`app.agent.graph.graph._stm_load` / `_stm_save`). These two
constants are all that's shared: `graph.py` imports them — TTL drives the Mongo
TTL index on the STM docs, the count caps the stored history.
"""

STM_TTL = 60 * 60 * 24 * 30  # 30 days (drives the MongoDB TTL index on STM docs)
MAX_STM_MESSAGES = 10
