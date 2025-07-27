from app import db

class Neo4jAdapter:
    # Handles Neo4j queries related to site relationships.

    def __init__(self):
        self.driver = db.get_neo4j_driver()

    def get_connected_sites(self, site_id: int):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:Site {id: $id})-[:CONNECTED_TO]->(connected:Site)
                RETURN connected.id AS id, connected.name AS name
            """, {"id": site_id})

            return [{"id": r["id"], "name": r["name"]} for r in result]
