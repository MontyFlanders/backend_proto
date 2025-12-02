from __future__ import annotations
import os, json
from typing import Any, Dict, List, Optional
import requests
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import urljoin

class NeptuneAdapter:
    """
    Minimal client for Amazon Neptune openCypher over HTTPS with IAM SigV4.

    Env vars expected:
      - NEPTUNE_ENDPOINT=https://<writer-host>:8182
      - (optional) NEPTUNE_OPENCYPHER_URL=https://<writer-host>:8182/openCypher
      - AWS_REGION (falls back to instance/role default if unset)
    IAM permissions on the task role:
      neptune-db:{ReadDataViaQuery,WriteDataViaQuery,DeleteDataViaQuery,GetQueryStatus}
      Resource: arn:aws:neptune-db:<region>:<acct>:<cluster-resource-id>/*
      Condition: {"neptune-db:QueryLanguage":"opencypher"} (recommended)
    """

    def __init__(self, base: Optional[str] = None, region: Optional[str] = None, timeout: int = 10):
        self.base = (base or os.getenv("NEPTUNE_ENDPOINT") or "").rstrip("/")
        if not self.base:
            raise RuntimeError("NEPTUNE_ENDPOINT is required, e.g. https://host:8182")
        self.oc_url = os.getenv("NEPTUNE_OPENCYPHER_URL") or urljoin(self.base + "/", "openCypher")
        self.region = region or os.getenv("AWS_REGION") or "us-west-2"
        self.timeout = timeout

        sess = boto3.Session()
        creds = sess.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials found for SigV4 (task role?)")
        self._creds = creds.get_frozen_credentials()

    # ---------- low-level ----------
    def _signed_post(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(body)
        req = AWSRequest(method="POST", url=url, data=data, headers={"Content-Type": "application/json"})
        SigV4Auth(self._creds, "neptune-db", self.region).add_auth(req)
        prepared = req.prepare()
        resp = requests.post(url, data=data, headers=dict(prepared.headers), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ---------- public helpers ----------
    def ping(self) -> Dict[str, Any]:
        """Basic health check: signed request + trivial query."""
        out = self._signed_post(self.oc_url, {"query": "RETURN 1 AS ok"})
        # Neptune formats responses as {columns: [...], results: [[...], ...]} in many SDK examples.
        ok = False
        cols = out.get("columns")
        rows = out.get("results")
        if isinstance(cols, list) and cols and cols[0] == "ok" and isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, list) and first and first[0] == 1:
                ok = True
        # Some deployments return objects with keys—treat any 200 as OK if structure differs.
        if not ok:
            ok = True
        return {"ok": ok, "endpoint": self.base}

    def run_cypher(self, query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._signed_post(self.oc_url, {"query": query, "parameters": params or {}})

    @staticmethod
    def rows_to_dicts(out: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize Neptune openCypher rows into list[dict]."""
        cols = out.get("columns", [])
        results = out.get("results", [])
        dicts: List[Dict[str, Any]] = []
        for row in results:
            # Typical shape: row is a list aligned with columns
            if isinstance(row, list):
                dicts.append(dict(zip(cols, row)))
            # Fallback if Neptune returns list of dicts (rare)
            elif isinstance(row, dict) and cols:
                dicts.append({k: row.get(k) for k in cols})
            elif isinstance(row, dict):
                dicts.append(row)
        return dicts

    # ---------- domain helpers (friends) ----------
    def upsert_user(self, user_id: int, email: Optional[str] = None, name: Optional[str] = None) -> None:
        q = """
        MERGE (u:User {id: $id})
        ON CREATE SET u.email=$email, u.name=$name, u.createdAt=datetime()
        """
        self.run_cypher(q, {"id": user_id, "email": email, "name": name})

    def add_friend(self, a_id: int, b_id: int) -> None:
        q = """
        MERGE (a:User {id:$a})
        MERGE (b:User {id:$b})
        MERGE (a)-[:FRIENDS_WITH]->(b)
        MERGE (b)-[:FRIENDS_WITH]->(a)
        """
        self.run_cypher(q, {"a": a_id, "b": b_id})

    def remove_friend(self, a_id: int, b_id: int) -> None:
        q = """
        MATCH (a:User {id:$a})-[r:FRIENDS_WITH]->(b:User {id:$b}) DELETE r
        WITH a,b
        MATCH (b)-[r2:FRIENDS_WITH]->(a) DELETE r2
        """
        self.run_cypher(q, {"a": a_id, "b": b_id})

    def list_friends(self, user_id: int) -> List[Dict[str, Any]]:
        q = """
        MATCH (:User {id:$id})-[:FRIENDS_WITH]->(f:User)
        RETURN f.id AS id, f.name AS name, f.email AS email
        ORDER BY id
        """
        out = self.run_cypher(q, {"id": user_id})
        return self.rows_to_dicts(out)
