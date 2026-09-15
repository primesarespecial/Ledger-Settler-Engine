# Ledger Settler Engine

Ledger Settler Engine finds a way to clear a set of net debts while respecting limits on who can pay whom.

Each person has a net balance:
- Negative balance means they need to pay.
- Positive balance means they need to receive.
- Balances must sum to zero.

Person-to-person payment limits are represented as directed edges. The problem is modeled as a maximum flow network using a super-source and super-sink, and Dinic's algorithm is used to find a valid settlement.

If the required flow can be achieved, the program returns a payment assignment. Otherwise, it reports that the debt cannot be completely cleared under the given limits.

The project uses C++ for the flow solver, FastAPI for the backend, Redis for caching, and a simple HTML/CSS/JavaScript frontend.