# Vulnerable original (unmodified)

Exact copy of the upstream ledger-api-assignment source, untouched.
Used as:
1. The authorized Task 4B pentest target (`docker run -p 8080:8080 ...` locally, outside the hardened cluster).
2. The "before" baseline for the Task 2 Trivy/dependency-scan comparison.

Do NOT deploy this to the cluster. The hardened, deployed image lives at `../Dockerfile` / `../app.py`.
