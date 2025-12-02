Antiquity Atlas – Backend (Production)

This repository contains the production backend and AWS infrastructure for Antiquity Atlas — a history-sharing platform with geospatial posting, social connections, and content discovery.

🏛️ Architecture Overview

The backend exposes a single GraphQL API that integrates:

FastAPI + Strawberry GraphQL

PostgreSQL / PostGIS for historical site data

Neo4j for social graph + recommendations

Amazon S3 for media storage

Keycloak (OIDC) for authentication and user roles

AWS ECS Fargate for containerized backend deployment

AWS Secrets Manager for credentials and API secrets

AWS CDK (TypeScript) for all infrastructure-as-code

📁 Repository Structure
app/                  # Backend API code (FastAPI + Strawberry)
lib/                  # AWS CDK stacks (Compute, Data, Networking)
bin/                  # CDK entrypoints
keycloak-themes/      # Custom Keycloak login theme
Dockerfile            # Backend container image
package.json          # CDK dependencies
cdk.json              # CDK configuration

🚀 Deployment (AWS)

Deployment is handled entirely through AWS CDK.

1. Install dependencies
npm install

2. Bootstrap the environment
npx cdk bootstrap aws://<ACCOUNT>/<REGION>

3. Deploy the stacks
npx cdk deploy


The CDK stacks provision:

VPC + networking

ECS Fargate service running the backend container

Application Load Balancer (public API endpoint)

RDS PostgreSQL (with PostGIS extensions)

Neo4j instance

S3 bucket for images

Secrets Manager entries

Security groups and IAM roles

🔐 Authentication

Production authentication uses Keycloak.
Clients send JWT access tokens using:

Authorization: Bearer <token>


Roles (e.g., moderator) are enforced at the GraphQL resolver layer.

📌 Summary

This repository contains the production-ready backend and infrastructure for Antiquity Atlas:

GraphQL API

Geospatial + graph databases

Secure media storage

Fully managed AWS deployment via CDK