# Phase 4 — MLOps: Containerize & Deploy the RAG Agent

Takes the [Phase 3 RAG support agent](../phase3-rag-support-agent) from a script you run locally to a containerized service you can run anywhere — and optionally deploy as a monitored, publicly reachable AWS ECS Fargate service. Containerization, secrets management, and IAM are done directly against Docker/AWS primitives, no Terraform or managed PaaS abstraction, so you can see exactly what each piece is doing.

This is part of a larger [self-directed AI engineering roadmap](../README.md); this folder is self-contained enough to build and run on its own, against your own API keys and your own embeddings.

## What this does

- Packages the Phase 3 agent (`fastAPI/api.py`, `Agent/`, `RAG/`) into a container that serves `POST /ask` via `uvicorn`
- Injects secrets (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`) at **runtime**, never bakes them into an image layer
- Ships two Dockerfiles — one for local dev, one for deployment — because the two environments have genuinely different constraints (see [below](#why-two-dockerfiles-dev-vs-prod))
- Optionally deploys the image to AWS ECS Fargate behind Secrets Manager + IAM, reachable over a public IP

## Repository layout

| Path | Purpose |
| --- | --- |
| `RAGApp-dev.dockerfile` | Local image — `chroma_store/` is bind-mounted from the host at `docker run` time |
| `RAGApp-prod.dockerfile` | Deployment image — `chroma_store/` is `COPY`'d in, since a deployed container has no host filesystem to mount |
| `iam/ecs-trust-policy.json` | Trust policy shared by both ECS IAM roles |
| `iam/execution-role-secrets-policy.json` | Inline policy granting the execution role read access to the two secrets |

## Prerequisites

- Docker Desktop installed and running (`docker info` should succeed, not just `docker --version`)
- This repository cloned in full — the Dockerfiles `COPY` files from `../phase3-rag-support-agent/`, so they need that sibling folder present, not just this one
- Your own API keys: an [Anthropic API key](https://console.anthropic.com/) and a [Voyage AI API key](https://dash.voyageai.com/)
- Python 3.9+ and `pip`, to build your own embeddings before containerizing (the vector index isn't committed to the repo — you generate it locally)
- For the AWS section only: an AWS account and the AWS CLI, configured (`aws configure`) with an IAM user (not root) that has console + programmatic access

## Quickstart: run it locally

**1. Set up the Phase 3 project and build your own vector store.** The container serves whatever is in `chroma_store/` — you generate that yourself from the committed corpus, so it's never someone else's stale embeddings:

```bash
cd phase3-rag-support-agent
pip install -r requirements.txt
cp .env.example .env               # fill in your ANTHROPIC_API_KEY and VOYAGE_API_KEY
python RAG/ingest_semantic.py      # chunk + embed corpus/ into chroma_store/
cd ..
```

**2. Build the image**, from the repo root (see [why the build context is the repo root](#why-the-build-context-is-the-repo-root-not-this-folder)):

```bash
docker build -f phase4-MLOps/RAGApp-dev.dockerfile -t rag-agent .
```

**3. Run it** — secrets via `--env-file`, `chroma_store/` mounted from the host:

```bash
docker run -d --name rag-agent \
  --env-file phase3-rag-support-agent/.env \
  -v "$(pwd)/phase3-rag-support-agent/chroma_store:/app/chroma_store" \
  -p 8000:5000 \
  rag-agent

docker logs rag-agent   # confirm it's up
```

**4. Test it**, the same way you'd hit the Phase 3 API directly:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I define a path parameter with type validation in FastAPI?"}'
```

You should get back a grounded answer with `docs_source` citations. An out-of-scope question should get a clean refusal (`"No results found in the documentation."`), not a hallucinated answer — containerizing shouldn't change RAG behavior.

**5. Tear down:**

```bash
docker rm -f rag-agent
```

### Verifying secrets never leaked into the image

`docker history` alone isn't sufficient proof — it only shows each layer's *instruction text*, not file contents, so it wouldn't catch a secret file that got `COPY`'d in some other way. Check both:

```bash
# No ENV instruction should reference the keys directly
docker history rag-agent

# No .env file should exist anywhere in the running container's filesystem
docker exec rag-agent find / -maxdepth 4 -iname "*.env"

# The keys SHOULD be present as runtime env vars (this is expected — they got
# in via --env-file at `docker run`, not baked into a layer)
docker exec rag-agent env | grep -E "ANTHROPIC|VOYAGE"
```

## Why the build context is the repo root, not this folder

The Dockerfiles live at `phase4-MLOps/RAGApp-dev.dockerfile` and `phase4-MLOps/RAGApp-prod.dockerfile`, but they `COPY` files from `../phase3-rag-support-agent/`. Docker's `COPY` can only reach files *inside* the build context — it can't follow `../` out of it. Rather than moving the Dockerfile to the repo root (which would break the phase-by-phase folder layout), the build context is set to the repo root explicitly, and the Dockerfile's location is passed separately via `-f`:

```bash
# run from the repo root
docker build -f phase4-MLOps/RAGApp-dev.dockerfile -t rag-agent .
```

The trailing `.` is the context (repo root); `-f` just tells Docker where the Dockerfile file itself sits. This is also why `.dockerignore` lives at the **repo root**, not in `phase4-MLOps/` — Docker only reads a `.dockerignore` at the root of the build context.

## Why two Dockerfiles (dev vs. prod)

The "bake it in or mount it?" question doesn't have one universal answer — it depends on whether a host filesystem exists to mount *from*.

- **Locally**, your machine is that host: `docker run -v $(pwd)/.../chroma_store:/app/chroma_store` mounts live disk state into the container, so re-running `ingest_semantic.py` is immediately visible without a rebuild, and a rebuild can never accidentally serve embeddings older than what's on disk.
- **Deployed to Fargate**, there's no host you control to mount from — Fargate provisions the container on infrastructure you never touch, and there's no ongoing local editing/re-ingesting happening against a running deployed task the way there is in dev. Updating the corpus in production is already a deliberate, versioned act (rebuild → push → redeploy), not a background side effect. So `RAGApp-prod.dockerfile` bakes `chroma_store/` in with a plain `COPY`, and each image becomes a self-contained, reproducible artifact — anyone can `docker run` it and get exactly the same answers, with no separate "did you remember to also copy the index over" step.

**The `COPY` wildcard gotcha to know about if you touch this again:** `COPY chroma_store/* dest` and `COPY chroma_store/ dest/` are *not* equivalent. Docker's rule for `COPY <src> <dst>` is: if `<src>` is a directory, its *contents* get copied, not the directory itself. A wildcard (`chroma_store/*`) expands to multiple source paths — one per matched entry — and that flattening rule applies separately to *each* one. Chroma persists each collection under its own UUID-named subdirectory, and those subdirectories all contain identically-named files (`data_level0.bin`, `header.bin`, etc.). With the wildcard form, each UUID folder's *contents* get dumped straight into the destination, and the second folder processed silently overwrites the first's files — no error, just a Chroma collection quietly missing (`NotFoundError: Collection [...] does not exist` at query time, not at build time). Use the no-wildcard form (`COPY chroma_store/ /app/chroma_store/`) so the flattening happens exactly once, preserving the UUID subdirectories.

## Design notes (local image)

- **`chroma_store/` is mounted in dev, not `COPY`'d.** If it were baked into the dev image, re-running `ingest_semantic.py` on the host would leave any already-running container serving the old embeddings — no error, no warning, just quietly stale answers. Mounting means the container always reads whatever's on disk right now.
- **Dependency install is a separate, earlier layer from the code copy.** `COPY requirements.txt .` + `pip install` happens before `COPY` of `RAG/`/`Agent/`/`fastAPI/`, so editing application code doesn't invalidate (and re-run) the dependency install layer on every rebuild.
- **`.dockerignore` excludes by reason.** Each entry maps to a concrete concern: `.env`/`*.json` are real secrets (the latter because `calendar-agent/credentials.json` and `token.json` live elsewhere in this monorepo and would otherwise ride along in the build context sent to the Docker daemon); `.venv/` and `.git/` are excluded for context-transfer size/hygiene, not because they're sensitive. `chroma_store/` is deliberately **not** excluded — the dev Dockerfile never `COPY`s it (it's mounted instead) so its presence in the build context is inert there, but the prod Dockerfile needs it available to `COPY` in.

---

## Deploying to AWS (ECS Fargate)

Optional, and independent of the local Quickstart above. This section is intentionally a runbook — ECR auth and IAM trust-policy JSON are standard reference mechanics, not something worth deriving from first principles. The one part worth actually understanding is the IAM structure: why there are two roles, and why the secrets policy needs two separate statements.

**What gets built:** an ECR repository holding the `rag-agent:prod` image → two IAM roles (execution + task) → two Secrets Manager secrets → an ECS cluster running one Fargate service, reachable on a public IP over port 5000.

Every command below uses placeholders (`<...>`) — substitute your own region, account ID, VPC/subnet IDs, and secret values throughout.

### 1. Build the production image

The prod Dockerfile bakes `chroma_store/` in, so it needs the vector store already built (see Quickstart step 1):

```bash
docker build -f phase4-MLOps/RAGApp-prod.dockerfile -t rag-agent:prod .
```

### 2. Push the image to ECR

```bash
aws ecr create-repository --repository-name rag-agent --region <region>
```

Authenticate Docker against ECR. `aws ecr get-login-password` mints a **short-lived (12-hour) token** from your live IAM credentials — it's not a static password, by design, so a leaked token expires on its own:

```bash
aws ecr get-login-password --region <region> \
  | docker login --username AWS --password-stdin <account_id>.dkr.ecr.<region>.amazonaws.com
```

Re-authenticating by hand every 12 hours gets old fast. Install `docker-credential-ecr-login` and scope it to just your ECR registry in `~/.docker/config.json`, so Docker silently refreshes the token for you:

```json
{
  "credHelpers": {
    "<account_id>.dkr.ecr.<region>.amazonaws.com": "ecr-login"
  }
}
```

Tag and push:

```bash
docker tag rag-agent:prod <account_id>.dkr.ecr.<region>.amazonaws.com/rag-agent:prod
docker push <account_id>.dkr.ecr.<region>.amazonaws.com/rag-agent:prod
```

### 3. Create secrets and IAM roles

**Create the secrets:**

```bash
aws secretsmanager create-secret --name rag-agent/anthropic-api-key \
  --secret-string "<your ANTHROPIC_API_KEY>" --region <region>
aws secretsmanager create-secret --name rag-agent/voyage-api-key \
  --secret-string "<your VOYAGE_API_KEY>" --region <region>
```

Note the **full ARN** each command returns (e.g. `...secret:rag-agent/anthropic-api-key-iJU2R5`) — AWS appends a random 6-character suffix, and later steps need the exact ARN, not the bare secret name.

**Why two IAM roles, not one:** ECS tasks use two separate roles because they're assumed by two different actors, at two different points in the container's lifecycle.

- **Execution role** — assumed by the ECS agent/control-plane infrastructure, *before* your application code runs, to bootstrap the container: pull the image from ECR, resolve `secrets[]` from Secrets Manager, and set up the CloudWatch log stream. Its credentials are never exposed inside the running container.
- **Task role** — assumed by your application code, exposed inside the running container via the Fargate metadata endpoint (`169.254.170.2`, `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`). Anything that gets code execution inside the container — your app, or an attacker exploiting a vulnerability in it — can reach these credentials.

That split is the actual security boundary: scope the execution role to "infrastructure bootstrap" permissions only, and the task role to whatever the *app itself* legitimately needs to call at runtime. This app calls none — Anthropic/Voyage are called with API keys injected as env vars, not via AWS SDK calls — so the task role here is created with zero attached permissions.

**Trust policy** (answers "who can assume this role" — both roles are assumed by the same service, so they share one, `iam/ecs-trust-policy.json`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

```bash
aws iam create-role --role-name rag-agent-execution-role \
  --assume-role-policy-document file://iam/ecs-trust-policy.json
aws iam create-role --role-name rag-agent-task-role \
  --assume-role-policy-document file://iam/ecs-trust-policy.json
```

**Execution role permissions.** Attach AWS's managed policy for the baseline (ECR pull + CloudWatch Logs write, `Resource: "*"`):

```bash
aws iam attach-role-policy --role-name rag-agent-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

That managed policy does **not** cover Secrets Manager. Add a scoped inline policy for that (`iam/execution-role-secrets-policy.json`) — and note it needs **two separate statements**, not one:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": [
        "arn:aws:secretsmanager:<region>:<account_id>:secret:rag-agent/anthropic-api-key-XXXXXX",
        "arn:aws:secretsmanager:<region>:<account_id>:secret:rag-agent/voyage-api-key-XXXXXX"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "ssm:GetParameters",
      "Resource": "*"
    }
  ]
}
```

```bash
aws iam put-role-policy --role-name rag-agent-execution-role \
  --policy-name rag-agent-secrets-access \
  --policy-document file://iam/execution-role-secrets-policy.json
```

**Why `ssm:GetParameters` has to be a separate statement scoped to `"*"`:** even for Secrets-Manager-backed secrets, ECS resolves `secrets[].valueFrom` in the task definition through the SSM `GetParameters` API as a unified proxy path under the hood. IAM evaluates that specific call against a synthetic SSM-namespaced ARN, not your Secrets Manager ARN — so scoping it down to the secret ARN never matches, and the call fails with `AccessDenied` even though the `secretsmanager:GetSecretValue` statement looks correct. This is genuinely non-obvious and easy to lose an hour to.

### 4. Register the task definition and launch the service

Two things fail silently (or with confusing errors) if you get them wrong:

- **`secrets[].valueFrom` must be the full secret ARN**, not the bare name (`rag-agent/anthropic-api-key`). A bare name produces `invalid ssm parameters: rag-agent/anthropic-api-key,...` at container start — a different error from the permission-denial ones above, so don't confuse the two when debugging.
- **`runtimePlatform.cpuArchitecture` must match the image's actual architecture.** Docker on Apple Silicon builds `arm64` images by default; ECS task definitions default to `X86_64`. A mismatch fails at the image-pull step with `CannotPullContainerError: ... does not contain descriptor matching platform 'linux/amd64'` — not at build or push time, so this only surfaces once you try to run the task. Set `runtimePlatform.cpuArchitecture` to `"ARM64"` explicitly if you built on Apple Silicon (cheaper than cross-compiling for `amd64` under QEMU on an M-series Mac); leave it `X86_64` if you built on an Intel/AMD machine.

Save the following as `taskdef.json`, filling in your own account ID, region, and the exact secret ARNs from step 3:

```json
{
  "family": "rag-agent-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::<account_id>:role/rag-agent-execution-role",
  "taskRoleArn": "arn:aws:iam::<account_id>:role/rag-agent-task-role",
  "runtimePlatform": {
    "cpuArchitecture": "ARM64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "rag-agent",
      "image": "<account_id>.dkr.ecr.<region>.amazonaws.com/rag-agent:prod",
      "portMappings": [{ "containerPort": 5000, "protocol": "tcp" }],
      "secrets": [
        {
          "name": "ANTHROPIC_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:<region>:<account_id>:secret:rag-agent/anthropic-api-key-XXXXXX"
        },
        {
          "name": "VOYAGE_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:<region>:<account_id>:secret:rag-agent/voyage-api-key-XXXXXX"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/rag-agent",
          "awslogs-region": "<region>",
          "awslogs-stream-prefix": "rag-agent",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
```

```bash
aws ecs register-task-definition --region <region> --cli-input-json file://taskdef.json
```

**Cluster, security group, service:**

```bash
aws ecs create-cluster --cluster-name rag-agent-cluster --region <region>

# note the GroupId in the output — you'll need it as <sg_id> below
aws ec2 create-security-group --group-name rag-agent-sg \
  --description "RAG agent inbound" --vpc-id <vpc_id> --region <region>

# without this, every request times out at the TCP handshake — see the gotcha below
aws ec2 authorize-security-group-ingress --group-id <sg_id> \
  --protocol tcp --port 5000 --cidr 0.0.0.0/0 --region <region>

aws ecs create-service \
  --cluster rag-agent-cluster \
  --service-name rag-agent-service \
  --task-definition rag-agent-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet_id>],securityGroups=[<sg_id>],assignPublicIp=ENABLED}" \
  --region <region>
```

A public IP (chosen here over an ALB, which is unnecessary for a single always-on task) is the simpler of the two networking options.

**Security group gotcha:** a newly-created security group blocks **all** inbound traffic from the public internet by default — security groups are default-deny. The symptom is a pure TCP connect timeout (`curl: (28) Failed to connect... Timeout was reached`), not a "connection refused." That distinction matters for diagnosis: a *refused* connection means something is listening and actively rejecting you (an app-level issue); a *timed-out* connection means your packets never got a response at all (the network layer — usually the security group — is dropping them silently). You need an explicit inbound rule allowing your app's port from `0.0.0.0/0` (or a narrower CIDR, to restrict it) before anything outside the VPC can reach the task.

### Verifying the deployment

```bash
TASK_ARN=$(aws ecs list-tasks --cluster rag-agent-cluster --service-name rag-agent-service \
  --desired-status RUNNING --region <region> --query "taskArns[0]" --output text)

ENI_ID=$(aws ecs describe-tasks --cluster rag-agent-cluster --tasks "$TASK_ARN" --region <region> \
  --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value | [0]" --output text)

PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --region <region> \
  --query "NetworkInterfaces[0].Association.PublicIp" --output text)

curl -X POST "http://$PUBLIC_IP:5000/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I define a path parameter with type validation in FastAPI?"}'
```

You should get the same grounded, cited answer as the local container, and the same clean refusal for out-of-scope questions — containerization and deployment shouldn't change RAG behavior, only reachability.

### Troubleshooting a stuck deployment

`aws ecs list-tasks` **without `--desired-status` only returns `RUNNING` tasks** — a task that failed and stopped disappears from the default view entirely, which reads as "nothing happening" rather than "it's failing." Pass `--desired-status STOPPED` explicitly to see failures.

Task ARNs are random GUIDs with no chronological ordering. To find the *actual* most recent stopped task (e.g. after several failed attempts), sort by the real timestamp instead of the ARN list order:

```bash
aws ecs describe-tasks --cluster rag-agent-cluster --tasks <all stopped ARNs> --region <region> \
  --query "sort_by(tasks, &stoppedAt)[-1].{reason:stoppedReason,containers:containers[].reason}"
```

If a deployment has failed repeatedly, ECS's circuit breaker stops it from auto-retrying. Force a fresh attempt after fixing the underlying issue:

```bash
aws ecs update-service --cluster rag-agent-cluster --service rag-agent-service \
  --force-new-deployment --region <region>
```

### Pausing between sessions (cost)

Fargate is **not** covered by the AWS free tier — a single small task left running continuously costs real money (roughly $9–10/month) for zero benefit while you're not actively using it. Don't delete the service between sessions; just scale it to zero. Everything else (task definition, IAM roles, ECR image, secrets, cluster, security group) is free or negligible to leave in place, so scaling back up is instant, with no re-setup:

```bash
# pause
aws ecs update-service --cluster rag-agent-cluster --service rag-agent-service \
  --desired-count 0 --region <region>

# resume
aws ecs update-service --cluster rag-agent-cluster --service rag-agent-service \
  --desired-count 1 --region <region>
```

### Teardown

To remove everything created in this section:

```bash
aws ecs delete-service --cluster rag-agent-cluster --service rag-agent-service --force --region <region>
aws ecs delete-cluster --cluster-name rag-agent-cluster --region <region>
aws ec2 delete-security-group --group-id <sg_id> --region <region>
aws iam delete-role-policy --role-name rag-agent-execution-role --policy-name rag-agent-secrets-access
aws iam detach-role-policy --role-name rag-agent-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam delete-role --role-name rag-agent-execution-role
aws iam delete-role --role-name rag-agent-task-role
aws secretsmanager delete-secret --secret-id rag-agent/anthropic-api-key --force-delete-without-recovery --region <region>
aws secretsmanager delete-secret --secret-id rag-agent/voyage-api-key --force-delete-without-recovery --region <region>
aws ecr delete-repository --repository-name rag-agent --force --region <region>
```
