import asyncpg
from neo4j import GraphDatabase
from app import config

# connect to pg

async def get_pg_conn():
    return await asyncpg.connect(
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        host=config.DB_HOST,
        port=config.DB_PORT
    )

# connect to neo

def get_neo4j_driver():
    return GraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
    )
