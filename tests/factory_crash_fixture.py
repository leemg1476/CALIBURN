"""Child-process fixture: die after durable proposal but before the tool checkpoint."""

import os
import sys

from caliburn.runtime.store import Store
from caliburn.tool_factory.contracts import Proposal
from caliburn.tool_factory.service import Factory

store = Store(os.environ["CALIBURN_DATABASE_URL"])
task = store.claim("factory-crash-fixture", 30)
call = task["messages"][-1]["tool_calls"][0]
step = store.prepare(task["id"], task["lease_token"], "TOOL", call)
value = Proposal.model_validate_json(call["function"]["arguments"])
Factory(store).propose(task["id"], task["lease_token"], step["id"], value)
sys.stdout.flush()
os._exit(73)
