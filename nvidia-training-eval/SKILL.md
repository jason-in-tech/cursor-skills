# NVIDIA-Olympus Training Skill

End-to-end experiment workflow for NVIDIA data integration into the Olympus v1.4
training pipeline. Covers the full lifecycle from checkpoint lookup through
results publishing.

**Reference Documents**:
- [Nvidia Data Specification](https://generalmotors-my.sharepoint.com/:w:/g/personal/kzfz9h_nam_corp_gm_com/IQCOorx9yCmESr-fZxhbWqhfAaEW8bHCOdffpApvZLSKczI?e=RooXsR) -- sensor layout, data format, label schema
- [Nvidia Data Consumption Strategy](https://generalmotors-my.sharepoint.com/:w:/g/personal/kzfz9h_nam_corp_gm_com/IQC-vWZUbA4KT52N894s89b4AR8cU1sph1UU5D8O1l1MNDQ?e=PKE9HV) -- ingestion plan, pipeline strategy
- [NVIDIA Data Training / Eval Plan](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1972702552) -- phases, hyperparameters, comparison matrix, metrics reference
- [Platform Comparison and Integration Report](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1792737336) -- camera mapping, feature/config comparison, calibration bugs, MSL label gaps
- Local plan: `~/.cursor/plans/nvidia_olympus_v1.4_integration_8f9779e9.plan.md`

## Platform Context

NVIDIA data is remapped into the A110 namespace at Stage 1 featurization. Key facts:

- **7 NVIDIA cameras** mapped to A110 LDM names (camera_front_medium, camera_front_right_40,
  camera_front_left_80, camera_front_right_80, camera_rear_medium, camera_back_left, camera_back_right).
  `camera_front_wide_120fov` is duplicated into left_40 + right_40; the 7-camera config drops left_40.
- **Feature format**: NVIDIA matches A110_MSL on 8/11 dimensions (prefix, extrinsics, longpos,
  intent, metadata, MSL labels). Map format differs: NVIDIA uses `map_v2_*` (NGM) vs A110's
  `map_semantic_*` (L4). Image resolution matches A110 (940x1824).
- **Data source type**: `A110_MSL` with `cameras_override=get_nvidia_7_cameras()`
- **Architecture**: `FasterViT (vision) -> DimAdjust -> Accumulator -> FusionEncoderV2 (LaRa) -> GLOBAL_EMBEDDING`.
  Map head consumes GLOBAL_EMBEDDING. No separate map encoder.
- **Temporal sequence**: 1.6s window, 16 ticks at 10Hz. **NVIDIA uses 4-tick**
  (`BATCH_SHIFTS_PRETRAIN = [6, 4, 2, 0]`), matching A110 pre-training. SC3 fine-tuning
  uses 8-tick (`BATCH_SHIFTS_FINETUNE = [14, 12, 10, 8, 6, 4, 2, 0]`). Feature Accumulator
  (window size=2) gives the FusionEncoder current + previous frame at each step. 4 forward
  passes per NVIDIA sample (vs 8 for SC3), each outputting 400 detection slots.
- **Calibration fixes**: Two bugs fixed on branch (transform direction inversion + optical_joint
  duplication). After fixes, NVIDIA flows through identical code paths as SC3/A110.
- **MSL label gaps**: `total_num_lidar_points=0` (mitigated by `min_valid_lidar_point_number=None`),
  `object_bearing_angle=None` (no-op), classification fall-through (extend map in Phase 2).

## Pipeline Context

The NVIDIA training step sits between A110 pre-training and SC3 fine-tuning:

```
Fusion Encoder Pre-training -> A110 Pre-training -> NVIDIA Fine-tune -> SC3 Fine-tune -> SC3 Eval
```

Five branches (4 variants + 1 baseline) run in parallel:

| # | Branch | Source Checkpoint | Data | FasterViT | Config |
|---|--------|------------------|------|-----------|--------|
| 0 | **Baseline** | A110 | SC3 (8-tick) | Unfrozen | `olympus_v1_4_sc3_road` |
| 1 | **A110+NVIDIA frozen** | A110 | NVIDIA (4-tick) | Frozen | `olympus_v1_4_nvidia_backbone_frozen` |
| 2 | **A110+NVIDIA unfrozen** | A110 | NVIDIA (4-tick) | Unfrozen | `olympus_v1_4_nvidia` |
| 3 | **FusionPT+NVIDIA frozen** | FusionEncoder PT | NVIDIA (4-tick) | Frozen | `olympus_v1_4_nvidia_backbone_frozen` (different ckpt) |
| 4 | **FusionPT+SC3 autolabel** | FusionEncoder PT | SC3 autolabel (4-tick) | Frozen | TBD |

All 5 branches feed into SC3 fine-tune + eval on the same SC3 test set.

Key files (relative to repo root):

| File | Purpose |
|------|---------|
| `cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/configs/model_configs/olympus_v1_4.py` | NVIDIA model configs |
| `cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/configs/dataset_config.py` | NVIDIA dataset spec |
| `cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/configs/training_config.py` | Training config registry |
| `cruise/mla/ml_deployments/olympus/olympus_loader.py` | Deployed model checkpoint registry |
| `cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/notebooks/nvidia_olympus_eval.ipynb` | Inference visualization |

## 0. Pre-flight: Authentication

Before ANY `bazel run`, `bq query`, or `gcloud` command, verify auth:

```bash
gcloud auth application-default print-access-token 2>&1 | head -1
```

**If output is a token starting with `ya29.`**: Auth is valid, proceed.

**If output contains "Reauthentication", "refresh", or "error"**: Use two-tier refresh:
1. **Tier 1 (instant, no MFA)**: `authcli refresh` — silently refreshes all tokens using
   the existing Okta session. Works ~95% of the time, completes in <20 seconds.
2. **Tier 2 (full SSO)**: If `authcli status` still shows INVALID after Tier 1, escalate
   to the `cruise-auth-refresh` skill (`~/.cursor/skills/cruise-auth-refresh/SKILL.md`).

Re-check auth whenever a command fails with: `Reauthentication`, `401`,
`credentials`, `Permission denied`, `access token`, `RefreshError`.

**Persistent fix**: Set up a cron job to auto-refresh tokens every 30 minutes:

```bash
(echo "*/30 * * * * $(which authcli) refresh >/dev/null 2>&1") | crontab -
```

**Ladybug MCP auth**: The Ladybug MCP uses a `ladybug-mcp-dev` app token fetched
via `authcli app get ladybug-mcp-dev -ttl 120h`. The remote server has a proxy
that auto-refreshes, but the initial token fetch requires a valid Okta session.
If tools show as unavailable, the cron job above prevents the issue. If already
broken: run `authcli refresh`, then reload the Cursor window (the MCP restarts
and fetches a fresh token on startup).

## 1. Checkpoint Lookup

### 1a. V1.4 Deployed Checkpoints

The deployed V1.4 pipeline has 3 stages. Each stage's output checkpoint is the
next stage's input.

| Stage | Config | Checkpoint | Used by |
|-------|--------|------------|---------|
| Fusion Encoder PT (input for branches 3-4) | `olympus_v1_1_sc3_pce_road` | TBD -- look up from Olympus Hybrid Release Flow | FusionPT+NVIDIA, FusionPT+SC3 autolabel |
| A110 Pre-training (input for branches 0-2) | `olympus_v1_4_a110` | `gs://robotorch2-prod/scene_encoder/52f48c8b18a644ff820c77acf320d98d/checkpoints/final-checkpoint-epoch=15-step=145448.ckpt` | Baseline, A110+NVIDIA frozen/unfrozen |
| SC3 Fine-tune (deployed, input for Phase 0) | `olympus_v1_4_sc3_road` | `gs://robotorch2-prod/scene_encoder/bc25b4cab83c4a4c969001fe6d9629d7/checkpoints/final-checkpoint-epoch=26-step=70808.ckpt` | Zero-shot eval reference |

The A110 checkpoint is the starting point for **branches 0-2**.
The FusionEncoder PT checkpoint is the starting point for **branches 3-4**.
The SC3 checkpoint is the starting point for **Phase 0 (zero-shot eval)**.

### 1b. Find A110 Pre-training Checkpoint (for NVIDIA fine-tune)

The A110 pre-training checkpoint is the starting point for **Phase 1 (NVIDIA
fine-tune)**. Find a completed `olympus_v1_4_a110` run:

**Option A: BQ query (preferred)**

```bash
bq query --use_legacy_sql=false --format=csv --max_rows=10 "
SELECT id, root_run_id, name, future_state, created_at
FROM \`cruise-mlp-prod-13d0.mli_analytics.roboflow_export_rooted\`
WHERE name LIKE '%olympus_v1_4_a110%'
AND future_state = 'RESOLVED'
ORDER BY created_at DESC LIMIT 10"
```

**Option B: Glean search**

Search for "Olympus Hybrid Release Flow" or the V1.4 release doc to find the
specific A110 run ID used in the deployed release.

**Option C: lumen_agent MCP**

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "Find resolved Roboflow runs with name containing 'olympus_v1_4_a110'.
            Return the run ID, name, and checkpoint GCS path from the output
            artifact. Show the 5 most recent."
    start_fresh_session: true
```

### 1c. Extract Checkpoint GCS Path from a Run

**CRITICAL**: For `train-eval-scene-enc` pipelines, checkpoints are stored under
the **`train_pytorch_lightning` subtask's run ID**, NOT the orchestrator ID or the
`pytorch_trainer_substrate` ID.

**Step 1: Find the `train_pytorch_lightning` run ID from the orchestrator DAG**

```bash
RF_TOKEN=$(authcli app get roboflow -out stdout)
curl -s -H "Authorization: Bearer $RF_TOKEN" \
  "https://roboflow.robot.car/api/v1/runs/<ORCHESTRATOR_ID>/dag" | \
  python3 -c "
import sys,json
def find(node, name):
    if node.get('transformerName') == name: return node
    for c in node.get('children',[]):
        r = find(c, name)
        if r: return r
d=json.load(sys.stdin)
n = find(d, 'train_pytorch_lightning')
if n: print(n.get('id'))
"
```

**Step 2: List checkpoints in GCS using that ID**

```bash
GCP_TOKEN=$(gcloud auth application-default print-access-token)
curl -s -H "Authorization: Bearer $GCP_TOKEN" \
  "https://storage.googleapis.com/storage/v1/b/robotorch2-prod/o?prefix=scene_encoder/<TRAIN_PYTORCH_LIGHTNING_ID>/checkpoints/&delimiter=/" | \
  python3 -c "import sys,json; [print(i['name']) for i in json.load(sys.stdin).get('items',[])]"
```

The final checkpoint follows this pattern:
`gs://robotorch2-prod/scene_encoder/<TRAIN_PYTORCH_LIGHTNING_ID>/checkpoints/final-checkpoint-epoch=<N>-step=<M>.ckpt`

**Common mistake**: Using the orchestrator ID or `pytorch_trainer_substrate` ID for
GCS paths returns empty results. Only the `train_pytorch_lightning` wrapper ID maps
to the GCS directory.

### 1d. Checkpoint Chaining

Each stage loads the previous stage's checkpoint:

```
--ckpt_path=<prev_stage_checkpoint> --only_load_ckpt_weights
```

`--only_load_ckpt_weights` uses `load_state_dict_strict_overwrite_to_false = True`,
allowing key mismatches (different heads, different camera counts).

## 1e. Hyperparameter Defaults

Mirror SC3 fine-tuning. The NVIDIA config must call `modify_config_for_training_optimization`
(currently missing -- see plan Section 3 "Hyperparameters" for details).

**Data splits**: All three needed -- train (training), val (loss monitoring), test (eval job for Phase 0/1 metrics). Final decision metric is SC3 eval (Phase 2), but NVIDIA eval gives intermediate signal.

### Smoke Test (10K samples via CLI limit) -- COMPLETE

Validated via run [`f387ad21`](https://centra.robot.car/roboflow/runs/f387ad217e4f4f13953f1f63863e6802).
Loss converged 8.53 -> 3.07 (-64%). See runbook for full results.

| Param | Value | Verified |
|-------|-------|----------|
| max_lr | 0.0005 | Yes |
| Samples | 10K (via `--config.train_data_ctx.num_samples 10000`) | Yes (W&B: 9,302/epoch) |
| Batch size | 5 | Yes |
| Num GPUs | 32 (via CLI override) | Yes (W&B: effective_batch=160) |
| Reweighting | None | Yes |
| torch_compile | 5 modules (no map head) | Yes |

### Full Run (382K training samples)

| Param | Value | Rationale |
|-------|-------|-----------|
| **Sequence length** | 4-tick (`BATCH_SHIFTS_PRETRAIN`) | Match A110 pre-training; halves forward pass per sample |
| max_lr | 0.0005 | Match SC3 |
| Epochs | 15 | Set in Python config. Match total exposure (189K*30 ~ 382K*15) |
| Batch size | 5 | Match SC3 |
| Num GPUs | 128 | Set in Python config. Full scale |
| Num workers | 8 | Match SC3 |
| Reweighting | None | NVIDIA distribution differs from SC3/A110 |
| torch_compile | 5 modules (no MAPTR2_LARA_HEAD) | Map head disabled |

LR scheduler (OneCycleLR, pct_start=0.1, div_factor=25) and optimizer (Adam, lr=1e-4)
are inherited from the base config for both settings.

**Knobs to explore** (priority order): backbone frozen/unfrozen > epochs > learning rate > num GPUs. Keep everything else fixed at SC3 values for clean comparisons.

## 2. Launch Jobs

All commands use the ml_ranker_pipeline entry point:

```
//cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline
```

### Pre-flight: GPU Quota Selection (MANDATORY)

Before **every** `bazel run` that submits a training or eval job, you **MUST**
run the `select-gpu-quota` skill (`~/.cursor/skills/select-gpu-quota/SKILL.md`):

1. Query real-time GPU quota via Grafana Prometheus (capacity, in-use, queued)
2. Compute availability for each quota path
3. Present the quota table to the user
4. Get explicit user approval for the `--business_attribution` value
5. Only then proceed with the `bazel run` command

**Do NOT default to `structured_prediction` without checking.** It is often fully
subscribed. Submitting to a full quota means hours in queue when alternative paths
have immediate capacity.

This applies to: `train-scene-enc`, `train-eval-scene-enc`, `eval-scene-enc`,
and any `ml_ranker_pipeline` submission that requests GPU resources.

### Pre-flight: Eval GPU Type Selection (MANDATORY)

**T4 GPUs are deprecated for eval jobs.** Per the AV Infra migration plan (EoQ2 2026
deadline), all eval workloads must migrate to L4. See the
[T4 deprecation plan](https://generalmotors.sharepoint.com/:w:/s/av-infrastructure-sharepoint/IQAZSUwMawX3TY3RDBm-tRjYAT_KA8YAQIgH8_yDCggf_WE).

**How to select L4 for eval:**

| Method | When to use | Command |
|--------|-------------|---------|
| **`--apply_macros eval_with_l4_gpu`** | One-off override at launch time | Add to `bazel run` args (64 L4 GPUs, batch_size=16) |
| **Config-level** | Permanent change for a config | Set `eval_resource_config=get_l4_compute_config(num_gpus=N)` in the Python config |
| **CLI override** | Fine-grained control | `--config.eval_resource_config.device_type L4` |

**Config defaults by version:**

| Config family | Default eval GPU | Notes |
|---------------|-----------------|-------|
| `olympus_v1_1` and earlier | T4 (128 GPUs, batch=8) | **Must override to L4** |
| `olympus_v1_4_sc3_road` | T4 (inherited from v1.1) | **Must override to L4** |
| `olympus_v1_5` | **L4** (32 GPUs) | Already migrated |
| Closed-loop eval | **L4** (forced in `config_creator.py`) | Automatic, no action needed |

**For `olympus_v1_4_sc3_road` eval submissions, always add `--apply_macros eval_with_l4_gpu`:**

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  eval-scene-enc \
  --config-choice=olympus_v1_4_sc3_road \
  --apply_macros eval_with_l4_gpu \
  ...
```

**Macro specs** (from `cluster_specs.py`):

| Macro | GPU type | Num GPUs | Batch size |
|-------|----------|----------|------------|
| `eval_with_t4_gpu` | T4 | 128 | 8 |
| `eval_with_l4_gpu` | L4 | 64 | 16 |
| `eval_with_h100_gpu` | H100 | 16 | 48 |

**Consistency rule**: Within a single experiment comparison (e.g., all 7 NVIDIA
branches), all OL evals must use the same GPU type. If some branches already
completed on T4, either rerun them all on L4 or keep all on T4 for that experiment.
Do not mix GPU types within a comparison set.

### 2a. Train + Eval (remote, Roboflow)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  train-eval-scene-enc \
  --config-choice=<config_name> \
  --exp_name=<experiment_name> -v <version> \
  --ckpt_path=<gs://checkpoint_path> --only_load_ckpt_weights \
  --business_attribution=<USER_APPROVED_QUOTA> \
  --skip-prevalidate --ignore_time_limit --ignore_cost_warning \
  --model_selection final
```

### 2b. Eval Only (remote, Roboflow)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  eval-scene-enc \
  --config-choice=<config_name> \
  --apply_macros eval_with_l4_gpu \
  --exp_name=<experiment_name> \
  --ckpt_path=<gs://checkpoint_path> --only_load_ckpt_weights \
  --business_attribution=<USER_APPROVED_QUOTA> \
  --skip-prevalidate --ignore_time_limit
```

> **Note**: `--apply_macros eval_with_l4_gpu` ensures L4 GPUs. Omit only if you
> need T4 for backward-compatibility with an existing experiment set.

> **`<USER_APPROVED_QUOTA>`**: Run the `select-gpu-quota` skill first to determine
> the best quota path, then get explicit user approval before substituting the value.
> Default is `structured_prediction` but may change based on real-time availability.

For eval-only on a previously trained run's checkpoint, use `--train_job_id`
instead of `--ckpt_path`:

```bash
  --train_job_id=<roboflow_train_job_id>
```

### 2b-1. Handling Stale Branch Errors

If `bazel run` fails with a stale-branch error, there are **two layers**:

| Layer | Error message | Env var bypass |
|-------|---------------|----------------|
| Client-side | `Please rebase on latest develop` | `CRUISE_BYPASS_BAD_COMMITS=true` |
| Server-side | `RoboFlowError: status=400, Orchestrator launch is blocked because the git branch is stale` | `STALE_CODE_REASON="<reason>"` |

**Full bypass command** (both layers):
```bash
CRUISE_BYPASS_BAD_COMMITS=true \
STALE_CODE_REASON="Experiment branch must match prior runs for fair comparison" \
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  train-eval-scene-enc \
  --config-choice=<config_name> ...
```

**Decision: bypass vs rebase -- ASK THE USER.** Present both options:
- **Bypass**: Use when experiments must run on identical code as prior runs for fair comparison, or when develop has unrelated breaking changes. Provide a meaningful `STALE_CODE_REASON`.
- **Rebase**: Use when the user wants the latest code, or when CI/PR submission requires it. See `rebase-to-develop` skill.

Never assume rebase is required. A rebase introduces confounding variables into experiment comparisons.

Source: `cruise/mlp/roboflow2/server/stale_branch_blocking_utils.py`, `cruise/mlp/roboflow2/api_client_internal.py`.

### 2c. Local Debug (quick validation)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder:local_debug -- \
  --config-choice=<config_name>
```

Add `--shrink_trainer_config` for minimal data. This does NOT submit to Roboflow;
it runs locally on the current machine.

### 2d. Phase-Specific Commands

**Phase 0: Zero-Shot Eval** (V1.4 SC3 model on NVIDIA data)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  eval-scene-enc \
  --config-choice=olympus_v1_4_nvidia \
  --exp_name=nvidia_zero_shot_v1_4_baseline \
  --ckpt_path=gs://robotorch2-prod/scene_encoder/bc25b4cab83c4a4c969001fe6d9629d7/checkpoints/final-checkpoint-epoch=26-step=70808.ckpt \
  --only_load_ckpt_weights \
  --business_attribution=structured_prediction \
  --skip-prevalidate --ignore_time_limit
```

**Phase 1: Backbone-frozen** (NVIDIA fine-tune)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  train-eval-scene-enc \
  --config-choice=olympus_v1_4_nvidia_backbone_frozen \
  --exp_name=nvidia_backbone_frozen -v smoke_1 \
  --ckpt_path=<a110_checkpoint> --only_load_ckpt_weights \
  --business_attribution=structured_prediction \
  --skip-prevalidate --ignore_time_limit --ignore_cost_warning \
  --model_selection final
```

**Phase 1: Backbone-unfrozen** (NVIDIA fine-tune)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  train-eval-scene-enc \
  --config-choice=olympus_v1_4_nvidia \
  --exp_name=nvidia_backbone_unfrozen -v smoke_1 \
  --ckpt_path=<a110_checkpoint> --only_load_ckpt_weights \
  --business_attribution=structured_prediction \
  --skip-prevalidate --ignore_time_limit --ignore_cost_warning \
  --model_selection final
```

### 2d-1. Phase 2: SC3 Fine-tune (from any Phase 1 checkpoint)

**CRITICAL**: Phase 2 SC3 fine-tuning MUST use `olympus_v1_4_sc3_road` (30 epochs),
regardless of which Phase 1 config was used. Do NOT re-use the Phase 1 config for
Phase 2 -- Phase 1 configs have different epoch counts (12-23) and train on different
datasets (NVIDIA or SC3 autolabel). Phase 2 always fine-tunes on SC3 road data.

| Phase | Config | Epochs | Dataset |
|-------|--------|--------|---------|
| Phase 1 (NVIDIA fine-tune) | `olympus_v1_4_nvidia*` | 20-40 | NVIDIA (4-tick) |
| Phase 1 (SC3 autolabel) | `olympus_v1_4_sc3_autolabel*` | 12-23 | SC3 autolabel v0.13 (4-tick) |
| **Phase 2 (SC3 fine-tune)** | **`olympus_v1_4_sc3_road`** | **30** | **SC3 road v0.14 (8-tick)** |

To find the Phase 1 checkpoint, follow Section 1c:
1. Get the Phase 1 Roboflow orchestrator ID (from Centra URL)
2. Query the DAG to find the `train_pytorch_lightning` subtask ID
3. List GCS checkpoints: `gs://robotorch2-prod/scene_encoder/<train_pytorch_lightning_id>/checkpoints/`
4. Use the `final-checkpoint-epoch=*-step=*.ckpt` file

**Phase 2 command template:**

```bash
CRUISE_BYPASS_BAD_COMMITS=true \
STALE_CODE_REASON="Experiment branch must match prior runs for fair comparison" \
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking:ml_ranker_pipeline -- \
  train-eval-scene-enc \
  --config-choice=olympus_v1_4_sc3_road \
  --exp_name=<branch_name>_then_sc3 \
  --ckpt_path=gs://robotorch2-prod/scene_encoder/<parent_run_id>/checkpoints/final-checkpoint-epoch=<N>-step=<M>.ckpt \
  --only_load_ckpt_weights \
  --business_attribution=<USER_APPROVED_QUOTA> \
  --skip-prevalidate --ignore_time_limit --ignore_cost_warning \
  --model_selection final
```

**Naming convention**: `<branch_descriptor>_then_sc3` (e.g., `nvidia_frozen_then_sc3`,
`nvidia_autolabel_frozen_then_sc3`).

### 2e. Common Knobs

Defaults mirror SC3 (see Section 1e). Override via CLI flags:

**IMPORTANT**: Epoch and GPU settings should be baked into the Python config
(`_make_olympus_v1_4_nvidia_base_config` in `olympus_v1_4.py`). CLI overrides
via roboparser are unreliable for nested config fields. In particular,
`--config.max_train_epochs N` does NOT work -- use `--step_limit=N` instead.

| Flag | Purpose | Verified? | Example |
|------|---------|-----------|---------|
| `--step_limit=N` | Cap total optimizer steps | Yes (Runbook) | `--step_limit=200` |
| `--config.{train,eval}_resource_config.num_workers=N` | Override GPU count | Yes (Runbook) | `--config.{train,eval}_resource_config.num_workers=32` |
| `--config.train_data_ctx.num_samples N` | Limit training samples | Yes (smoke test) | `--config.train_data_ctx.num_samples 10000` |
| `--config.train_dataloader_config.batch_size N` | Training batch size | Yes | `3` (OOM) |
| `--config.val_dataloader_config.batch_size N` | Val batch size | Yes | `2` |
| `--config.train_resource_config.device_type X` | GPU type | Yes | `T4` |
| `--config.limit_val_batches N` | Limit validation (0 to skip) | Yes | `0` |
| `--shrink_trainer_config` | Minimal data for local debug | Yes | -- |
| `--config.profile_thorough=true` | PyTorch profiler | Yes | -- |
| ~~`--config.max_train_epochs N`~~ | ~~Override epochs~~ | **NO** | Does not work; set in Python config |

## 3. Monitor Jobs

After `bazel run` prints a Centra URL like `https://centra.robot.car/roboflow/runs/<run_id>`:

### 3a. Poll for Completion

```bash
bazel run //cruise/e2e_gym:roboflow_job_status -- <run_id> --poll-for-completed \
  --timeout-sec 14400 --poll-interval-sec 60
```

Run in background (`block_until_ms: 0`), check periodically.

### 3b. Quick State Check

```bash
bazel run //cruise/e2e_gym:roboflow_job_status -- <run_id>
```

States: `RESOLVED` (done), `RAN` (Dataflow finished, may still be processing),
`NESTED_FAILED`, `FAILED`.

### 3c. Via lumen_agent

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "Check the status of Roboflow run <run_id>. Is it completed?
            What is the future_state? If resolved, get the checkpoint path."
    start_fresh_session: true
```

### 3d. Early Health Check (IMPORTANT)

After submitting, wait **5 minutes** and run the debug tool to catch startup errors fast:

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/notebooks:debug_roboflow_errors -- <run_id>
```

If the run has already failed (`NESTED_FAILED`), fix immediately instead of polling for
hours. Common startup failures resolve in <5 minutes.

### 3e. What to Watch For

| Signal | Meaning | Action |
|--------|---------|--------|
| `RESOLVED` | Job completed | Extract checkpoint (train) or metrics (eval), proceed |
| `RAN` | Dataflow done, still processing | Wait and re-check; NOT equivalent to RESOLVED |
| `NESTED_FAILED` with OOM | GPU memory exceeded | Reduce batch size, retry |
| `NESTED_FAILED` with key mismatch | Checkpoint incompatible | Verify config matches checkpoint source |
| `NESTED_FAILED` with `InvalidConfigError: sample_from_data_sources cannot take zero data sources` | **Split weights are zero for the requested split** | Fix `Weights` in `dataset_config.py` -- ensure `test=1.0` (and `val=1.0`) for all splits the pipeline needs. This is the most common eval failure. |
| Loss NaN after epoch 0 | Learning rate too high or data issue | Check LR schedule, data quality |
| Loss not decreasing | Model not learning | Check frozen modules, data loading, labels |

### 3f. Dataset Config Checklist (Pre-launch)

Before launching eval or train-eval, verify the dataset config:

1. **Split weights**: `Weights(train=X, val=Y, test=Z)` -- all splits you need must have weight > 0.
   For eval-only (`eval-scene-enc`): `test > 0` required. For train-eval: all three > 0 recommended.
2. **val_split_available**: Must be `True` in the training config if val weight > 0.
3. **job_id**: Must point to a Stage 2 (map+intent) job, not Stage 1.
4. **BQ tables exist**: Verify with lumen_agent or BQ query before launching.

## 4. W&B Analysis

### 4a. Find W&B Link from a Centra Run

**Note**: The BQ analytics table `roboflow_export_rooted` has a replication lag of
30-60 minutes after RESOLVED. If the W&B query returns empty, wait and retry, or
check the Centra URL directly (the W&B link appears in the run's artifacts tab).

**Primary method: lumen_agent** (requires ladybug-mcp-dev token):
```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "Get the W&B URL and eval metrics for resolved Roboflow run <run_id>"
    start_fresh_session: true
```

**Fallback: BQ query** (may lag behind):

Use the `analyze-olympus-runs` skill pattern:

```sql
SELECT
  e.producer_run_id,
  JSON_VALUE(a.json_representation, '$.wandb_url.value_serialization') as wandb_url
FROM `ca-silver-prd-e2h4.ml_pipelines_mart.run_edges_vw` e
JOIN `ca-silver-prd-e2h4.ml_pipelines_mart.fact_run_edge_artifacts` a
  ON e.artifact_id = a.artifact_id
WHERE e.producer_run_id IN (
  SELECT id FROM `cruise-mlp-prod-13d0.mli_analytics.roboflow_export_rooted`
  WHERE root_run_id = '<root_run_id>'
  AND transformer_path LIKE '%pytorch_trainer_substrate%'
)
AND e.name = 'streaming_metrics'
```

### 4b. Compare Loss Curves

Use the `analyze-wandb` skill for structured run comparison. Provide both run IDs
and ask for convergence analysis:

Key metrics to compare between backbone-frozen and backbone-unfrozen:
- `train/total_loss` convergence rate
- `train/tracker_loss` and `train/trajectory_loss` separately
- Learning rate schedule alignment
- Gradient norm stability

### 4c. Key Metrics for NVIDIA Experiments

**Phase 0 vs. Phase 1** (open-loop, NVIDIA data):
- Detection 3D AP by range [0-25m], [25-50m], [50-100m]
- Tracking lateral/longitudinal error by distance bin

**Phase 2** (open-loop + closed-loop, SC3 data):
- All Phase 0/1 SP metrics on SC3 data
- Map head: Lane F1, chamfer distance (gating -- must not regress)
- SC3 Protocol: Lane Keep, ORA Actions pass rates (from `decorated_test_requests`);
  TTC, collision, hard brake mi/event, swerve mi/event, controllability, sim safety
  proxy (from `decorated_test_executions.execution.scores` -- ~300 per-execution metrics).
  See `sc3-protocol` skill for extraction queries.

### 4d. Automated BQ Metrics Extraction (Primary Method)

The eval pipeline writes per-sample 3D detection metrics to BQ. Use lumen_agent
to discover the tables, then query directly.

**Step 1: Find BQ tables via lumen_agent**

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "For Roboflow run <run_id>, find the pytorch_evaluator_substrate
            nested transformer. Get its streaming_metrics side artifact (W&B URL)
            and ModelEvaluationResults output (BQ table refs in local_measurements).
            Return ALL BQ table references found."
    start_fresh_session: true
```

Key artifacts from `ModelEvaluationResults.local_measurements`:
- `tracking_3d` → `cruise-mlp-prod-13d0.visual_detection_metrics.detection_3d_<eval_id>`
- `inference_metrics` → `cruise-mlp-prod-13d0.inferences_dev.scene_encoder_inference_metrics_<parent_id>`

**Step 2: Run aggregate detection metrics queries**

```sql
-- Precision by range bin (primary detection metric)
SELECT
  CASE WHEN detection_distance_from_av BETWEEN 0 AND 25 THEN '0-25m'
       WHEN detection_distance_from_av BETWEEN 25 AND 50 THEN '25-50m'
       WHEN detection_distance_from_av BETWEEN 50 AND 100 THEN '50-100m'
       ELSE '100m+' END as range_bin,
  COUNTIF(match_outcome_class LIKE 'MATCH%') as tp,
  COUNTIF(match_outcome_class = 'NO_LABEL') as fp,
  ROUND(COUNTIF(match_outcome_class LIKE 'MATCH%')
    / NULLIF(COUNTIF(dt_valid), 0), 4) as precision,
  ROUND(AVG(CASE WHEN match_outcome_class LIKE 'MATCH%'
    THEN centroid_error_3d END), 3) as centroid_err,
  ROUND(AVG(CASE WHEN match_outcome_class LIKE 'MATCH%'
    THEN heading_error_3d END), 3) as heading_err
FROM `cruise-mlp-prod-13d0.visual_detection_metrics.detection_3d_<eval_id>`
WHERE dt_valid GROUP BY range_bin ORDER BY range_bin
```

**Step 3: Run trajectory generation metrics queries**

The inference_metrics table contains per-sample traj generation metrics. Key queries:

```sql
-- ADE/FDE at key time horizons
SELECT COUNT(*) as n,
  ROUND(AVG(top_mode_ade_lat_0_5s), 4) as ade_lat_0_5s,
  ROUND(AVG(top_mode_ade_lat_2s), 4) as ade_lat_2s,
  ROUND(AVG(top_mode_ade_lat_3s), 4) as ade_lat_3s,
  ROUND(AVG(top_mode_ade_long_1s), 4) as ade_long_1s,
  ROUND(AVG(top_mode_ade_long_2s), 4) as ade_long_2s,
  ROUND(AVG(top_mode_ade_long_9s), 4) as ade_long_9s,
  ROUND(AVG(min_l2_fde_1s), 4) as min_fde_1s
FROM `cruise-mlp-prod-13d0.inferences_dev.scene_encoder_inference_metrics_<parent_id>`
```

```sql
-- KCM, hard brake, NMC violations, route compliance
SELECT
  ROUND(AVG(av_pred_min_lateral_kcm), 4) as min_lat_kcm,
  ROUND(AVG(av_pred_min_longitudinal_kcm), 4) as min_long_kcm,
  ROUND(AVG(av_pred_hard_brake_rate_1s), 4) as hard_brake_1s,
  ROUND(AVG(top_1_av_pred_hard_brake_rate_with_gt_masking_1s), 4) as hard_brake_gt_1s,
  ROUND(AVG(top_1_av_pred_max_lat_acc_violation), 4) as lat_acc_viol,
  ROUND(AVG(fraction_trajectories_diverged_from_route), 4) as route_diverge,
  ROUND(AVG(av_too_slow_rate_6s), 4) as too_slow_6s,
  ROUND(AVG(top_mode_avg_vel_long_err_3s), 4) as vel_long_err_3s,
  ROUND(AVG(union_area_coverage_2d_radial_3s), 4) as coverage_3s,
  ROUND(AVG(total_loss), 4) as total_loss
FROM `cruise-mlp-prod-13d0.inferences_dev.scene_encoder_inference_metrics_<parent_id>`
```

### 4e. W&B Metric Download (for Loss Curves)

```bash
bazel run --config=no-tty \
  //cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/notebooks/tools:download_wandb_metric_csv -- \
  --wandb_url <wandb_url> \
  --metric_pattern "train/total_loss" --metric_pattern "valid/total_loss" \
  --output loss_curves.csv
```

### 4f. Existing Tools Reference

| Tool | Bazel Target / Path | Purpose |
|------|---------------------|---------|
| `download_wandb_metric_csv` | `//...scene_encoder/notebooks/tools:download_wandb_metric_csv` | Download W&B metrics to CSV |
| `sc3_wandb_slices.ipynb` | `//...scene_encoder/notebooks:sc3_wandb_slices` | W&B metric analysis with slice breakdown |
| `experiment_comparison.ipynb` | `//...scene_encoder/notebooks:experiment_comparison` | Compare experiments via BQ inference tables |
| `analyze-olympus-runs` skill | `.agents/skills/teams/avml/analyze_olympus_runs/SKILL.md` | BQ queries for run artifacts, configs, RPS |

### 4g. Baseline Metrics (Phase 0 Zero-Shot)

**Detection (from `detection_3d` table)**:

| Range | TP | FP | Precision | Centroid Err (m) | Heading Err (rad) |
|-------|----|----|-----------|------------------|-------------------|
| 0-25m | 665 | 7,701 | 7.95% | 0.865 | 0.779 |
| 25-50m | 540 | 7,133 | 7.04% | 0.827 | 1.030 |
| 50-100m | 80 | 775 | 9.36% | 0.900 | 0.918 |
| **Overall** | **1,285** | **15,609** | **7.61%** | **0.84** | **0.85** |

- Recall: 1.07% (1,285 / 120,423) -- **misleading**, see note below
- Only VEHICLE class matched (1,284/1,285 TPs); GT has 1,483 PED + 119 BIKE
- 429 scenes, avg GT distance 66.81m (48K GT at 50-100m, 23K at 100m+)

**Detection thresholds**: Two-stage filtering applies: (1) existence score >= 0.3
determines if a detection is valid (binary "is this a detection?" gate), then
(2) BEV IoU >= 0.45 determines if a valid detection matches a GT label.

**Important**: Low recall does NOT mean the model can't detect NVIDIA objects.
At 0-25m, the model produces 8,366 detections for 15,975 GT (52% DT/GT ratio),
but only 675 meet BEV IoU >= 0.45 (4.2% recall). The bottleneck is **box
alignment** (size/orientation/position), not detection ability. Additionally,
28% of matched objects have 180-degree heading flip, suggesting a heading
convention mismatch in the featurization pipeline.

**Trajectory Generation (from `inference_metrics` table, 3,432 samples)**:

| Metric Category | Key Metric | Value | Notes |
|----------------|-----------|-------|-------|
| **Losses** | total_loss | 8.528 | All from traj classification; detection losses = 0 |
| **ADE Lateral** | 0.5s / 2s / 3s | 0.25m / 1.00m / 1.65m | Grows with horizon |
| **ADE Longitudinal** | 1s / 2s / 9s | 0.67m / 1.93m / 28.4m | 9s explodes (expected zero-shot) |
| **Min FDE** | 1s | 1.85m | Best-of-N final displacement |
| **KCM** | lat / long | 0.26 / 0.27 | Pred KCM low vs GT lat KCM 2.18 |
| **Hard Brake** | raw 1s / GT-masked 1s | 29.6% / 3.4% | GT masking removes GT-caused brakes |
| **NMC Violations** | lat acc / long acc | 4.17 / 1.50 | High lat acc suggests sharp turns |
| **Route** | divergence / too slow | 11.5% / 31.8% | Domain gap in route following |
| **Velocity Error** | long 1s / 3s | 1.49 / 4.39 m/s | Growing error with horizon |
| **Diversity** | union coverage 3s | 48.56 | Multi-modal coverage |

## 5. Experiment Tracking

**First experiment completed**: Phase 0 zero-shot eval (`dc99ccafec8244bc925f7b072d0d0186`)
resolved with 0/14 failures on 2026-03-26.

### 5a. Registry Format

Maintain a local YAML file at `~/.cursor/nvidia_training_experiments.yaml`:

```yaml
experiments:
  - name: "nvidia_zero_shot_v1_4_baseline"
    phase: 0
    variant: "zero-shot"
    config: "olympus_v1_4_nvidia"
    ckpt_source: "V1.4 SC3 deployed"
    ckpt_path: "gs://robotorch2-prod/scene_encoder/bc25b4cab83c4a4c969001fe6d9629d7/checkpoints/final-checkpoint-epoch=26-step=70808.ckpt"
    centra_url: "https://centra.robot.car/roboflow/runs/dc99ccafec8244bc925f7b072d0d0186"
    wandb_url: null  # Check Centra artifacts tab
    status: "completed"
    notes: "RESOLVED 0/14 failures. First attempt (e44c66c3) failed with InvalidConfigError due to test weight=0; fixed Weights to (1.0,1.0,1.0)."
    launched_at: "2026-03-26T01:00:08"
    completed_at: "2026-03-26T01:32:16"

  - name: "nvidia_backbone_frozen_smoke_1"
    phase: 1
    variant: "backbone-frozen"
    config: "olympus_v1_4_nvidia_backbone_frozen"
    ckpt_source: "A110 pre-training"
    ckpt_path: "<a110_checkpoint>"
    centra_url: null
    wandb_url: null
    status: "pending"
    notes: ""
    launched_at: null
    completed_at: null
```

### 5b. Workflow

1. Before launching, add an entry with `status: pending`
2. After launch, update with `centra_url` and `status: running`
3. After completion, update with `wandb_url`, `status: completed`, metrics summary
4. On failure, update with `status: failed`, error notes

TODO: Automate registry updates in the launch/monitor workflow.

## 6. Results Publishing

Choose the publishing target based on image density:

| Content type | Target | Who publishes |
|---|---|---|
| **Image-heavy** (eval results with W&B viz, notebook plots, camera views) | **Google Doc** | Agent generates markdown, user pastes + manages images |
| **Image-light** (plans, config summaries, links, metrics tables) | **Confluence** | Agent publishes directly via Atlassian MCP |

### 6a. Markdown-First Workflow (all reports)

All reports start as markdown, co-located with their images:

1. **Extract images from executed notebooks** into the notebook's `output/` directory (e.g., `cruise/.../notebooks/output/report_*.png`). Use descriptive filenames.
2. **Draft markdown** in the same `output/` directory so image references use bare filenames (`![alt](filename.png)`).
3. **Add narrative around every figure**: Explain what the plot shows, what indices mean (e.g., "Sample 0 = one driving sequence"), what to look for, and why the result looks the way it does.
4. **Co-edit** the markdown file with the user until content is finalized.
5. **Publish** to the appropriate target (see 6b/6c below).

### 6b. Google Doc (image-heavy reports)

- Target doc: [Structured Perception - Nvidia Training & Inference](https://docs.google.com/document/d/1GG8VtoN0wkC2MXL_MduLa65b6s2NyZ52IHEnrge99zc/edit?tab=t.0)
- Google Docs accepts markdown paste directly
- User manages images manually (screenshots from W&B, notebooks, extracted PNGs from `output/` directory)
- Include Centra run URLs, W&B links, and metrics tables in the markdown
- For images the agent can't upload, use `> **TODO:** ...` placeholders with exact source locations

### 6c. Confluence (image-light reports)

Use the `confluence-publish` skill (`~/.cursor/skills/confluence-publish/SKILL.md`):

- Plan page: [NVIDIA Data Training / Eval Plan for Olympus v1.4](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1972702552)
- Results index: [Structured Perception -- NVIDIA Zero-Shot Inference Results](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1987543558)
- **Size limit**: The Atlassian MCP has a ~46KB payload limit. For larger reports, use the child page pattern:
  - Parent page = lightweight index (summary table, links, no inline images)
  - Child pages = one per section (e.g., "Detection Results", "Trajectory Results")
  - Always use `contentFormat: markdown` -- it's ~10x smaller than ADF
- **Never overwrite a page with manually-uploaded images** -- the ADF for media nodes is huge and fragile. Add new content as child pages instead.

### 6d. Slack

Use the `slack-thread-reply` skill (`~/.cursor/skills/slack-thread-reply/SKILL.md`)
to share results in relevant channels. Include:
- One-line summary (which variant won, key metric deltas)
- Links to Centra, W&B, Google Doc or Confluence as appropriate
- Next steps

### 6e. Report Template

When publishing results, follow the `write-technical-report` skill
(`~/.cursor/skills/write-technical-report/SKILL.md`) structure:

```markdown
## NVIDIA Training Results: <Phase> - <Variant>

**Run**: [Centra](<url>) | [W&B](<url>)
**Config**: `<config_name>` | **Checkpoint source**: <source>
**Dataset**: NVIDIA MAP_AND_INTENT (<N> samples)

### Detection by Range
| Metric | Zero-shot | Backbone-frozen | Backbone-unfrozen |
|--------|-----------|-----------------|-------------------|
| Precision [0-25m] | 7.95% | ... | ... |
| Precision [25-50m] | 7.04% | ... | ... |
| Precision [50-100m] | 9.36% | ... | ... |
| Centroid Err [0-25m] | 0.865m | ... | ... |
| Centroid Err [25-50m] | 0.827m | ... | ... |
| Heading Err [0-25m] | 0.779 rad | ... | ... |
| Overall Recall | 1.07% | ... | ... |
| Overall Precision | 7.61% | ... | ... |

### Trajectory Generation
| Metric | Zero-shot | Backbone-frozen | Backbone-unfrozen |
|--------|-----------|-----------------|-------------------|
| Total Loss | 8.528 | ... | ... |
| ADE Lat 2s (m) | 1.00 | ... | ... |
| ADE Long 2s (m) | 1.93 | ... | ... |
| ADE Long 9s (m) | 28.36 | ... | ... |
| Min FDE 1s (m) | 1.85 | ... | ... |
| Hard Brake (GT-masked 1s) | 3.4% | ... | ... |
| Route Diverge | 11.5% | ... | ... |
| Too Slow Rate 6s | 31.8% | ... | ... |
| Lat Acc Violation | 4.17 | ... | ... |
| Union Coverage 3s | 48.56 | ... | ... |

### Observations
- Two-stage filtering: existence score >= 0.3 (detection valid?) then BEV IoU >= 0.45 (match?)
- 1% recall is misleading: model produces detections (52% DT/GT ratio at 0-25m)
  but BEV IoU < 0.45 for most (box alignment issue, not non-detection)
- 28% of matched objects have 180-degree heading flip (featurization convention?)
- Detection losses = 0 in eval mode by design (trackformer head skips loss
  computation, detection quality measured separately via detection_3d table)
- ADE grows steeply with horizon (expected for zero-shot on new domain)
- Hard brake drops 29.6% -> 3.4% with GT masking (GT has aggressive maneuvers)

### Next Steps
- Investigate heading convention mismatch before Phase 1 (featurization fix?)
- Phase 1: Fine-tune to improve box alignment and close remaining domain gap
- Larger dataset: Current results from small subset (429 scenes / 1,611 samples)
```

## 7. Iterative Workflow

When the user asks to run an NVIDIA training experiment, follow this checklist:

```
Pre-flight:
- [ ] Check auth (Section 0)
- [ ] Determine phase (0/1/2) and variant (frozen/unfrozen)
- [ ] Look up required checkpoint (Section 1)
- [ ] Run `select-gpu-quota` skill to pick best `--business_attribution` for GPU count
- [ ] **User approves `--business_attribution`** (hard gate -- do not skip)

Launch:
- [ ] Run local debug first if config is new or untested (Section 2c)
- [ ] Launch remote job(s) (Section 2a/2b/2d) with **user-approved** `--business_attribution`
- [ ] Record in experiment registry (Section 5)

Monitor:
- [ ] Poll for completion (Section 3a)
- [ ] Check for errors (Section 3d)
- [ ] Extract W&B link (Section 4a)

Analyze:
- [ ] Extract BQ tables via lumen_agent (Section 4d)
- [ ] Run aggregate detection queries (Section 4d)
- [ ] Get W&B link from streaming_metrics (Section 4a)
- [ ] Compare loss curves if training run (Section 4b)
- [ ] Compare against baseline (Section 4g)
- [ ] Update experiment registry (Section 5)

Publish:
- [ ] Image-heavy? Provide markdown for Google Doc (Section 6a)
- [ ] Image-light? Publish to Confluence directly (Section 6b)
- [ ] Share in Slack if requested (Section 6c)
```

### Autonomy Rules

- **Run autonomously**: Auth check, checkpoint lookup, local debug, monitoring,
  BQ metrics extraction, experiment registry updates, W&B link retrieval
- **NEVER launch without explicit user approval**: Any `bazel run` that submits
  to Roboflow (train-scene-enc, eval-scene-enc, train-eval-scene-enc) costs GPU
  time ($100-$10K per run). Always present the exact command and estimated cost
  to the user and wait for explicit "go ahead" / "launch it" / "yes" before
  executing. Do NOT launch jobs as part of autonomous plan execution.
- **ALWAYS confirm `--business_attribution` before launch**: Run `select-gpu-quota`
  to recommend a quota path, present the recommendation with the quota table, and
  wait for the user to approve the specific value. This is a separate approval
  from the launch approval -- even if the user said "launch it", confirm the
  quota path explicitly if it hasn't been reviewed yet.
- **Ask user before**: Publishing results to Confluence/Slack/Google Doc
- **Stop and report**: Auth refresh fails, ambiguous checkpoint choice, job failure
  requiring user decision

### Analysis Automation Checklist

After any eval or train-eval run resolves, automatically:

1. Use lumen_agent to discover BQ tables from artifacts (detection_3d + inference_metrics)
2. Run detection queries: summary, precision-by-range, match distribution, class dist
3. Run trajectory queries: ADE/FDE, KCM, hard brake, NMC violations, route compliance
4. Extract W&B link from streaming_metrics
5. Update `~/.cursor/nvidia_training_experiments.yaml` with all metrics
6. Compare against baseline (Section 4g) and previous experiments
7. Report summary to user with delta from baseline (both detection AND trajectory)

## 8. MCP Tool Preferences

| Task | Preferred MCP | Tool | Notes |
|------|---------------|------|-------|
| Read Google Docs | `user-google-docs` | `readDocument` | Pass the document ID from the URL. Prefer over Glean for Google Doc access. |
| Query W&B metrics | `user-wandb` | `query_wandb_tool` | GraphQL against W&B Models API. Use `sampledHistory` for time-series data. |
| Query Roboflow runs | `project-0-cruise-ladybug-agents` | `lumen_agent` | For run status, artifacts, checkpoint paths, W&B URLs. |
| Search internal docs | `user-glean` | `search` / `chat` | For broad search across Confluence, Slack, code. Use Google Docs MCP for specific doc reads. |

### W&B MCP Example (live training monitoring)

```graphql
query RunInfo($entity: String!, $project: String!, $runName: String!) {
  project(name: $project, entityName: $entity) {
    run(name: $runName) {
      state summaryMetrics historyLineCount historyKeys
    }
  }
}
# variables: {"entity": "cruise", "project": "e2e_training", "runName": "<trainer_substrate_run_id>"}
```

Parse `summaryMetrics` (JSON string) to extract: `epoch`, `trainer/samples_seen`,
`train-step/total_loss`, `optimizer/lr-Adam`, `mini_batch_optimizer_steps`.

### Google Docs MCP Example

```
CallMcpTool:
  server: user-google-docs
  toolName: readDocument
  arguments:
    documentId: "1QPIz9dgkrLhOGfBkEbbs-NssIKXQn2_pPloTGyDffLg"
```

Document ID is the long string between `/d/` and `/edit` in the Google Docs URL.

## 9. Related Skills

| Skill | When to use |
|-------|-------------|
| `select-gpu-quota` | Pick best `--business_attribution` before submitting a training job |
| `cruise-auth-refresh` | GCP/Cruise auth expired |
| `nvidia-featurization` | Run the featurization pipeline (Stage 1 + 2) |
| `analyze-olympus-runs` | BQ/Centra queries for run artifacts, configs, RPS |
| `analyze-wandb` | Structured W&B run comparison |
| `confluence-publish` | Publish image-light content to Confluence |
| `write-technical-report` | Structure experiment reports |
| `slack-thread-reply` | Share results in Slack |
| `rebase-to-develop` | Sync branch when user requests it (NOT required for launch -- see 2b-1) |
| `run-notebook-to-html` | Execute `nvidia_olympus_eval.ipynb` for visual validation |
