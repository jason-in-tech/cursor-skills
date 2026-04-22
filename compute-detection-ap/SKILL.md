---
name: compute-detection-ap
description: Compute detection AP (average precision) by range from BQ detection match tables for Olympus OL eval runs. Use when computing or verifying detection AP numbers for experiment reports/trackers, computing AP by range from BigQuery `visual_detection_metrics.detection_3d_*` tables, comparing detection AP across branches (B0/B1/B2/...), or when the user mentions detection AP, OL detection metrics, or AP by range.
---

# Compute Detection AP from BQ

Compute VEHICLE detection AP by range from BigQuery `visual_detection_metrics.detection_3d_*` tables for Olympus OL eval runs.

## Methodology

- **Class filter**: `COALESCE(label_model_class_name, detection_model_class_name) = 'CAR'`
- **TP criterion**: `iou_match_valid AND class_match_valid` (publish_introspection match logic: IoU-valid + same model class)
- **FP criterion**: `NOT iou_match_valid AND NOT gt_valid` (unmatched detection) OR `iou_match_valid AND NOT class_match_valid` (class mismatch)
- **FN criterion**: `NOT iou_match_valid AND NOT dt_valid` (missed GT)
- **Distance binning**: Euclidean distance from AV via `COALESCE(label_distance_from_av, detection_distance_from_av)`, bins: `[0, 25)`, `[25, 50)`, `[50, 100)`
- **Score binning**: 1000 bins (quantize `detection_confidence_score` to nearest 0.001)
- **Recall formula**: Standard: `cum_TP / (total_TP + total_FN)` where denominator is fixed per range bin
- **AP integration**: Trapezoidal: `sum(0.5 * (prec_i + prec_{i-1}) * (rec_i - rec_{i-1}))`
- **% change**: Always report **relative** % change: `(B2 - B0) / B0 * 100`

This differs from `publish_introspection` (which uses chassis-frame X binning, CAR/TRUCK/MOTORCYCLE filter, per-detection scoring). Euclidean distance is more appropriate for multi-camera range analysis; publish_introspection's X-axis is suited for forward-driving lead-vehicle analysis.

## BQ Table ID Resolution

OL eval BQ table IDs follow the pattern `detection_3d_{eval_run_id}` where `eval_run_id` is the W&B run ID of the OL evaluation (not the training run). For `train-eval-scene-enc` pipelines, the eval run ID differs from the training run ID.

To find the mapping:
1. Check `generate_pr_curves.py` in `scene_encoder/notebooks/` for hardcoded table IDs
2. Or search W&B for eval runs sharing the display name of the training run

## SQL Template

```sql
WITH classified AS (
    SELECT
        CASE
            WHEN COALESCE(label_distance_from_av, detection_distance_from_av) < 25 THEN '0-25'
            WHEN COALESCE(label_distance_from_av, detection_distance_from_av) < 50 THEN '25-50'
            WHEN COALESCE(label_distance_from_av, detection_distance_from_av) < 100 THEN '50-100'
        END AS range_bin,
        CASE
            WHEN iou_match_valid AND class_match_valid THEN 'TP'
            WHEN NOT iou_match_valid AND NOT gt_valid THEN 'FP'
            WHEN NOT iou_match_valid AND NOT dt_valid THEN 'FN'
            WHEN iou_match_valid AND NOT class_match_valid THEN 'FP'
            ELSE 'TP'
        END AS match_type,
        COALESCE(detection_confidence_score, 1.0) AS dt_score,
        gt_valid, dt_valid
    FROM `cruise-mlp-prod-13d0.visual_detection_metrics.detection_3d_{TABLE_ID}`
    WHERE COALESCE(label_model_class_name, detection_model_class_name) = 'CAR'
      AND COALESCE(label_distance_from_av, detection_distance_from_av) < 100
),
fn_totals AS (
    SELECT range_bin, COUNTIF(match_type = 'FN') AS total_fn
    FROM classified WHERE range_bin IS NOT NULL
    GROUP BY range_bin
),
score_bins AS (
    SELECT
        range_bin,
        CAST(FLOOR(dt_score * 1000) AS INT64) AS score_bin,
        COUNTIF(match_type = 'TP') AS tp_in_bin,
        COUNTIF(match_type = 'FP') AS fp_in_bin
    FROM classified
    WHERE range_bin IS NOT NULL AND match_type IN ('TP', 'FP')
    GROUP BY range_bin, score_bin
),
cum_counts AS (
    SELECT
        range_bin, score_bin,
        SUM(tp_in_bin) OVER (PARTITION BY range_bin ORDER BY score_bin DESC
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_tp,
        SUM(tp_in_bin + fp_in_bin) OVER (PARTITION BY range_bin ORDER BY score_bin DESC
                                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_det
    FROM score_bins
),
pr_points AS (
    SELECT
        c.range_bin, c.score_bin,
        SAFE_DIVIDE(c.cum_tp, c.cum_det) AS prec,
        SAFE_DIVIDE(c.cum_tp,
            (SELECT SUM(s2.tp_in_bin) FROM score_bins s2
             WHERE s2.range_bin = c.range_bin) + f.total_fn
        ) AS rec
    FROM cum_counts c
    JOIN fn_totals f ON f.range_bin = c.range_bin
),
with_lag AS (
    SELECT *,
        LAG(prec) OVER (PARTITION BY range_bin ORDER BY score_bin DESC) AS prev_prec,
        LAG(rec) OVER (PARTITION BY range_bin ORDER BY score_bin DESC) AS prev_rec
    FROM pr_points
)
SELECT
    range_bin,
    ROUND(SUM(0.5 * (prec + COALESCE(prev_prec, 1.0))
                   * (rec - COALESCE(prev_rec, 0.0))), 4) AS ap
FROM with_lag
GROUP BY range_bin
ORDER BY range_bin
```

## Python Wrapper

Use `google.cloud.bigquery.Client` to run the SQL template for each branch's table. Compare computed AP to tracker/report values. Report both absolute delta (AP units) and relative % change.

```python
from google.cloud import bigquery
client = bigquery.Client(project='cruise-mlp-prod-13d0')

TABLES = {
    'B0': 'detection_3d_<eval_run_id>',
    'B2': 'detection_3d_<eval_run_id>',
}

for branch, table in TABLES.items():
    query = SQL_TEMPLATE.replace('{TABLE_ID}', table.replace('detection_3d_', ''))
    results = {r.range_bin: r.ap for r in client.query(query).result()}
```

## Verification Checklist

1. Confirm BQ table IDs match eval run IDs (check `generate_pr_curves.py` or W&B)
2. Run the SQL for each branch
3. Compare computed AP to tracker values (expect max delta < 0.002 from rounding)
4. Verify B2 vs B0 gains using **relative** % change: `(ap_b2 - ap_b0) / ap_b0 * 100`
5. Cross-check that gains are consistent across methodology variants (the relative ranking should be robust even if absolute AP differs by methodology)

## Known Methodology Sensitivity

All reasonable methodology variants (VEHICLE vs CAR class, with/without class_match_valid, step vs trapezoidal AP, 200 vs 1000 score bins) produce identical relative branch rankings and B2 vs B0 gain directions. Absolute AP values differ by up to 0.008 depending on choices, but the relative-% change itself is stable to within 0.1 (absolute).
