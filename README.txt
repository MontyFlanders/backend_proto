# Antiquity Atlas – Backend & API

**Antiquity Atlas** is the backend service for a social media-based history sharing app. It enables users to share historical sites, vote on their authenticity, and discover new places through a recommendation engine.

This backend was built from the ground up to support a scalable front-end, using modern cloud-native architecture and graph-based relationships for historical data.

--- 

## 🚀 Features
- **Unified GraphQL API** – Query Neo4j (graph DB), PostGIS (geo-data), and AWS S3 in a single request.
- **Recommendation Engine** – Powered by Neo4j to suggest historical sites based on user interactions.
- **Planned Authentication** – AWS Cognito integration for secure user management in production.
- **Geo-Query Optimization** – PostGIS with custom indexing for efficient location-based lookups.
- **Serverless & Scalable** – FastAPI backend deployed on AWS Lambda for cost-effective scaling.
- **Automated Content Population** – Scraped 2,500+ historical sites from U.S. National Parks and archives.
- **Dockerized Deployment** – All services containerized for smooth development and CI/CD workflows.

---

## 🛠 Tech Stack
- **Frameworks:** FastAPI, GraphQL (Ariadne)
- **Databases:** Neo4j, PostgreSQL + PostGIS
- **Cloud:** AWS Lambda, AWS S3, AWS Cognito (planned)
- **Containerization:** Docker
- **Languages:** Python 3
- **Other Tools:** pytest, GitHub Actions (optional for CI)

---

## 📂 Project Structure
├── app/
│ ├── main.py # FastAPI entry point
│ ├── api/ # GraphQL and REST endpoints
│ ├── services/ # Business logic and DB interactions
│ ├── schemas/ # Pydantic models
│ └── tests/ # pytest-based test suite
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md---

## ⚙️ Setup Instructions

### **Prerequisites**
- Docker and Docker Compose
- Python 3.10+
- An AWS account (optional for future cloud features)

### **Local Development**
```bash
# Clone the repo
git clone https://github.com/YourUsername/antiquity-atlas-backend.git
cd antiquity-atlas-backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload

# Docker
docker build -t antiquity-backend .
docker-compose up
The backend will be available at:
http://localhost:8000/graphql (GraphQL Playground)

📊 API Highlights
GraphQL Queries: Aggregate data from Neo4j, PostGIS, and AWS S3.

Geo Queries: Example:

graphql
Copy
Edit
{
  nearbySites(lat: 40.7128, lon: -74.0060, radiusKm: 10) {
    name
    description
  }
}

📜 About This Project
This backend is part of my senior capstone project at the University of Utah, built to demonstrate real-world, production-ready backend development.
Role: Lead backend developer, responsible for architecture, database design, API implementation, and AWS deployment.

🔗 Links
Author: Patrick West

GitHub: Antiquity Atlas Backend

🧪 Future Improvements
Integrate AWS Cognito for secure authentication.

Add caching layers (Redis) for frequently accessed queries.

Expand CI/CD with GitHub Actions for automated deployment.

Add rate limiting and advanced logging for production-grade scaling.

