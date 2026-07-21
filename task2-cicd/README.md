# Task 2 — Secure CI/CD Pipeline & Supply Chain

## Pipeline (`.github/workflows/ci.yml`)

```
push/PR --> gitleaks --> semgrep (SAST) --> trivy fs (dep CVEs)
        --> docker build+push GHCR --> trivy image scan
        --> cosign sign (keyless) --> SLSA provenance attestation
        --> cosign verify --> bump image digest in gitops/ --> ArgoCD syncs
```

Every scanning step uploads SARIF to the repo's Security tab
(`github/codeql-action/upload-sarif`). Each gate is implemented as a direct CLI
invocation (install the tool, run it, produce SARIF, enforce the fail policy) rather
than depending on third-party GitHub Actions wrappers, for full control over exactly
what's scanned and what the pass/fail condition is.

## Fail-policy matrix

| Gate | Tool | Hard-blocks the build | Warns only |
|---|---|---|---|
| Secrets | gitleaks | **Any** finding not covered by `.gitleaks.toml`'s documented, justified allowlist entries (SealedSecret ciphertext; a known placeholder value quoted as pentest evidence) | — |
| SAST | Semgrep (`p/python`, `p/flask`, `p/security-audit`) | High/Critical — e.g. `yaml.load()` without a safe Loader, unvalidated outbound request destination | Medium/Low |
| Dependency CVEs | Trivy `fs` | Critical/High **with a fix available** | Critical/High with no fix (see `.trivyignore` below), Medium and under |
| Image CVEs | Trivy `image` | Same policy, applied to the built image (also catches base-image CVEs the fs scan can't see) | Same |
| Signature | `cosign verify` (Kyverno `require-signed-images`, Task 1) | Unsigned image can never reach the `payments` namespace | — |

### Handling a CVE with no fix yet

Not blocked indefinitely and not silently ignored either. Added to
`.trivyignore` with a mandatory comment block: CVE ID, date found, reason
(specific to this app, not generic), owning team, and a review-by date. All
current entries are Debian OS-package CVEs in the base image with no upstream fix
yet, verified against the actual application code to confirm the affected package
isn't reachable through this app's attack surface (e.g. Perl and SQLite CVEs — this
app invokes neither).

## Cosign keyless signing

No long-lived signing key exists anywhere in this pipeline. GitHub Actions' OIDC
token is exchanged for a short-lived certificate from Sigstore's Fulcio CA, the
signature is logged in the public Rekor transparency log, and `cosign verify`
checks the signature against the exact workflow identity:

```
--certificate-identity-regexp "^https://github.com/NandhaReddy8/devsecops-dodo/.github/workflows/ci.yml@refs/heads/main$"
--certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Kyverno's `require-signed-images` policy (`task1-hardening/policies/require-signed-images.yaml`)
verifies against this exact identity and is set to **Enforce** — see that file's
header for the sequencing rationale (it started in Audit mode until a real
signature existed).

## GitOps (ArgoCD)

`gitops/argocd/application.yaml` points ArgoCD at
`gitops/argocd/overlays/dev`, which layers an image-digest override on top
of `task1-hardening/base`. `syncPolicy.automated` sets both `prune: true`
and `selfHeal: true` — drift detection and self-heal: any manual
`kubectl edit`/`kubectl delete` against a resource ArgoCD owns is reverted back to
the git-declared state on the next reconciliation loop.

ArgoCD itself is installed and verified healthy in-cluster
(`kubectl -n argocd get pods`). A fully local (no-GitHub) proof of the live
sync/self-heal loop is listed as follow-up work in the top-level README — it
requires a proper git smart-HTTP server as the local source, which wasn't set up
in this pass.

## Reproduce

```bash
helm install kyverno kyverno/kyverno -n kyverno --create-namespace   # Task 1
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl apply -f gitops/argocd/application.yaml
```

CI/CD runs automatically on push to `main` via `.github/workflows/ci.yml` — see
GitHub Actions for run history and logs.
