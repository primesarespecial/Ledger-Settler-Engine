from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import redis
import psycopg2

app = FastAPI(title="NetFlow Ledger Engine")

# Initialize Redis & Postgres connections from environment variables
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
POSTGRES_URL = os.getenv("DATABASE_URL", "postgresql://admin:password@localhost:5432/netflow")

redis_client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

class Transaction(BaseModel):
    from_entity: str
    to_entity: str
    amount: float

class BatchRequest(BaseModel):
    batch_id: str
    transactions: list[Transaction]

@app.post("/api/v1/settle")
def settle_ledger(payload: BatchRequest):
    # Check Redis cache to see if batch was already processed
    cached_res = redis_client.get(payload.batch_id)
    if cached_res:
        return {"status": "cached", "result": cached_res}

    # Map string names to integer nodes for the C++ graph
    entities = {}
    idx = 1
    for tx in payload.transactions:
        if tx.from_entity not in entities:
            entities[tx.from_entity] = idx
            idx += 1
        if tx.to_entity not in entities:
            entities[tx.to_entity] = idx
            idx += 1

    num_nodes = len(entities)
    edges_data = []
    for tx in payload.transactions:
        u = entities[tx.from_entity]
        v = entities[tx.to_entity]
        edges_data.append(f"{u} {v} {tx.amount}")

    cpp_input = f"{num_nodes} {len(edges_data)}\n" + "\n".join(edges_data) + "\n"

    try:
        # Execute the compiled C++ Dinic solver binary
        process = subprocess.run(
            ["./solver"],
            input=cpp_input,
            text=True,
            capture_output=True,
            check=True
        )
        resolved_capacity = process.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"C++ Engine Error: {e.stderr}")

    result_data = {
        "batch_id": payload.batch_id,
        "nodes_processed": num_nodes,
        "max_netted_capacity": resolved_capacity
    }

    # Cache result in Redis for fast retrieval
    redis_client.set(payload.batch_id, resolved_capacity)

    return {"status": "success", "data": result_data}