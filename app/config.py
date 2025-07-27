import os
from dotenv import load_dotenv

# load the environment file dynamically
load_dotenv(os.getenv("ENV_FILE", ".env.local"))

# PostgreSQL Config
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# Neo4j Config
NEO4J_URI = os.getenv("DB_NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# Environment Name (optional)
ENVIRONMENT = os.getenv("ENVIRONMENT", "local")
