# GCP deployment path for Riverbend (Infrastructure-as-Code sketch).
#
# This is a written plan expressed as Terraform, not a live-deployed stack (no
# cloud credits were used). It names the services and wires the key relationships;
# a few resources (VPC connector, IAM bindings, container image build/push) are
# intentionally elided and called out in comments to keep it to the essentials.
#
# Mapping from the local prototype:
#   docker api        -> Cloud Run service "api"
#   docker worker     -> Cloud Run service "worker"
#   docker db         -> Cloud SQL (Postgres)
#   outbox + poller   -> Cloud Tasks (push to worker) + Cloud Scheduler
#   .env secrets      -> Secret Manager

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "image" {
  type = string # built & pushed to Artifact Registry in CI
}

# ---------------------------------------------------------------------------
# Secrets — never in code. OPENAI_API_KEY and the DB password live here.
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "openai_api_key" {
  secret_id = "openai-api-key"
  replication { auto {} }
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-app-password"
  replication { auto {} }
}

# ---------------------------------------------------------------------------
# Cloud SQL (Postgres) — RLS is a Postgres feature, so tenancy carries over
# unchanged. The app connects as a non-superuser role (created by migrate job).
# ---------------------------------------------------------------------------
resource "google_sql_database_instance" "pg" {
  name             = "riverbend-pg"
  database_version = "POSTGRES_16"
  settings {
    tier = "db-custom-1-3840"
    ip_configuration { ipv4_enabled = false } # private IP via VPC connector
  }
  deletion_protection = true
}

resource "google_sql_database" "db" {
  name     = "riverbend"
  instance = google_sql_database_instance.pg.name
}

# ---------------------------------------------------------------------------
# Cloud Tasks — replaces the local outbox. Native retry/backoff, rate limiting
# (maps to the spend cap / backpressure), and task-name dedup (idempotency).
# One queue; per-shop queues are the 100-shop scaling move (see NOT_BUILT).
# ---------------------------------------------------------------------------
resource "google_cloud_tasks_queue" "process" {
  name     = "process"
  location = var.region
  retry_config {
    max_attempts  = 5
    min_backoff   = "2s"
    max_backoff   = "60s"
  }
  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 20
  }
}

# ---------------------------------------------------------------------------
# Cloud Run — API (public) and Worker (receives Cloud Tasks pushes). Both run
# the SAME image as local, different commands. Secrets + DB URL injected as env.
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "api" {
  name     = "riverbend-api"
  location = var.region
  template {
    containers {
      image   = var.image
      command = ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"]
      env {
        name = "OPENAI_API_KEY"
        value_source { secret_key_ref {
          secret  = google_secret_manager_secret.openai_api_key.secret_id
          version = "latest"
        } }
      }
      # DATABASE_URL built from the Cloud SQL private IP + db_password secret.
    }
    # vpc_access { connector = ... } for private Cloud SQL
  }
}

resource "google_cloud_run_v2_service" "worker" {
  name     = "riverbend-worker"
  location = var.region
  # Ingress restricted to Cloud Tasks (OIDC-authenticated push). The worker
  # exposes an HTTP handler that runs one job per request instead of polling.
  template {
    containers {
      image   = var.image
      command = ["uvicorn", "app.worker_http:app", "--host", "0.0.0.0", "--port", "8080"]
      # same secret/env wiring as api
    }
  }
}

# ---------------------------------------------------------------------------
# Cloud Scheduler — monthly spend-cap reset / reconciliation tick.
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "monthly_reset" {
  name     = "spend-cap-reset"
  schedule = "0 0 1 * *" # 00:00 on the 1st
  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/reset-caps"
    http_method = "POST"
    # oidc_token for authenticated internal call
  }
}

# NOTE for the reader: going live also needs Artifact Registry + CI build/push,
# a VPC connector for private Cloud SQL, a one-shot migrate job (Cloud Run Job
# running `python -m scripts.init_db`), and IAM service accounts binding
# Cloud Tasks -> worker and Scheduler -> api. Omitted here to keep the plan legible.
