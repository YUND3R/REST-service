# Security policy

## Supported versions

We address security fixes for the latest commit on the default branch. Tag releases when possible.

## Reporting a vulnerability

Please **do not** open a public issue for security-sensitive reports.

Instead, contact maintainers privately (e.g. enable **GitHub Private vulnerability reporting** for the repository, or use an email listed in the repository profile).

Include:

- Description of the issue and impact  
- Steps to reproduce  
- Affected component (gateway / workers / infra)  
- Optional: suggested fix or patch  

We aim to acknowledge within a few business days.

## Operational hardening (production checklist)

- Replace demo API keys (`001_schema.sql` seed) and **rotate** `platforms.api_key` regularly.  
- Use strong `POSTGRES_PASSWORD` and restrict DB/Redis to private networks (remove public port mappings in `docker-compose` where not needed).  
- Set `DOCS_ENABLED=false` and expose `/docs` only on internal networks.  
- Restrict `CORS_ORIGINS` to known LMS origins (avoid `*` in production).  
- Terminate TLS at a reverse proxy or load balancer in front of Nginx.  
- For Hugging Face model pulls in private environments, use `HF_TOKEN` with minimal scope and store in an enterprise secret store.  

## Out of scope

- Misconfiguration of cloud IAM, VPC, or third-party SaaS outside this repository.
