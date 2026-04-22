---
name: sc3-protocol
description: Run end-to-end SC3 protocol evaluation on Galileo for a trained Olympus model checkpoint. Covers checkpoint lookup, robocompile, Galileo sc3-100/sc3-2000 triggering, result polling, and scorecard extraction. Use when the user wants to run SC3 protocol, evaluate a model on Galileo, trigger sc3-2000, run sc3-100, compile a model for simulation, or gather SC3 scorecard results.
---

# SC3 Protocol Evaluation

End-to-end workflow for evaluating an Olympus model checkpoint via SC3 simulation protocol on Galileo. Covers the full pipeline from checkpoint lookup through scorecard results.

## Prerequisites

- Pushed branch on `origin` (Galileo/Buildkite operate on remote branches)
- `BUILDKITE_API_TOKEN` in environment (check `~/.buildkite_token` or `echo $BUILDKITE_API_TOKEN`)
- Valid auth: `authcli status` should show Galileo and Roboflow as VALID

## Workflow Overview

```
1. Find checkpoint -> 2. Configure -> 3. Robocompile -> 4. Trigger Galileo -> 5. Gather results
```

## Step 1: Find the Model Checkpoint

For `train-eval-scene-enc` pipeline runs, checkpoints are under the `train_pytorch_lightning` subtask ID, NOT the orchestrator or `pytorch_trainer_substrate` ID.

```bash
RF_TOKEN=$(authcli app get roboflow -out stdout)
ORCH_ID="<orchestrator_run_id>"
TRAIN_ID=$(curl -s -H "Authorization: Bearer $RF_TOKEN" \
  "https://roboflow.robot.car/api/v1/runs/${ORCH_ID}/dag" | \
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
")
echo "train_pytorch_lightning ID: $TRAIN_ID"
```

Then list checkpoints:

```bash
GCP_TOKEN=$(gcloud auth application-default print-access-token)
curl -s -H "Authorization: Bearer $GCP_TOKEN" \
  "https://storage.googleapis.com/storage/v1/b/robotorch2-prod/o?prefix=scene_encoder/${TRAIN_ID}/checkpoints/&delimiter=/" | \
  python3 -c "import sys,json; [print(i['name']) for i in json.load(sys.stdin).get('items',[])]"
```

The final checkpoint follows: `gs://robotorch2-prod/scene_encoder/<TRAIN_ID>/checkpoints/final-checkpoint-epoch=<N>-step=<M>.ckpt`

## Step 2: Configure the Model

Create a fresh branch from `origin/develop` to avoid stale-code issues with robocompile:

```bash
git fetch origin develop
git checkout -b <branch-name> origin/develop
```

Update the deployment config with the checkpoint path:

```bash
# File: cruise/mla/ml_deployments/olympus_v1_4_config.json
{
    "config_name": "olympus_v1_4",
    "training_checkpoint": "gs://robotorch2-prod/scene_encoder/<TRAIN_ID>/checkpoints/final-checkpoint-epoch=<N>-step=<M>.ckpt"
}
```

Commit and push:

```bash
git add cruise/mla/ml_deployments/olympus_v1_4_config.json
git commit -m "Update olympus_v1_4 checkpoint for SC3 protocol"
git push -u origin <branch-name>
```

## Step 3: Robocompile (Model Export)

Robocompile converts the PyTorch checkpoint to TensorRT for simulation. Three components must be compiled for the split Olympus model:

```bash
# All 3 can run in parallel -- trigger them back-to-back
bazel run --config=no-tty cruise/mla/ml_compiler/robocomp/buildkite:trigger_buildkite_job -- \
  --auto_commit_models_bzl //cruise/sc3/models/olympus:olympus_v1_4_camera_encoder_a

bazel run --config=no-tty cruise/mla/ml_compiler/robocomp/buildkite:trigger_buildkite_job -- \
  --auto_commit_models_bzl //cruise/sc3/models/olympus:olympus_v1_4_camera_encoder_b

bazel run --config=no-tty cruise/mla/ml_compiler/robocomp/buildkite:trigger_buildkite_job -- \
  --auto_commit_models_bzl //cruise/sc3/models/olympus:olympus_v1_4_fusion_decoder
```

Each job prints a Buildkite build number. Runs on Buildkite CI agents (T4 GPUs), ~40 min per component. No GPU training cost.

### Monitoring Robocompile

Poll Buildkite API for build status:

```bash
BUILDKITE_TOKEN="${BUILDKITE_API_TOKEN}"
BUILD_NUM="<from trigger output>"
curl -s -H "Authorization: Bearer ${BUILDKITE_TOKEN}" \
  "https://api.buildkite.com/v2/organizations/cruise/pipelines/cruise-cruise-robocompilerasyncexport/builds/${BUILD_NUM}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'State: {d[\"state\"]}, Created: {d[\"created_at\"]}')"
```

### Verify Auto-Commits

After all 3 builds pass, `--auto_commit_models_bzl` pushes SHA updates to your branch:

```bash
git fetch origin <branch-name>
git log --oneline origin/<branch-name> -5
```

Expect 3 commits like "Update packaged model sha256 in models.bzl" on top of your config commit. Pull them before triggering Galileo:

```bash
git pull origin <branch-name>
```

## Step 4: Trigger Galileo SC3 Protocol

**CRITICAL**: Use the V2 trigger CLI (`//cruise/galileo:trigger_tests`). The V1 CLI
(`//cruise/galileo/protocols:trigger`) is **deprecated and deactivated** as of April 2026.
V1 runs will lack protocol analysis data (no severity scores, no Validation Scorecard).

Two protocol options:
- **sc3-100**: ~100 scenarios, quick sanity check (~1 hour)
- **sc3-2000**: ~1881 scenarios, full scorecard for stakeholder-ready results (2-3 hours)

```bash
bazel run --config=no-tty //cruise/galileo:trigger_tests -- \
  --protocol "sc3-2000" \
  --revision <HEAD_COMMIT_SHA_OF_FEATURE_BRANCH> \
  --branch <feature-branch-name> \
  --base-branch develop \
  --base-commit <LATEST_DEVELOP_COMMIT_SHA> \
  --use-authcli
```

**Required flags:**
- `--revision`: HEAD commit SHA of the feature branch (must be pushed to origin)
- `--branch`: The remote branch name (e.g., `jl/nvidia-sc3-protocol`)
- `--base-branch`: Always `develop`
- `--base-commit`: Latest commit SHA on `origin/develop` at time of trigger
- `--use-authcli`: Use authcli for Galileo API authentication

Output includes the Test Request Group (TRG) ID:

```
Triggered protocol sc3-2000 as a test request group with ID: <uuid>
https://galileo.robot.car/test-request-groups/<uuid>
```

### Optional Flags

- `--category-filter "Lane Keeping"` -- run a single category
- `--dry-run` -- preview without triggering

## Step 5: Gather Results

### Poll for Completion

V2 protocol runs use Test Request Group (TRG) IDs. Poll via the Galileo API:

```bash
TOKEN=$(authcli app get "Galileo API" -token-algorithm RS256 -out stdout 2>/dev/null)
TRG_ID="<uuid>"
curl -s -H "Authorization: Bearer $TOKEN" -H "Galileo-ClientApp: cursor-agent" \
  "https://galileo.robot.car/api/v1/test-request-groups/${TRG_ID}" | \
  python3 -c "
import sys,json
d=json.load(sys.stdin)
trs = d.get('testRequests',[])
statuses = {}
for tr in trs:
    s = tr.get('status','unknown')
    statuses[s] = statuses.get(s,0) + 1
print(f'Status: {d.get(\"status\",\"?\")}')
print(f'Test requests: {len(trs)} total, breakdown: {statuses}')
for ao in d.get('analysisOutputs',[]):
    for o in ao.get('outputs',[]):
        print(f'Report: {o[\"label\"]}: {o[\"url\"]}')
"
```

Poll every 5-10 minutes until `status: completed` and performance reports appear.

**Note**: Despite being V2 protocol runs, the API path is `/api/v1/test-request-groups/<TRG_ID>`.
The UI URL is `https://galileo.robot.car/test-request-groups/<TRG_ID>`.

### Extract Results via BigQuery (preferred)

BigQuery is the preferred method -- one query returns all test requests for a PEID, and the same tables support richer per-scenario metrics. Run queries against project `cruise-mlp-prod-13d0` with `location=US`.

**Single PEID pass/fail/error breakdown:**

```bash
ADC_TOKEN=$(gcloud auth application-default print-access-token)
PEID="<uuid>"
curl -s -X POST \
  -H "Authorization: Bearer $ADC_TOKEN" \
  -H "Content-Type: application/json" \
  "https://bigquery.googleapis.com/bigquery/v2/projects/cruise-mlp-prod-13d0/queries" \
  -d "{
    \"query\": \"SELECT request.display_name as name, request.execution_count.total_test_executions as total, request.execution_count.passed_test_executions as passed, request.execution_count.failed_test_executions as failed, request.execution_count.errored_test_executions as errored FROM \\\`cruise-galileo-prod-b714.operational_data.decorated_test_requests\\\` WHERE request.client_trace_id = '${PEID}' AND request.git_branch != 'develop' ORDER BY request.display_name\",
    \"useLegacySql\": false,
    \"maxResults\": 50,
    \"location\": \"US\"
  }" | python3 -c "
import sys,json
d=json.load(sys.stdin)
total_all = passed_all = 0
for row in d.get('rows',[]):
    v = [c['v'] for c in row['f']]
    name, total, passed, failed, errored = v[0], int(v[1]), int(v[2]), int(v[3]), int(v[4])
    print(f'{name:65s} {passed:>4d}/{total:<4d} (err={errored})')
    total_all += total; passed_all += passed
print(f'\nTotal: {passed_all}/{total_all} ({passed_all/total_all*100:.1f}%)')
"
```

**Compare two PEIDs side by side (B0 vs B2 pattern):**

```bash
ADC_TOKEN=$(gcloud auth application-default print-access-token)
PEID_BASE="<base_peid>"
PEID_FEAT="<feature_peid>"
curl -s -X POST \
  -H "Authorization: Bearer $ADC_TOKEN" \
  -H "Content-Type: application/json" \
  "https://bigquery.googleapis.com/bigquery/v2/projects/cruise-mlp-prod-13d0/queries" \
  -d "{
    \"query\": \"WITH b AS (SELECT request.display_name as name, request.execution_count.total_test_executions as total, request.execution_count.passed_test_executions as passed FROM \\\`cruise-galileo-prod-b714.operational_data.decorated_test_requests\\\` WHERE request.client_trace_id = '${PEID_BASE}' AND request.git_branch != 'develop'), f AS (SELECT request.display_name as name, request.execution_count.total_test_executions as total, request.execution_count.passed_test_executions as passed FROM \\\`cruise-galileo-prod-b714.operational_data.decorated_test_requests\\\` WHERE request.client_trace_id = '${PEID_FEAT}' AND request.git_branch != 'develop') SELECT b.name, b.total as b_total, b.passed as b_pass, f.total as f_total, f.passed as f_pass, (f.passed - b.passed) as delta FROM b JOIN f ON b.name = f.name ORDER BY b.name\",
    \"useLegacySql\": false,
    \"maxResults\": 50,
    \"location\": \"US\"
  }" | python3 -c "
import sys,json
d=json.load(sys.stdin)
bt = bp = ft = fp = 0
for row in d.get('rows',[]):
    v = [c['v'] for c in row['f']]
    name = v[0]; b_t, b_p, f_t, f_p, delta = int(v[1]), int(v[2]), int(v[3]), int(v[4]), int(v[5])
    marker = f'+{delta}' if delta > 0 else str(delta)
    print(f'{name:65s} {b_p:>4d}/{b_t:<4d} {f_p:>4d}/{f_t:<4d} {marker:>5s}')
    bt += b_t; bp += b_p; ft += f_t; fp += f_p
print(f'\n{\"TOTAL\":65s} {bp:>4d}/{bt:<4d} {fp:>4d}/{ft:<4d} {fp-bp:>+4d}')
print(f'Base:    {bp}/{bt} ({bp/bt*100:.1f}%)')
print(f'Feature: {fp}/{ft} ({fp/ft*100:.1f}%)')
"
```

**Key BigQuery tables:**

| Table | Contents |
|-------|----------|
| `cruise-galileo-prod-b714.operational_data.decorated_test_requests` | Per-test-request metadata and pass/fail/error counts |
| `cruise-galileo-prod-b714.operational_data.decorated_test_executions` | Per-scenario execution data: exit codes, **300 per-execution scores** (TTC, collision, hard brake, swerve, controllability, distance traveled, sim safety proxy, etc.) |
| `cruise-galileo-prod-b714.protocol_analysis.protocol_analysis_scenario_results_v4` | Protocol analysis: burndown_solved, interpretation (regression/progression), input_metrics (14 aggregate driving metrics) |

The `decorated_test_requests` table uses `request.client_trace_id` for the PEID and `request.git_branch != 'develop'` to filter for feature (not base) test requests. Execution counts are in `request.execution_count.*`.

### Extract Safety & Driving Metrics (per-execution scores)

The `decorated_test_executions.execution.scores` array contains ~300 metrics per scenario, including all the safety/comfort/driving metrics that the Protocol Browser Validation Scorecard computes. This is the **primary source** for safety analysis.

**Key safety metrics available:**

| Score Name | What it measures |
|------------|-----------------|
| `sc_3_av_collision_scene__has_collision` | 1 if collision occurred |
| `sc_3_av_collision_scene__min_ttc` | Min time-to-collision (seconds) |
| `sc_3_av_controllability_hard_braking_scene__event_count` | Hard brake events |
| `sc_3_av_controllability_swerving_scene__event_count` | Swerve events |
| `sc_3_av_distance_traveled_total_distance` | Total distance (meters) |
| `sc_3_av_npc_interaction__min_ttc` | Min TTC in NPC interactions |
| `sc_3_av_controllability_aggregator__controllability_score` | Composite controllability (0-1) |
| `ahb_sim_safety_proxy_likelihood_score` | AHB sim safety proxy (0-1) |
| `sc_3_av_lane_excursion_scene__event_count` | Lane excursion events |
| `sc_3_av_uncontrollable_scene__event_count` | Uncontrollable events |

**Aggregate safety metrics for a PEID (feature arm):**

```bash
ADC_TOKEN=$(gcloud auth application-default print-access-token)
PEID="<uuid>"
curl -s -X POST \
  -H "Authorization: Bearer $ADC_TOKEN" \
  -H "Content-Type: application/json" \
  "https://bigquery.googleapis.com/bigquery/v2/projects/cruise-mlp-prod-13d0/queries" \
  -d "{
    \"query\": \"SELECT s.name, AVG(s.value) as avg_val, SUM(s.value) as sum_val, COUNT(*) as cnt, COUNTIF(s.value > 0) as nonzero FROM \\\`cruise-galileo-prod-b714.operational_data.decorated_test_executions\\\` e CROSS JOIN UNNEST(e.execution.scores) AS s JOIN \\\`cruise-galileo-prod-b714.operational_data.decorated_test_requests\\\` r ON e.test_request_id = r.test_request_id WHERE r.request.client_trace_id = '${PEID}' AND r.request.git_branch != 'develop' AND s.name IN ('sc_3_av_collision_scene__has_collision','sc_3_av_controllability_hard_braking_scene__event_count','sc_3_av_controllability_swerving_scene__event_count','sc_3_av_distance_traveled_total_distance','sc_3_av_npc_interaction__min_ttc','sc_3_av_controllability_aggregator__controllability_score','ahb_sim_safety_proxy_likelihood_score','sc_3_av_lane_excursion_scene__event_count','sc_3_av_uncontrollable_scene__event_count') GROUP BY s.name ORDER BY s.name\",
    \"useLegacySql\": false,
    \"maxResults\": 20,
    \"location\": \"US\",
    \"timeoutMs\": 120000
  }"
```

Compute derived metrics: `mi/event = total_distance_mi / event_count`, `collision_rate = collision_scenarios / total_scored`. Use `git_branch = 'develop'` filter for the base (develop) arm.

### Fallback: Galileo V2 API

If BigQuery access is unavailable, loop over the Galileo V2 API per test request:

```bash
TOKEN=$(authcli app get "Galileo API" -out stdout 2>/dev/null)
curl -s -H "Authorization: Bearer $TOKEN" -H "Galileo-ClientApp: cursor-agent" \
  "https://galileo.robot.car/api/v2/test-requests/<test_request_id>"
```

Returns `totalTestExecutions`, `passedTestExecutions`, `failedTestExecutions`, `erroredTestExecutions`. Requires looping over all 25 feature test request IDs (get them from the V1 PEID endpoint). Both sources return identical data.

### SC3-2000 Category Mapping

| Category | Test Request Name Prefixes |
|----------|-----------|
| Lane Keeping | `SC3 Lane Keep`, `SC3 - Lane Keep - MR5K` |
| Lane Changes | `SC3 - Merges`, `SC3 - Lane Changes Routing` |
| Lane Obstructions | `SC3 Debris` |
| NPC Actions | `SC3 - NPC Actions` |
| VRU | `SC3 Non Ped VRU` |
| Bridges | `SC3 - Bridges` |
| Tunnels | `SC3 - Tunnels` |
| Ramps | `SC3 - Ramps` |
| Vehicle Speed | `SC3 - Vehicle Speed` |
| Large/Unusual Vehicles | `SC3 - Large/Unusual Vehicles` |
| Closed Course | `SC3 - Closed Course` |
| Stack Smoke | `SC3 - Stack Smoke` |

### Streamlit Visualizations

**Protocol Browser** -- scorecard and charts for a single PEID (compares its internal base=develop vs feature=your-branch):

```
https://streamlit.robot.car/protocol-browser/?ProtocolBrowserHome_peids=<PEID>&key_tabs=Validation+Scorecard
```

Shows: SC3 All Behavior Performance Summary, LRR metrics, Lane Keep AV-AHB Zone Analysis, score distributions, exit codes.

**Protocol Diff** -- compare two models side by side. Set `base_execution_to_use=Feature` so both sides use their feature test requests (otherwise the "Base" PEID defaults to its develop side):

```
https://streamlit.robot.car/protocol-diff/?base_peid=<PEID_1>&feature_peid=<PEID_2>&base_execution_to_use=Feature
```

Shows: metric regressions/improvements, CDFs, score correlations, permutation analysis, error drilldowns.

### Performance Report

The Cypher-generated performance report (linked in `analysisOutputs`) is an auto-generated notebook artifact. The Streamlit apps above are the primary interactive tools for exploring and comparing results.

## Running Multiple Models in Parallel

To compare models (e.g., baseline vs feature branch):

1. Create separate branches from `origin/develop` for each model
2. Configure each with its respective checkpoint
3. Run robocompile for all models in parallel (6 builds for 2 models)
4. Trigger Galileo for each branch once robocompile completes
5. Poll all PEIDs concurrently

Reusing the same worktree across branches is fine -- just `git checkout -b <new-branch> origin/develop` between models.

## Common Issues

- **Stale code / robocompile failure**: Always branch from fresh `origin/develop`. Old branches may have incompatible model definitions.
- **`BUILDKITE_API_TOKEN` missing**: Save to `~/.buildkite_token` and add `export BUILDKITE_API_TOKEN=$(cat ~/.buildkite_token 2>/dev/null)` to `~/.bashrc`.
- **V1 protocol runs lack analysis data**: If you accidentally triggered with the V1 CLI (`//cruise/galileo/protocols:trigger`), the run will complete but Protocol Browser Validation Scorecard will show "no Protocol Analysis results" and severity scores will be missing. Re-trigger with the V2 CLI.
- **Auth expired during polling**: Re-run `authcli refresh` and retry. Galileo tokens expire periodically during long polls.
- **SC3 Debris Nominal 0/27**: All 27 scenarios error for both base and feature in current protocol -- this is a known scenario-level issue, not a model problem.

## Key Files

- Deployment config: `cruise/mla/ml_deployments/olympus_v1_4_config.json`
- Robocompile trigger: `cruise/mla/ml_compiler/robocomp/buildkite/trigger_buildkite_job.py`
- Split model targets: `cruise/sc3/models/olympus/build_configs/split_models.bzl`
- Model SHAs: `cruise/sc3/models/olympus/models.bzl`
- Galileo V2 trigger: `cruise/galileo/trigger_tests.py`
- Galileo V1 trigger (deprecated): `cruise/galileo/protocols/trigger.py`
- SC3 protocol definition: `cruise/galileo/protocols/v2/sc3/`
