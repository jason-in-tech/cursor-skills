# NVIDIA Featurization Pipeline: Run, Monitor, Debug

Automates the iterative workflow: **run pipeline → poll → check errors → diagnose → fix → rerun**.

**Reference Documents**:
- [Nvidia Data Specification](https://generalmotors-my.sharepoint.com/:w:/g/personal/kzfz9h_nam_corp_gm_com/IQCOorx9yCmESr-fZxhbWqhfAaEW8bHCOdffpApvZLSKczI?e=RooXsR) -- sensor layout, data format, label schema
- [Nvidia Data Consumption Strategy](https://generalmotors-my.sharepoint.com/:w:/g/personal/kzfz9h_nam_corp_gm_com/IQC-vWZUbA4KT52N894s89b4AR8cU1sph1UU5D8O1l1MNDQ?e=PKE9HV) -- ingestion plan, pipeline strategy
- [Platform Comparison and Integration Report](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1792737336) -- camera mapping, calibration bugs (Bug 1: transform direction, Bug 2: optical_joint duplication), MSL label gaps
- [NVIDIA Data Training / Eval Plan](https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/1972702552) -- training phases, hyperparameters, re-featurization status

## Required MCP: cruise-ladybug-agents

This skill depends on the `project-0-cruise-ladybug-agents` MCP server for extracting
Roboflow run artifacts. Both Stage 1 and Stage 2 produce a `job_id` with a random suffix
in their Roboflow output artifact -- this suffix is required for downstream data loading
and must be extracted via `lumen_agent`.

**At the start of ANY pipeline workflow**, verify the MCP is available by checking that
`project-0-cruise-ladybug-agents-lumen_agent` appears in your available tools list.

**If **`cruise-ladybug-agents`** is NOT available**: STOP immediately and tell the user:
> "The `cruise-ladybug-agents` MCP server is required for this workflow but is not enabled.
> Please add it in Cursor Settings → MCP, then tell me to continue."

Do NOT attempt to work around a missing MCP by guessing job IDs or parsing table names.

The pipeline has two stages:
- **Stage 1 (Featurization)**: Processes raw NVIDIA sensor data into per-tick model features.
- **Stage 2 (Map + Intent)**: Enriches Stage 1 output with map features and intent labels.

## 0. Pre-flight: Authentication

Before ANY pipeline run, BQ query, or `bazel run` that talks to cloud services, verify auth:

```bash
gcloud auth application-default print-access-token 2>&1 | head -1
```

**If the output contains "Reauthentication", "refresh", or "error"**: Attempt automated
refresh by following the `cruise-auth-refresh` skill (`~/.cursor/skills/cruise-auth-refresh/SKILL.md`).
This uses an expect script + @playwright/mcp browser automation to complete the OAuth flow
without user intervention. Only STOP and ask the user if the automated refresh fails
(e.g., unsupported 2FA, CAPTCHA, missing `~/.cruise-google-creds`).

**If the output is a long token string starting with **`ya29.`: Auth is valid, proceed.

Run this check:
- Once at the start of any pipeline workflow
- Again if any command fails with auth-related errors (`Reauthentication`, `401`,
`credentials`, `Permission denied`, `access token`)

## 1. Stage 1: Featurization Pipeline

### Worker tier guidelines

| Tier | `--limit` | `--max_num_workers` | `--machine_type` | Use case |
| --- | --- | --- | --- | --- |
| **Sanity check** | 10 | (default) | (default) | Quick smoke test after code changes |
| **Small validation** | 1000 | 200 | (default) | Validate fix on meaningful data volume |
| **Full production** | (none) | 625 | `n4-custom-4-256000-ext` | Full dataset featurization |

### Run strategy: parallel small + large

To save time, kick off BOTH the small validation run and the full production run
simultaneously in separate terminals. The small run finishes first and acts as a canary:

- **Small run passes** → large run is already in flight, just wait for it.
- **Small run fails** → diagnose and fix while the large run is still building/running.
Cancel the large run if the fix requires code changes (the large run will fail too).

Both runs share the same code (same local build), so a systemic code bug will affect both.
Data-availability errors (e.g., one VIN missing camera data) may differ between runs.

**Committing is NOT required before submitting.** `bazel run` builds the Docker
image from the local working tree (including uncommitted changes) and pushes it to
the container registry. The git hash is only used for the image tag, not for
selecting what code goes into the build. You can commit later for traceability.

### Sanity check run

```bash
bazel run //cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/cloud_pipeline:orchestration -- \
  --external_data_source nvidia --enable_msl \
  --limit 10 \
  -e <experiment_name>_test
```

### Small validation run

```bash
bazel run //cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/cloud_pipeline:orchestration -- \
  --external_data_source nvidia --enable_msl \
  --max_num_workers=200 --limit 1000 \
  -e <experiment_name>
```

### Full production run

```bash
bazel run //cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/cloud_pipeline:orchestration -- \
  --external_data_source nvidia --enable_msl \
  --max_num_workers=625 \
  --machine_type n4-custom-4-256000-ext \
  -e <experiment_name>
```

All commands should run in **separate background terminals** (`block_until_ms: 0`).
Monitor by periodically reading their terminal output files.

### Stage 1 key flags

| Flag | Purpose |
| --- | --- |
| `--external_data_source nvidia` | Use NVIDIA data (vs dcv1) |
| `--enable_msl` | Enable MSL label features |
| `--vin <VIN>` | Filter to a specific vehicle (optional) |
| `--limit N` | Limit number of segments |
| `-e <name>` | Experiment name (used in table names) |
| `--max_num_workers N` | Worker pool size (see worker tier table above) |
| `--machine_type` | Worker machine type (use `n4-custom-4-256000-ext` for full runs) |

### Stage 1 output

On success, Stage 1 produces three types of IDs:

| ID | Example | Where to find it |
| --- | --- | --- |
| **Roboflow run ID** | `90ec667cbc0e47b6a689e4785dd4cae5` | Printed in terminal as `https://centra.robot.car/roboflow/runs/<run_id>` |
| **Stage 1 job_id** (with random suffix) | `trajectory_ranking_external_data_mapper_2026_03_21_020107_nvidia_jl_nvidia_multi_stream_1_b5zli` | Roboflow output artifact via `lumen_agent` (see below) |
| **Dataflow job ID** | `2026-03-20_19_02_01-9348326127973538532` | `gcloud dataflow jobs list` |

**The Stage 1 **`job_id`** (with the random suffix like **`_b5zli`**) is what Stage 2 needs as **`--job_ids`**.**

This suffix is NOT derivable from the BQ table name or Dataflow job listing. It is stored
in the Roboflow run's output artifact and must be extracted via the `lumen_agent` MCP tool.

### Extract Stage 1 job_id via lumen_agent

Both stages follow the same extraction pattern: Roboflow run -> `lumen_agent` ->
`job_id` with random suffix from the output artifact. See also "Stage 2 output" in
Section 1b for the identical pattern applied to Stage 2.

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "Get the job_id from the output artifact of Roboflow run <run_id>.
            I need the top-level job_id field (not job_info.job_id or
            job_info.dataflow_job_info.job_id). It should look like
            trajectory_ranking_external_data_mapper_<date>_nvidia_<experiment>_<suffix>."
    start_fresh_session: true
```

The `lumen_agent` will query the Roboflow GraphQL API and return the `job_id` from
`outputArtifact.jsonRepresentation`. Use this value as `--job_ids` for Stage 2.

**IMPORTANT**: The BQ table names do NOT include the Roboflow suffix. Never derive
the `job_id` from BQ table names -- always extract it from the Roboflow output artifact.

## 1b. Stage 2: Map + Intent Enrichment

**Prerequisites**: Stage 1 must have completed successfully with training rows > 0.

### Verify Stage 2 config exists on the current branch

Before running Stage 2, confirm that the NVIDIA map+intent config is present on
the current branch. Check for the `nvidia_map_and_intent` config name:

```bash
rg 'nvidia_map_and_intent' cruise/mlp/cfs/projects/trajectory_ranking/mappers/data_mapper_configs.py
```

**If found**: Stage 2 code is on this branch (cherry-picked from
`jl/nvidia-map-intent-datagen`). Proceed without switching branches.

**If NOT found**: STOP and tell the user:
> "The `nvidia_map_and_intent` Stage 2 config is missing from the current branch.
> It may need to be cherry-picked from `jl/nvidia-map-intent-datagen` or another
> branch that has the Stage 2 data mapper config."

### Determine the experiment name (-e)

**Reuse the same experiment name from Stage 1.** Extract it from the Stage 1 `job_id`:

```
trajectory_ranking_external_data_mapper_<date>_nvidia_<experiment_name>_<random_suffix>
```

For example, from `trajectory_ranking_external_data_mapper_2026_03_21_020107_nvidia_jl_nvidia_multi_stream_1_b5zli`,
the experiment name is `jl_nvidia_multi_stream_1` (everything between `_nvidia_` and the
final `_<random_suffix>`). The random suffix is always a short alphanumeric string (5-6 chars).

Do NOT ask the user for the experiment name -- derive it from the Stage 1 job_id.

### Run Stage 2

```bash
bazel run --//ros/src/triton:triton_direct_streaming=True \
  //cruise/mlp/cfs/projects/trajectory_ranking/orchestration:data_mapper -- \
  -e <experiment_name> \
  -v derived_stage_1_v1 \
  --data_mapper_config_name nvidia_map_and_intent \
  --seq_length 16 \
  --machine_type n4-custom-8-307200-ext \
  --job_ids <stage1_job_id> \
  --row_group_size 16 \
  --flexrs_goal=COST_OPTIMIZED \
  --max_num_workers 625 \
  --redo_split \
  --save_full_dataset \
  --disable_data_quality \
  --input_time_field _time_requested \
  --enable_next_gen_map
```

### Stage 2 key flags

| Flag | Purpose |
| --- | --- |
| `--job_ids <stage1_job_id>` | Stage 1 job_id extracted via `lumen_agent` (includes random suffix) |
| `--data_mapper_config_name nvidia_map_and_intent` | Config for map + intent enrichment |
| `--seq_length 16` | Sequence length for sequential dataset |
| `--row_group_size 16` | Parquet row group size |
| `--flexrs_goal=COST_OPTIMIZED` | Use Flex RS for cost savings |
| `--max_num_workers 625` | Worker pool size (Stage 2 is heavier) |
| `--redo_split` | Recompute train/val/test splits |
| `--save_full_dataset` | Save the complete dataset (not just splits) |
| `--disable_data_quality` | Skip data quality checks (already done in Stage 1) |
| `--input_time_field _time_requested` | Time field for input data alignment |
| `--enable_next_gen_map` | Use next-gen tile loader map (better coverage for NVIDIA locations; without this, ~50K additional "no lane boundaries" errors) |
| `--//ros/src/triton:triton_direct_streaming=True` | Bazel config flag for Triton streaming |

### Stage 2 output

On success, Stage 2 produces the same types of IDs as Stage 1:

| ID | Example | Where to find it |
| --- | --- | --- |
| **Roboflow run ID** | `959799ccf2184d80a4b874bc77f81fe3` | Printed in terminal as `https://centra.robot.car/roboflow/runs/<run_id>` |
| **Stage 2 job_id** (with random suffix) | `trajectory_ranking_data_mapper_2026_03_22_180231_jl_nvidia_multi_stream_2_derived_stage_1_v1_ahaye` | Roboflow output artifact via `lumen_agent` |
| **Dataflow job ID** | `2026-03-22_...` | `gcloud dataflow jobs list` |

**The Stage 2 **`job_id`** (with the random suffix like **`_ahaye`**) is what goes into **`dataset_config.py`**.**

Extract it the same way as Stage 1:

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "Get the job_id from the output artifact of Roboflow run <run_id>.
            I need the featurized_dataset.job_id field. It should look like
            trajectory_ranking_data_mapper_<date>_<experiment>_<version>_<suffix>."
    start_fresh_session: true
```

**IMPORTANT**: The BQ table names do NOT include the Roboflow suffix. Never derive
the `job_id` from BQ table names -- always extract it from the Roboflow output artifact.

## 2. Poll and Diagnose via Roboflow + Lumen

### 2a. Poll for completion

After `bazel run` prints a Roboflow URL like `https://centra.robot.car/roboflow/runs/<run_id>`:

```bash
bazel run //cruise/e2e_gym:roboflow_job_status -- <run_id> --poll-for-completed \
  --timeout-sec 14400 --poll-interval-sec 60
```

- Use `--timeout-sec 14400` (4 hours) for large runs.
- Run in the background (`block_until_ms: 0`), then periodically read the terminal output.
- If polling fails with 404 immediately after submission, wait 60s and retry (job not yet
registered).

### 2b. Check run state (quick, non-blocking)

**IMPORTANT**: `roboflow_job_status` reports the **latest state transition**, NOT the
terminal state. A run showing `"state": "RAN"` is NOT necessarily complete — it only
means the Dataflow job finished running; the orchestrator may still be processing
downstream steps.

To check the current state transition:

```bash
bazel run //cruise/e2e_gym:roboflow_job_status -- <run_id>
```

State transitions from `roboflow_job_status`:
- `RESOLVED` → completed and finalized
- `RAN` → Dataflow job ran, but **downstream steps may still be running**
- `NESTED_FAILED` → a sub-step (Dataflow job) crashed
- `FAILED` → the orchestrator step itself failed

**Always verify the terminal state** using the debug script (2c) which checks
`future_state`. Do NOT rely solely on `roboflow_job_status` to determine completion.

### 2c. Verify terminal state and diagnose errors via debug script

**Always run this after **`roboflow_job_status`** to confirm the run is truly done.** The
`future_state` field is the authoritative terminal state.

```bash
bazel run //cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/notebooks:debug_roboflow_errors -- <run_id>
```

This prints:
- `future_state`: The **authoritative terminal state** of the root run
(`FutureState.RESOLVED` = done, `FutureState.FAILED` / `FutureState.NESTED_FAILED` = error)
- `stack_trace`: Orchestrator-side traceback (e.g., Terra job wait timeout)
- `ai_platform_error`: Worker-side traceback from the Dataflow job — this usually
contains the actual Python exception (e.g., fastavro crashes, import errors, OOM)
- **Nested run count and failure breakdown**

**If **`future_state`** is **`FutureState.RAN`** (not **`RESOLVED`**)**: The run is NOT done.
`RAN` means the Dataflow job finished but the orchestrator is still writing BQ tables.
Do NOT proceed to BQ checks. Wait 5-10 minutes and re-run `debug_roboflow_errors`.
Repeat until you see `FutureState.RESOLVED` or a failure state.

A run showing `FutureState.RAN` with `Total failed: 0 / N` is especially deceptive --
it looks like success but the pipeline is still processing.

### 2d. Interpreting Roboflow errors

| `future_state` | Error table exists? | What happened | Next step |
| --- | --- | --- | --- |
| `RESOLVED` | Yes (may be empty) | Pipeline completed | Check BQ tables (Section 3) |
| `RESOLVED` | Yes, has rows | Some chunks failed, others succeeded | Check error distribution |
| `RAN` | Usually missing | Dataflow finished, orchestrator still writing tables | **Wait 5-10 min**, re-run `debug_roboflow_errors` |
| `NESTED_FAILED` | Usually empty | Dataflow worker crashed hard | Check `ai_platform_error` in debug script |
| `FAILED` | No | Orchestrator failed before Dataflow | Check `stack_trace` in debug script |
| Not yet set | -- | **Run is still in progress** | Wait and re-check |

**Common **`NESTED_FAILED`** causes from **`ai_platform_error`:
- `fastavro TypeError: 'NoneType' object is not iterable` → A struct/array column
(e.g., `msl_labels_scene`) is `None` instead of a valid value. Fix: error out early
in the data adapter so the chunk goes to the error table, not to Avro serialization.
- `OOM` / `Resource exhausted` → Increase `--machine_type` memory.
- `ModuleNotFoundError` → Missing dependency in the Docker image BUILD target.
- `google.auth.exceptions.RefreshError` → Auth expired during the job. Re-auth and rerun.

### 2e. Workflow when BQ error table is empty but pipeline failed

1. Run `roboflow_job_status` to confirm state is `NESTED_FAILED`
2. Run `debug_roboflow_errors` to get the `ai_platform_error` traceback
3. Read the traceback to identify the crashing line (usually in the Dataflow worker code)
4. Fix the code, then rerun both small + large

### 2f. CRITICAL: Do NOT check BQ tables until future_state is RESOLVED

The pipeline writes tables in stages: segments table first, then error table, then
training tables. If you check BQ before the pipeline is fully done, you will see
incomplete results (e.g., missing error table, 0 training rows) and draw wrong
conclusions.

**Symptom pattern of checking too early** (observed in practice):
- Segments table: populated (e.g., 1000 rows) -- written first
- Error table: does not exist yet
- Training/val tables: exist but have 0 rows -- created as empty shells, populated last

If you see this pattern, the run is almost certainly still writing. Re-check
`future_state` via `debug_roboflow_errors` and wait for `RESOLVED`.

**Correct workflow:**
1. `roboflow_job_status` shows terminal-looking state (`RAN`, `RESOLVED`, etc.)
2. Run `debug_roboflow_errors` → confirm `future_state` is `FutureState.RESOLVED`
3. **Only then** query BQ tables for row counts, error distribution, etc.

If `future_state` is not yet set or still in progress, **wait and re-check**.

### 2g. Inspect run artifacts via lumen_agent

The `lumen_agent` MCP tool can query any Roboflow run's artifacts, config, and metadata
via the Lumen GraphQL API. Use it when you need information not available from the
`debug_roboflow_errors` script or `roboflow_job_status`:

```
CallMcpTool:
  server: project-0-cruise-ladybug-agents
  toolName: lumen_agent
  arguments:
    query: "<your question about the run>"
    start_fresh_session: true
```

**Primary use case**: Extract `job_id` with Roboflow suffix from output artifacts.
Both Stage 1 and Stage 2 follow the same pattern:
1. Get the Roboflow run ID from the terminal output (printed as a centra.robot.car URL)
2. Query `lumen_agent` for the `job_id` in the output artifact's `jsonRepresentation`
3. The returned `job_id` includes the Roboflow suffix (e.g., `_b5zli`, `_ahaye`)
4. Use this `job_id` directly downstream (Stage 1's -> Stage 2 `--job_ids`,
Stage 2's -> `dataset_config.py`)

Other useful queries:
- Inspect input/output artifact schemas
- Check run config parameters
- Get nested run tree and their states
- Search for runs by name/date when you don't have the run ID

The `lumen_agent` uses a GraphQL agent under the hood -- ask in natural language and
it will construct the appropriate query. Include the Roboflow run ID in your question.

## 3. Check Results

### Output table naming

Tables live in `cruise-mlp-prod-13d0.datasets_dev`.

**Stage 1** tables follow this pattern:

```
error_table_nvidia_<experiment>_<run_id>
segments_table_nvidia_<experiment>_<run_id>
trajectory_ranking_external_data_mapper_<date>_nvidia_<experiment>_<version>__train_1
trajectory_ranking_external_data_mapper_<date>_nvidia_<experiment>_<version>__val_1
trajectory_ranking_external_data_mapper_<date>_nvidia_<experiment>_<version>__test_1
```

**Stage 2** tables follow a different pattern (no `nvidia` prefix, includes version):

```
trajectory_ranking_data_mapper_<date>_<experiment>_<version>__train_1
trajectory_ranking_data_mapper_<date>_<experiment>_<version>__val_1
trajectory_ranking_data_mapper_<date>_<experiment>_<version>__test_1
trajectory_ranking_data_mapper_<date>_<experiment>_<version>__filtered_1
```

For example: `trajectory_ranking_data_mapper_2026_03_22_024008_jl_nvidia_multi_stream_1_derived_stage_1_v1__train_1`

Stage 2 also produces a `__filtered_1` split (not present in Stage 1).

### Find tables

Run all three queries in parallel to save time:

```bash
# Query 1: Find all tables for the experiment (Stage 1 + Stage 2)
# Use INFORMATION_SCHEMA.TABLES — NOT __TABLES__ (fails at 500k tables).
# Search by experiment name without 'nvidia' prefix since Stage 2 tables omit it.
bq query --use_legacy_sql=false --format=csv --max_rows=20 "
SELECT table_name, creation_time
FROM \`cruise-mlp-prod-13d0.datasets_dev.INFORMATION_SCHEMA.TABLES\`
WHERE table_name LIKE '%<experiment>%'
ORDER BY creation_time DESC LIMIT 20"
```

```bash
# Query 2: Training row count (substitute actual table name from Query 1)
bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as row_count
FROM \`cruise-mlp-prod-13d0.datasets_dev.<train_table>\`"
```

```bash
# Query 3: Error distribution
bq query --use_legacy_sql=false --format=csv "
SELECT ERROR_CODE, COUNT(*) as cnt
FROM \`cruise-mlp-prod-13d0.datasets_dev.<error_table>\`
GROUP BY ERROR_CODE ORDER BY cnt DESC"
```

Always run Query 1 first, then run Queries 2, 3, and 4 in parallel once you have the table names.

### Stage 2 monitoring notes

Stage 2 behaves differently from Stage 1 during monitoring:

1. **Flex RS delayed start**: Stage 2 uses `--flexrs_goal=COST_OPTIMIZED`, which means the
Dataflow job may take 15-25 minutes to start after submission. This is normal.
1. **Empty tables until completion**: BQ split tables (train/val/test/filtered) are created
immediately as empty shells. Data is only written when the Dataflow job completes.
**Do NOT interpret 0 rows as failure while the Dataflow job is still running.**
1. **Check Dataflow state directly**: Since `debug_roboflow_errors` may not exist on the
Stage 2 branch, use `gcloud dataflow` to check the actual job state:

```bash
# Find the Dataflow job (look for the experiment name in the job name)
gcloud dataflow jobs list --region=us-central1 --status=active \
  --format="table(id,name,currentState,createTime,startTime)"

# Check a specific job's state
gcloud dataflow jobs describe <dataflow_job_id> --region=us-central1 \
  --format="table(id,currentState,createTime,startTime)"
```

1. **Roboflow state **`RAN`: For Stage 2, `RAN` persists while the Dataflow job is still
running. Only after the Dataflow job completes and tables are populated does it transition
to `RESOLVED`. Do NOT panic if `RAN` persists for 30-60+ minutes.
1. **Timeline expectation**: Submission -> Dataflow created (~15 min) -> Flex RS starts
(~20-25 min after submission) -> Execution (~30-60 min) -> RESOLVED (~60-90 min total).

### Validate Stage 2 data quality

After Stage 2 completes, check for map/intent columns and error coverage:

```bash
bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(*) as total,
  COUNTIF(datamapper_error IS NOT NULL AND datamapper_error != '') as rows_with_errors,
  COUNTIF(intent_generation_input_city_name IS NOT NULL) as rows_with_intent
FROM \`cruise-mlp-prod-13d0.datasets_dev.<stage2_train_table>\`"
```

**What to look for**:
- `rows_with_intent` should be close to `total` (map+intent enrichment succeeded)
- `rows_with_errors` should be 0 or very low
- If `rows_with_errors` is high, check `datamapper_error` and `datamapper_exc_trace`
columns for failure details

### Validate MSL label quality (Query 4)

After confirming training rows > 0, verify that MSL labels contain real data.

**IMPORTANT**: MSL labels are stored as **base64-encoded ZIP-compressed numpy arrays**
in per-tick columns (`msl_labels_box_0`, `msl_labels_valid_mask_0`, etc.), NOT as nested
struct columns. A column being non-NULL does NOT mean it has real label data — you must
decode the arrays and check for non-zero values.

#### Step 1: Discover MSL label columns

```bash
bq query --use_legacy_sql=false --format=csv "
SELECT column_name
FROM \`cruise-mlp-prod-13d0.datasets_dev.INFORMATION_SCHEMA.COLUMNS\`
WHERE table_name = '<train_table>'
  AND column_name LIKE 'msl_labels%'
  AND column_name NOT LIKE '%camera%'
  AND column_name NOT LIKE '%image%'
ORDER BY column_name"
```

Key columns to look for per tick (e.g., `_0`, `_6`):
- `msl_labels_valid_mask_<tick>` — boolean array `(1, 400)`, True for valid objects
- `msl_labels_box_<tick>` — float32 `(1, 400, 8)`, 3D bounding boxes
- `msl_labels_kinematics_<tick>` — float32 `(1, 400, 5)`, velocity/heading
- `msl_labels_fine_grained_semantic_class_<tick>` — object class IDs
- `msl_labels_object_id_<tick>` — unique object tracking IDs
- `msl_labels_num_lidar_points_<tick>` — lidar point counts per object

#### Step 2: Decode and validate array contents

NULL checks alone are insufficient — columns can be non-NULL but contain all-zero arrays
(meaning no labeled objects exist). **Decode the numpy arrays** to check actual values:

```bash
bq query --use_legacy_sql=false --format=json --max_rows=5 "
SELECT
  msl_labels_box_0 as box,
  msl_labels_valid_mask_0 as valid_mask,
  msl_labels_kinematics_0 as kinematics,
  msl_labels_num_lidar_points_0 as lidar_pts
FROM \`cruise-mlp-prod-13d0.datasets_dev.<train_table>\`
LIMIT 5" 2>&1 | python3 -c "
import json, sys, base64, io, zipfile, numpy as np

data = json.load(sys.stdin)
for i, row in enumerate(data):
    print(f'=== Row {i} ===')
    for key in ['box', 'valid_mask', 'kinematics', 'lidar_pts']:
        val = row.get(key)
        if val is None:
            print(f'  {key}: NULL')
            continue
        try:
            raw = base64.b64decode(val)
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                arr = np.load(io.BytesIO(zf.read(zf.namelist()[0])))
            non_zero = np.count_nonzero(arr)
            print(f'  {key}: shape={arr.shape}, dtype={arr.dtype}, '
                  f'non_zero={non_zero}/{arr.size}, min={arr.min():.4f}, max={arr.max():.4f}')
        except Exception as e:
            print(f'  {key}: decode error ({e})')
"
```

#### Step 3: Check valid_mask coverage across the full dataset

The `valid_mask` is the authoritative signal — it tells you how many labeled objects
exist per row. Check whether ANY rows have valid objects:

```bash
bq query --use_legacy_sql=false --format=json "
SELECT
  COUNT(*) as total_rows,
  msl_labels_valid_mask_0 as vm
FROM \`cruise-mlp-prod-13d0.datasets_dev.<train_table>\`
GROUP BY vm
LIMIT 10" 2>&1 | python3 -c "
import json, sys, base64, io, zipfile, numpy as np

data = json.load(sys.stdin)
for row in data:
    raw = base64.b64decode(row['vm'])
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        arr = np.load(io.BytesIO(zf.read(zf.namelist()[0])))
    print(f'total_rows={row[\"total_rows\"]}, valid_objects={arr.sum()}, any_valid={arr.any()}')
"
```

#### What to look for

| Result | Meaning | Action |
| --- | --- | --- |
| `valid_mask` has True values, `box` has non-zero floats | Labels are real and valid | Proceed to training |
| `valid_mask` all False, `box` all zeros, across ALL rows | No MSL labels in this dataset | **Expected for NVIDIA external data** (MSL labels come from Cruise's internal labeling pipeline). Training can proceed but the model won't learn from 3D object labels. |
| `valid_mask` has True values but `box` is all zeros | Label processing bug | Check `msl_labels_feature.py` and the data adapter |
| Some rows have valid labels, others don't | Mixed coverage | Normal — not all frames have labeled objects. Check the ratio. |
| Columns are NULL (not just zero arrays) | Columns not populated | Check if `--enable_msl` was passed in Stage 1 |

**NVIDIA data and MSL labels**: NVIDIA external data typically has **no MSL labels**
because MSL (Machine-Scale Labeling) is Cruise's internal annotation pipeline. The
featurization pipeline creates MSL columns with correct shapes `(1, 400, N)` but fills
them with zeros. This is structurally valid (model code won't break) but means no 3D
object supervision. If you need object labels for NVIDIA data, a separate labeling
pipeline must run first.

### Update dataset_config.py with Stage 2 data

After Stage 2 completes, update `dataset_config.py` with the Stage 2 `job_id`
extracted via `lumen_agent` (see "Stage 2 output" in Section 1b). The data loader
resolves the GCS parquet path automatically via CMLD -- no manual GCS path lookup needed.

```python
NVIDIA_MAP_AND_INTENT_TRAIN_SET_SIZE = <row_count_from_bq>
NVIDIA_MAP_AND_INTENT = MultiDatasetSpec(
    [
        JobSpec(
            job_id="<job_id_from_lumen_agent>",  # includes RF suffix, e.g. ...v1_ahaye
            dataset_ref=ArtifactRef.NOT_SET,
            split_specs=[
                SplitSpec(None, None, Weights(train=1.0, val=0.0, test=0.0), False),
            ],
            job_id_source=JobIdSource.IL,
        ),
    ]
)
```

#### How data loading works (under the hood)

Two lookups happen when the data loader initializes from a `job_id`:

1. **CMLD (GCS parquet path)**: `dataset/utils.py` calls `job_id.rsplit("_", 1)[0]`
to strip the RF suffix, then resolves `trajectory_ranking__<stripped_id>__<split>`
via `get_existing_ml_dataset()` to get the GCS URL.

1. **Lineage (BQ table validation)**: `get_table_names_for_job_id(job_id)` calls the
lineage system with the **full** `job_id` (including suffix) to get the set of
known BQ tables.

Both lookups succeed when the `job_id` has the real Roboflow suffix:

| `job_id` in config | CMLD | Lineage | Result |
| --- | --- | --- | --- |
| `...v1_ahaye` (real suffix) | strips `_ahaye` -> correct | finds job -> correct | **Works** |
| `...v1_x` (dummy) | strips `_x` -> correct | 404 | Needs patch |
| `...v1` (no suffix) | strips `_v1` -> **wrong** | 404 | **Broken** |

**Rule**: Always use the actual Roboflow job_id with its suffix.

### Compare yield across runs

When evaluating yield improvements, compare these metrics between the old and new runs:

```bash
# Error distribution comparison
bq query --use_legacy_sql=false --format=csv --project_id=cruise-mlp-prod-13d0 '
SELECT error_code, COUNT(*) as cnt, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as pct
FROM `cruise-mlp-prod-13d0.datasets_dev.<error_table>`
GROUP BY error_code
ORDER BY cnt DESC'

# NUM_TICKS_MISMATCH got=N breakdown (key yield indicator)
bq query --use_legacy_sql=false --format=csv --project_id=cruise-mlp-prod-13d0 '
SELECT REGEXP_EXTRACT(error_message, r"got (\d+)") as got_ticks, COUNT(*) as count
FROM `cruise-mlp-prod-13d0.datasets_dev.<error_table>`
WHERE error_code = "ERROR_SEQUENTIAL_DATASET_CREATOR_NUM_TICKS_MISMATCH"
GROUP BY got_ticks ORDER BY count DESC'

# GCE metadata transient errors (should be 0 after Fix C)
bq query --use_legacy_sql=false --format=csv --project_id=cruise-mlp-prod-13d0 '
SELECT
  SUM(CASE WHEN error_message LIKE "%metadata.google.internal%" THEN 1 ELSE 0 END) as gce_transient,
  SUM(CASE WHEN error_message LIKE "%No MSL label data found%" THEN 1 ELSE 0 END) as no_msl_labels,
  COUNT(*) as total_unknown
FROM `cruise-mlp-prod-13d0.datasets_dev.<error_table>`
WHERE error_code = "ERROR_UNKNOWN"'
```

**Key indicators of yield improvement:**
- got=14-15 share of TICKS_MISMATCH should decrease (boundary ticks recovered)
- GCE metadata transient errors should be 0 (retry working)
- ERROR_UNKNOWN % should decrease (transient errors retried)
- Total training rows should increase ~20% vs. previous run

### Pull failing chunks for local debugging

```bash
bq query --use_legacy_sql=false --format=csv --max_rows=50 "
SELECT DISTINCT vehicle_id, chunk_start_sec_utc_int, chunk_end_sec_utc_int
FROM \`cruise-mlp-prod-13d0.datasets_dev.<error_table>\`
WHERE ERROR_CODE = '<target_error_code>'
LIMIT 50"
```

### Error table schema

| Column | Description |
| --- | --- |
| `ERROR_CODE` | e.g. `ERROR_CAMERA_DATA_NOT_CONTINUOUS`, `ERROR_CAMERA_DATA_NOT_FOUND` |
| `ERROR_MESSAGE` | Full error string from the DoFn |
| `vehicle_id` | VIN or UUID segment ID |
| `chunk_start_sec_utc_int` / `chunk_end_sec_utc_int` | 10-second chunk boundaries |
| `segment_start_sec_utc_int` / `segment_end_sec_utc_int` | Full segment boundaries |

## 4. Common Error Codes and Diagnoses

### ERROR_CAMERA_DATA_NOT_CONTINUOUS

**Source**: `camera_feature.py` line ~155. `sync_with_rate_trigger` produced null ticks.

**Known issue**: NVIDIA 2021-era vehicles (UUID VINs) have a 50/40/30ms frame gap pattern
producing ~15ms age, failing the 10ms threshold. 2023+ vehicles (W1K VINs) have 30/30/40ms
and fit within 10ms. Fix: increase `data_max_age_ms` in camera_feature.py (line ~144).

### ERROR_CAMERA_DATA_NOT_FOUND

Empty camera DataFrame. Data availability issue, not a code bug.

### Index out of bounds / DataFrame is empty

**Source**: `msl_labels_feature.py`. Accessing columns on empty DataFrames after filtering.
**Fix**: Add `if df.is_empty(): return self._empty_result()` guard before column access.

### ERROR_UNKNOWN with "No MSL label data found for segment"

**Source**: `create_model_features.py`. The `msl_labels_scene` column exists but all values
are null — the `obstacle_v2` table has no labels for the given time range.

**Cause**: Not all VINs/time ranges have MSL label data. If `--vin` is set, the pipeline
will fail for every chunk from VINs without labels.

**Fix**: Do NOT use `--vin` when running with `--enable_msl`, unless you have confirmed
that the VIN has MSL label coverage for the target time range. Without `--vin`, the
pipeline picks from VINs that have labels (chunks without labels are logged as errors).

### Missing polynomial

**Source**: Odometry/polynomial feature. Data availability issue for that segment.

### ERROR_UNKNOWN with "metadata.google.internal" (GCE metadata transient)

**Source**: `attribute_generation_do_fn.py`. Google client libraries fail to reach the
GCE metadata server during ADC credential refresh on Dataflow workers.

**Fix (applied)**: `AttributeGenerationDoFn` now retries up to 3 times with exponential
backoff + jitter for errors containing `metadata.google.internal`. This eliminated ~30K
errors (4% of total) in the previous full production run.

### ERROR_SEQUENTIAL_DATASET_CREATOR_NUM_TICKS_MISMATCH

**Source**: `create_model_features.py`. Expected 16 non-NULL `msl_labels_scene` ticks
but got fewer. The `got=N` value in the error message shows how many ticks had labels.

**Breakdown by got=N (from full production run):**

| got | Count | Root cause | Fixable? |
| --- | --- | --- | --- |
| 2 | ~108K (41%) | Single ~1Hz observation burst covers only ~200ms of 1.6s chunk | No — need higher label frequency |
| 4 | ~65K (25%) | Two bursts but most tracklines only appear at one burst | No — fundamental data sparsity |
| 8-14 | ~77K (29%) | Boundary ticks clipped OR gaps from sparse tracklines | **Partially fixed** (see below) |
| 15 | ~9K (3%) | MSL dedup bug (now fixed) OR one boundary tick missing | **Fixed** |

**Yield improvements applied** (commit `f58f7b18`):
- **Removed tick clipping** (`msl_labels_feature.py`): Camera ticks outside
  `[first_burst, last_burst]` are no longer discarded. The per-trackline interpolation
  caps (`_MAX_EXTRAPOLATION_MS=200ms`, `_MAX_SINGLE_OBS_TOLERANCE_MS=50ms`) already
  enforce accuracy. This recovers ~2 boundary ticks per sequence.
- **Increased `_MAX_EXTRAPOLATION_MS` from 100→200ms**: At 200ms, constant-velocity
  extrapolation error is 6cm (well within NVIDIA label noise of ~10-20cm).

**Remaining unfixable**: got=2 and got=4 are fundamental data sparsity — NVIDIA
`obstacle_v2` labels arrive at ~1Hz, and many tracklines only appear in one burst.

### ERROR_SEQUENCE_SET_CREATOR_REMAINING_UNUSED_TICKS

**Source**: `sequence_set_creator.py`. Leftover ticks after greedy 16-tick extraction.

**~97% are benign**: These occur when a segment's total tick count is not a multiple
of 16. After extracting N complete 16-tick sequences, the leftover 1-15 ticks are
logged as errors. Only ~3% are genuine "set 0" errors from segments too short to
form any sequence.

**No fix needed**: This is expected pipeline behavior, not data loss.

### ERROR_DATASET_QUALITY_ISSUE with "NaN in longpos_odometry"

**Source**: `data_quality_do_fn.py`. NaN values in odometry features (~25K errors).

**Potential fix**: Interpolate over NaN odometry values using neighboring valid
measurements. Not yet implemented — requires validation of downstream model impact.

## 5. Local Debugging Pattern

To reproduce a specific failing chunk locally, create a debug script in
`cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/notebooks/` with a `cruise_py_binary`
BUILD target, then `bazel run` it. Core boilerplate:

```python
from cruise.mlp.behaviors.data.nvidia.data_loader.utils.iceberg_lake_client import (
    IcebergLakeClientWrapper,
)
from cruise.mlp.robotorch.project.trajectory_ranking.dcv_1.data_processor.features.dcv_1.utils.sync import (
    sync_with_rate_trigger,
)

client = IcebergLakeClientWrapper()
client.setup()

lf = client.query_data_to_lazy_df(
    namespace=client.get_sensor_namespace(),
    table_name="camera_front_wide_120fov",
    vin=vin, start_sec=start_sec, end_sec=end_sec,
    columns=["segment_id", "timestamp_sec_utc_in_ms"],
)
```

When debugging `sync_with_rate_trigger` issues, test multiple `data_max_age_ms` thresholds
and inspect the actual frame timestamps and ages per tick window.

## 6. Key Source Files

All paths relative to `cruise/mlp/robotorch/project/trajectory_ranking/dcv_1/`:

| File | Role |
| --- | --- |
| `cloud_pipeline/orchestration.py` | Stage 1 entry point, submits to Roboflow/Terra |
| `cloud_pipeline/utils/output_table_names.py` | Table naming: `error_table_nvidia_<exp>_<run_id>` |
| `data_processor/features/nvidia/camera_feature.py` | Camera sync, 10Hz downsampling, continuity check |
| `data_processor/features/nvidia/msl_labels_feature.py` | MSL label interpolation to 10Hz |
| `data_processor/features/dcv_1/utils/sync.py` | `sync_with_rate_trigger` implementation |
| `datatypes/camera_mappings.py` | `NVIDIA_TICK_CAM_NAME`, camera table mappings |
| `notebooks/debug_roboflow_errors.py` | Fetch Roboflow nested run failure details (stack traces) |
| `data_adapter/create_model_features.py` | Data adapter: MSL label processing, model feature creation |
| `cloud_pipeline/terra_transforms/attribute_generation_do_fn.py` | Attribute generation with GCE metadata retry logic |
| `data_processor/features/nvidia/tests/test_msl_boundary_extrapolation.py` | Tests for boundary extrapolation accuracy and caps |
| `cloud_pipeline/terra_transforms/tests/test_attribute_generation_retry.py` | Tests for GCE metadata retry behavior |

Stage 2 entry point: `cruise/mlp/cfs/projects/trajectory_ranking/orchestration/data_mapper`

## 7. Iterative Workflow

When asked to run and debug the pipeline, follow this loop. At each step, briefly tell the
user what you're doing and show key results (row counts, error distributions, diagnoses).

```
Pre-flight:
- [ ] 0.  Check Google auth (Section 0). STOP if expired.

Stage 1 (Featurization) — parallel strategy:
- [ ] 1.  Kick off BOTH small + large Stage 1 runs in parallel (separate terminals)
- [ ] 2.  Poll both for completion (background, check periodically).
          When `roboflow_job_status` reports a terminal-looking state (`RESOLVED`, `RAN`,
          `NESTED_FAILED`), ALWAYS confirm with `debug_roboflow_errors` to check
          `future_state`. `RAN` from the status tool does NOT mean "done" — the
          orchestrator may still be running downstream steps.
- [ ] 3a. When small run finishes (confirmed `FutureState.RESOLVED`): check training rows + errors
- [ ] 3a-msl. **Validate MSL labels** (Section 3, Query 4): decode `valid_mask` and `box`
              numpy arrays from BQ. For NVIDIA data, expect all-zero labels (no MSL coverage).
              Report the finding to the user — this is expected, not a bug.
- [ ] 3b. If small run PASSES: large run is already in flight — just wait for it
- [ ] 3c. If small run FAILS: diagnose top error, fix code, rerun BOTH (cancel stale large run)
- [ ] 4.  When large run finishes (confirmed `FutureState.RESOLVED`): check training rows + errors
- [ ] 4-msl. **Validate MSL labels** on large run (same decode check as 3a-msl)
- [ ] 5.  If rows > 0, labels look valid, and error rate is acceptable: Stage 1 DONE → Stage 2
- [ ] 6.  If rows == 0 or labels are all zeros/empty: analyze the top error code
- [ ] 7.  Pull 20-50 failing chunks from error table
- [ ] 8.  Reproduce locally with debug script (bazel run)
- [ ] 9.  Identify root cause, apply fix to source code
- [ ] 10. Rerun BOTH small + large in parallel to validate fix. If not → go to step 8.

Stage 2 (Map + Intent):
- [ ] 11. Extract stage1_job_id via `lumen_agent` MCP from the large run's Roboflow run ID
          (the job_id with random suffix, e.g. `..._b5zli`, NOT the BQ table name)
- [ ] 11b. Verify `nvidia_map_and_intent` config exists on current branch (Section 1b).
           If missing, STOP and tell user to cherry-pick Stage 2 code.
- [ ] 12. Derive experiment name from Stage 1 job_id (see Section 1b). Confirm job_id
           with user, then run Stage 2.
- [ ] 13. Poll for completion (Stage 2 can take several hours)
- [ ] 14. Check Stage 2 output tables for row counts
- [ ] 15. If errors: check Stage 2 error tables and diagnose
- [ ] 16. Extract Stage 2 job_id (with RF suffix) via `lumen_agent` from the Stage 2
           Roboflow run. Update `dataset_config.py` with the actual job_id.
           (See "Update dataset_config.py with Stage 2 data")
```

### Autonomy rules

- **Run autonomously** (no user confirmation needed): steps 0, 2-9 (code fixes,
  monitoring, BQ queries, error diagnosis)
- **NEVER launch without explicit user approval**: Any `bazel run` that submits
  a pipeline job (Stage 1, Stage 2, or any cloud job) costs real money ($10-$1000+).
  Always present the exact command and estimated cost, then wait for explicit
  "go ahead" / "launch it" / "yes" before executing. This includes steps 1, 10-12.
- **STOP and wait for user**: automated auth refresh failed AND manual fallback failed,
  or ambiguous diagnosis where multiple fixes are plausible

### Error handling during the workflow

| Error pattern | Action |
| --- | --- |
| `cruise-ladybug-agents` MCP not available | STOP. Tell user to enable it in Cursor Settings → MCP. |
| `Reauthentication`, `401`, `credentials`, `Permission denied` | Attempt automated refresh via `cruise-auth-refresh` skill. STOP only if automated + manual fallback both fail. |
| `bq` command fails with `Access Denied` on a table | Table may not exist yet (job still running). Recheck job status. |
| `bazel run` fails to build | Fix build errors, do NOT `bazel clean`. |
| Roboflow polling returns 404 | Job not registered yet. Wait 60s, retry. |
| `lumen_agent` returns no `job_id` | Run may still be in progress. Confirm `future_state` is `RESOLVED` first, then retry. |
| All chunks fail with same error | Systemic issue. Debug ONE chunk locally, fix, rerun. |
| Mixed error codes | Tackle the most frequent error first. |

---
