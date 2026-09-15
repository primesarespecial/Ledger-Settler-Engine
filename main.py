from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List
import hashlib
import json
import os
import subprocess

import redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel


app = FastAPI(title="NetFlow Ledger Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=6379,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


class BalanceEntry(BaseModel):
    entity: str
    balance: Decimal


class Connection(BaseModel):
    from_entity: str
    to_entity: str
    limit: Decimal


class SettlementRequest(BaseModel):
    batch_id: str
    balances: List[BalanceEntry]
    connections: List[Connection]


CENT = Decimal("0.01")


def money_to_paise(value: Decimal) -> int:
    try:
        value = value.quantize(
            CENT,
            rounding=ROUND_HALF_UP
        )
    except InvalidOperation:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid monetary value: {value}"
        )

    return int(value * 100)


def paise_to_rupees(value: int) -> str:
    amount = Decimal(value) / Decimal(100)
    return f"₹{amount:,.2f}"


def make_cache_key(payload: SettlementRequest) -> str:
    data = {
        "batch_id": payload.batch_id,
        "balances": [
            {
                "entity": item.entity.strip(),
                "balance": str(item.balance)
            }
            for item in payload.balances
        ],
        "connections": [
            {
                "from": item.from_entity.strip(),
                "to": item.to_entity.strip(),
                "limit": str(item.limit)
            }
            for item in payload.connections
        ]
    }

    raw = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":")
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()

    return f"settlement:{payload.batch_id}:{digest}"


@app.get("/")
def frontend():
    return FileResponse("/app/index.html")


@app.get("/health")
def health():
    try:
        redis_client.ping()
        redis_status = "ok"
    except redis.RedisError:
        redis_status = "unavailable"

    return {
        "status": "ok",
        "redis": redis_status,
        "solver": os.path.exists("/usr/local/bin/solver")
    }


@app.post("/api/v1/settle")
def settle(payload: SettlementRequest):
    batch_id = payload.batch_id.strip()

    if not batch_id:
        raise HTTPException(
            status_code=400,
            detail="batch_id cannot be empty"
        )

    if not payload.balances:
        raise HTTPException(
            status_code=400,
            detail="At least one person is required"
        )

    cache_key = make_cache_key(payload)

    try:
        cached = redis_client.get(cache_key)

        if cached:
            result = json.loads(cached)
            result["cache"] = "hit"
            return result

    except redis.RedisError as exc:
        print(f"Redis read error: {exc}")

    entity_to_id = {}
    id_to_entity = {}
    balances_paise = {}

    next_id = 1

    for item in payload.balances:
        name = item.entity.strip()

        if not name:
            raise HTTPException(
                status_code=400,
                detail="Entity name cannot be empty"
            )

        if name in entity_to_id:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate entity: {name}"
            )

        entity_to_id[name] = next_id
        id_to_entity[next_id] = name
        balances_paise[next_id] = money_to_paise(item.balance)

        next_id += 1

    num_nodes = len(entity_to_id)

    total_balance = sum(balances_paise.values())

    if total_balance != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "All balances must sum to zero.",
                "current_total": paise_to_rupees(total_balance)
            }
        )

    edges = []

    for connection in payload.connections:
        from_name = connection.from_entity.strip()
        to_name = connection.to_entity.strip()

        if from_name not in entity_to_id:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown entity: {from_name}"
            )

        if to_name not in entity_to_id:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown entity: {to_name}"
            )

        if from_name == to_name:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A payment connection cannot connect "
                    "a person to themselves"
                )
            )

        limit_paise = money_to_paise(connection.limit)

        if limit_paise < 0:
            raise HTTPException(
                status_code=400,
                detail="Connection limit cannot be negative"
            )

        edges.append({
            "from_id": entity_to_id[from_name],
            "to_id": entity_to_id[to_name],
            "limit": limit_paise,
            "from_name": from_name,
            "to_name": to_name
        })

    cpp_lines = [
        f"{num_nodes} {len(edges)}",
        " ".join(
            str(balances_paise[node])
            for node in range(1, num_nodes + 1)
        )
    ]

    for edge in edges:
        cpp_lines.append(
            f"{edge['from_id']} "
            f"{edge['to_id']} "
            f"{edge['limit']}"
        )

    cpp_input = "\n".join(cpp_lines) + "\n"

    try:
        process = subprocess.run(
            ["/usr/local/bin/solver"],
            input=cpp_input,
            text=True,
            capture_output=True,
            check=True,
            timeout=10
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=(
                "Solver was not found. "
                "Rebuild the Docker image."
            )
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="Settlement solver timed out"
        )

    except subprocess.CalledProcessError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Settlement solver failed",
                "stderr": exc.stderr,
                "stdout": exc.stdout
            }
        )

    output = process.stdout.strip()

    if not output:
        raise HTTPException(
            status_code=500,
            detail="Solver returned no output"
        )

    lines = output.splitlines()
    first = lines[0].split()

    if first[0] == "NOT_POSSIBLE":
        if len(first) != 3:
            raise HTTPException(
                status_code=500,
                detail="Malformed NOT_POSSIBLE response"
            )

        max_flow = int(first[1])
        required_flow = int(first[2])

        result = {
            "status": "not_possible",
            "feasible": False,
            "batch_id": batch_id,
            "required_clearance":
                paise_to_rupees(required_flow),
            "maximum_possible_clearance":
                paise_to_rupees(max_flow),
            "unresolved":
                paise_to_rupees(
                    required_flow - max_flow
                ),
            "assignments": [],
            "cache": "miss"
        }

        try:
            redis_client.setex(
                cache_key,
                3600,
                json.dumps(result)
            )
        except redis.RedisError:
            pass

        return result

    if first[0] != "POSSIBLE":
        raise HTTPException(
            status_code=500,
            detail=f"Unknown solver response: {lines[0]}"
        )

    if len(first) != 2:
        raise HTTPException(
            status_code=500,
            detail="Malformed POSSIBLE response"
        )

    required_flow = int(first[1])

    if len(lines) < 2:
        raise HTTPException(
            status_code=500,
            detail="Missing assignment information"
        )

    header = lines[1].split()

    if len(header) != 2 or header[0] != "ASSIGNMENTS":
        raise HTTPException(
            status_code=500,
            detail="Malformed assignment header"
        )

    expected_assignments = int(header[1])
    assignments = []

    for line in lines[2:]:
        parts = line.split()

        if len(parts) != 2:
            continue

        edge_index = int(parts[0])
        flow_paise = int(parts[1])

        if flow_paise <= 0:
            continue

        if edge_index < 0 or edge_index >= len(edges):
            raise HTTPException(
                status_code=500,
                detail="Solver returned invalid edge index"
            )

        edge = edges[edge_index]

        assignments.append({
            "from_entity": edge["from_name"],
            "to_entity": edge["to_name"],
            "amount": paise_to_rupees(flow_paise),
            "limit": paise_to_rupees(edge["limit"])
        })

    if len(assignments) != expected_assignments:
        print(
            f"Warning: expected {expected_assignments} assignments, "
            f"got {len(assignments)}"
        )

    result = {
        "status": "possible",
        "feasible": True,
        "batch_id": batch_id,
        "total_cleared":
            paise_to_rupees(required_flow),
        "assignments": assignments,
        "cache": "miss"
    }

    try:
        redis_client.setex(
            cache_key,
            3600,
            json.dumps(result)
        )
    except redis.RedisError:
        pass

    return result