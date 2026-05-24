# Contributing

Thanks for considering a contribution. This project is in early development — bug reports, feature requests, and PRs are all welcome.

## Quick start

1. Fork the repo and clone your fork.
2. Create a branch from `main`: `git checkout -b feat/your-change`.
3. Make your changes, with tests where appropriate.
4. Run the test suite locally (see below).
5. Open a PR against `main` with a clear description of the change and the motivation.

## Local development

Requirements: Python 3.11+, Docker, `kind`, `kubectl`.

```bash
# Set up a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies for each component
pip install -r router/requirements.txt
pip install -r mock-backend/requirements.txt
pip install -r benchmark/requirements.txt

# Install dev tools
pip install ruff yamllint
```

### Lint

```bash
ruff check .
yamllint -d "{rules: {line-length: disable, document-start: disable}}" k8s/
```

### Validate Kubernetes manifests

```bash
for f in k8s/base/*.yaml k8s/observability/*.yaml; do
  kubectl apply --dry-run=client -f "$f"
done
```

### End-to-end smoke test

```bash
# Spin up a local cluster
kind create cluster --name hetroserve-dev

# Build and load images
make build-images load-kind

# Apply manifests
kubectl apply -k k8s/base
kubectl apply -k k8s/observability

# Verify
./scripts/status.sh
```

## What we're looking for

Especially welcome contributions:

- **Bug fixes** — anything that doesn't work as documented
- **Real vLLM backend** — replacing one of the mock backends with a real vLLM pod to validate the end-to-end inference path
- **New accelerator classes** — adding AMD MI300X, Furiosa, Rebellions, d-Matrix, etc. with realistic cost/latency profiles
- **Benchmark scenarios** — realistic workload mixes (chat, RAG, long-context, mixed prompt/completion lengths)
- **Helm chart** — packaging the deployment for reuse outside kind
- **Documentation** — clearer architecture diagrams, more usage examples

## What requires discussion first

Please open an issue **before** writing code for:

- Breaking changes to the router's HTTP API
- Changes to the structure of benchmark output (CSV schema, metric names)
- New top-level directories or repositories
- Changes to the observability stack (Prometheus, Grafana) that affect existing dashboards

## Pull request expectations

- Lint-clean (`ruff check .` and `yamllint` passing)
- Conventional commit messages preferred: `feat:`, `fix:`, `docs:`, `chore:`, `ci:`
- Update the README or other docs if behavior changes
- Squash commits before merging (rebase squash, not merge commits)

## Code of conduct

Be kind. Assume good intent. Critique the code, not the person. Disagreements are resolved by clearly stating tradeoffs and inviting discussion, not by escalation.

## License

By contributing, you agree your contributions will be licensed under Apache 2.0, the same license as the project.
