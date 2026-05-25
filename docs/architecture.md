# HetroServe Architecture

HetroServe is a vendor-neutral heterogeneous LLM inference platform that routes inference requests across multiple accelerator backends such as NVIDIA, AMD, Tenstorrent, and inference-specific chips.

This repository contains the Kubernetes deployment layer, router, mock backends, Redis queue path, KEDA autoscaling setup, and operational proof artifacts.

## Current Architecture

```mermaid
flowchart LR
    Client[Client / curl / API caller] --> Router[HetroServe Router]

    Router -->|GET /control| NvidiaControl[mock-nvidia /control]
    Router -->|GET /control| TTControl[mock-tenstorrent /control]

    Router -->|POST /epp/pick| Scorer[HetroServe Scorer]

    Scorer -->|routing decision| Router

    Router -->|enqueue job| Redis[(Redis)]
    Redis -->|consume queue:nvidia| NvidiaWorker[NVIDIA Worker]
    Redis -->|consume queue:tenstorrent| TTWorker[Tenstorrent Worker]

    NvidiaWorker --> NvidiaBackend[mock-nvidia]
    TTWorker --> TTBackend[mock-tenstorrent]

    NvidiaWorker -->|write result:job_id| Redis
    TTWorker -->|write result:job_id| Redis

    Router -->|return response| Client

    Router -->|metrics| Prometheus[Prometheus]
    Scorer -->|metrics| Prometheus
    Workers -->|metrics| Prometheus
    Redis -->|queue depth| KEDA[KEDA Redis Scaler]
    Prometheus --> Grafana[Grafana]
