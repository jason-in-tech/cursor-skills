---
name: select-gpu-quota
description: Select the best business_attribution for a GPU training job before submission. Queries real-time Prometheus quota metrics and recommends the least-contended quota path that fits the requested GPU count. Use when submitting a training job, choosing business_attribution, checking GPU quota availability, or when a job is stuck waiting_for_quota.
---

# Select GPU Quota

Pre-submission check that picks the best `--business_attribution` for a training job based on real-time H100 quota availability.

## When to Use

- Before any `bazel run ... train-scene-enc` or `train-eval-scene-enc` submission
- When a submitted job is stuck in `waiting_for_quota`
- When the user asks which quota path has capacity

## Inputs

1. **GPU count**: Number of H100 GPUs the job requests (default: 128, from the config's `num_gpus`)
2. **Preferred quota**: The user's default `business_attribution`. For Structured Prediction (SP) team jobs (scene encoder, trajectory ranking, Olympus), the default is **`structured_prediction`**. Only override if the user explicitly requests a different path.

## Procedure

### Step 1: Query Real-Time Quota

Use the Grafana MCP to query Prometheus. Datasource UID for Chronosphere: `3725e559-3ab5-47a1-84aa-9baf182bb32c`.

Run these three queries in parallel (`queryType: "instant"`, `startTime: "now"`):

**Capacity:**
```promql
max by (quota_tree_path) (
  compute_substrate_admission_quota_resource_capacity{
    deployment_environment="prd",
    quota_resouce_identifier="nvidia-h100-80gb",
    quota_tree_path=~".*structured_prediction.*|.*e2e_training.*|.*fusion_encoder.*|.*olympus_release.*|.*sensor_encoder.*|.*trajectory_decoder.*"
  }
) > 0
```

**In Use (admitted):**
```promql
sum by (used_quota_tree_path) (
  max by (used_quota_tree_path, is_substrate_job_urgent) (
    compute_substrate_admission_quota_admitted_resource_agg{
      deployment_environment="prd",
      quota_resouce_identifier="nvidia-h100-80gb",
      used_quota_tree_path=~".*structured_prediction.*|.*e2e_training.*|.*fusion_encoder.*|.*olympus_release.*|.*sensor_encoder.*|.*trajectory_decoder.*"
    }
  )
)
```

**Queued (pending):**
```promql
sum by (desired_quota_tree_path) (
  max by (desired_quota_tree_path, is_substrate_job_urgent) (
    compute_substrate_admission_quota_pending_resource_agg{
      deployment_environment="prd",
      quota_resouce_identifier="nvidia-h100-80gb",
      desired_quota_tree_path=~".*structured_prediction.*|.*e2e_training.*|.*fusion_encoder.*|.*olympus_release.*|.*sensor_encoder.*|.*trajectory_decoder.*"
    }
  )
)
```

### Step 2: Compute Availability

For each quota path, calculate:

```
available = capacity - in_use
can_fit = (available >= gpu_count)
```

### Step 3: Apply Guardrails

#### H100 Quota Preferences

| Quota | Max GPUs | Preference | Rationale |
| --- | --- | --- | --- |
| `structured_prediction` | No limit | **1st (most preferred)** | Our primary quota — always try first |
| `e2e_training` | No limit | 2nd (flexible) | Our secondary quota, use freely if SP is full |
| `fusion_encoder` | 128 (1 job) | 2nd (flexible) | Shared — use if available |
| `sensor_encoder` | 128 (1 job) | 2nd (flexible) | Shared — use if available |
| `trajectory_decoder` | 128 (1 job) | 2nd (flexible) | Shared — use if available |
| `olympus_release` | 128 (1 job) | **Last (least preferred)** | Release quota — only use when all others are full |

#### L4 Quota Preferences

| Quota | Preference | Rationale |
| --- | --- | --- |
| `structured_prediction` | **1st (most preferred)** | Same as H100 — try first |
| All others | Equal | No strong preference among the rest |

**SP team jobs** include: scene encoder training/eval, trajectory ranking, Olympus model training, and any `ml_ranker_pipeline` submissions. For these jobs, `structured_prediction` is the natural home and should be recommended first unless it genuinely cannot fit the request.

If the user has already consumed their allowed limit on a quota path (check admitted), exclude it.

### Step 4: Rank and Recommend

Sort eligible paths by:
1. **`structured_prediction` first** — our primary quota, always preferred when it can fit
2. **User override** (if the user explicitly requests a different path, respect it)
3. **Flexible tier** (`e2e_training`, `fusion_encoder`, `sensor_encoder`, `trajectory_decoder`) — all equal; pick by zero queue, then most available GPUs
4. **`olympus_release` last** — only recommend when all flexible-tier paths are also full or queued
5. **Tie-breaker**: zero queue > most available GPUs

Present a table to the user:

```
| Quota | Capacity | In Use | Available | Queue | Fits? | Recommendation |
```

### Step 5: Present and Wait for Approval

Present the quota table and recommendation to the user. **Do NOT proceed with job submission until the user explicitly approves the `--business_attribution` value.** This is a hard gate -- even if the user already said "launch it", they must confirm the specific quota path.

Output exactly one of:
- **Recommend `<quota>`**: the path fits, with reasoning. Ask: "Submit with `--business_attribution=<quota>`?"
- **Wait**: preferred quota will free up soon (queue is draining). Ask: "Wait for preferred quota, or use `<alternative>`?"
- **Escalate**: no path has capacity. Suggest `MarkJobUrgent`, reducing GPU count, or waiting. Ask which option the user prefers.

Only after the user confirms (e.g., "yes", "use that", "go with olympus_release") should the downstream skill/workflow proceed with the chosen value.

## Valid BusinessAttribution Values

All from `cruise/ai_platform/attribution/business_attribution.py`:

| CLI value | Quota path suffix |
| --- | --- |
| `structured_prediction` | `structured_prediction` |
| `e2e_training` | `e2e_training` |
| `fusion_encoder` | `fusion_encoder` |
| `olympus_release` | `olympus_release` |
| `sensor_encoder` | `sensor_encoder` |
| `trajectory_decoder` | `trajectory_decoder` |

Switching `--business_attribution` only changes billing/quota path. It has no effect on training behavior, W&B project, or model output.

## T4 Deprecation Notice

**T4 GPUs are being deprecated for eval workloads (EoQ2 2026).** Per the AV Infra
migration plan, all eval jobs should run on **L4** (short-term) or **RTX 6000**
(long-term, Q2+ 2026).

When querying quota for eval jobs:
- Query **L4** quota (`nvidia-l4`) in addition to H100 for eval submissions
- For open-loop eval: use `--apply_macros eval_with_l4_gpu` (64 L4s, batch=16)
- For closed-loop eval: L4 is already the default (forced in `config_creator.py`)
- Configs on `olympus_v1_5+` already default to L4 for eval
- Older configs (`olympus_v1_4` and below) default to T4 and **must** be overridden

If a user submits an eval job without specifying L4, warn them that T4 is deprecated
and suggest adding `--apply_macros eval_with_l4_gpu`.

## Integration

Other skills should reference this skill in their pre-flight checklist:

```markdown
- [ ] Run `select-gpu-quota` skill to pick best `--business_attribution`
- [ ] For eval jobs: ensure L4 GPU target (T4 is deprecated)
```
