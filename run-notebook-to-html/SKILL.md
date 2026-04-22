# Run Notebook to HTML

Execute Jupyter notebooks headlessly under Bazel, producing a self-contained HTML report
with all outputs and plots embedded inline.

## Architecture

The system uses two files per notebook:

1. **`execute_notebook_to_html.py`** -- generic driver script (lives alongside the notebook)
2. **`cruise_py_binary` BUILD target** -- wires the driver to a specific notebook with deps

The driver uses `nbconvert.ExecutePreprocessor` (same engine as `tools/jupyter/test.py`)
with a temporary kernel spec pointing to the bazel-provided Python, then exports HTML
via `nbconvert.HTMLExporter`.

## Setup for a new notebook

### 1. Copy the driver script

If the target notebook package does not already have `execute_notebook_to_html.py`, copy
it from an existing package. The canonical copy lives at:

```
cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/notebooks/execute_notebook_to_html.py
```

The script is generic -- no notebook-specific code.

### 2. Add a BUILD target

Add a `cruise_py_binary` in the notebook's BUILD file:

```python
cruise_py_binary(
    name = "execute_<notebook_name>",
    main = "execute_notebook_to_html.py",
    args = [
        "--notebook-path",
        "<bazel_package>/<notebook_name>.ipynb",
    ],
    data = ["<notebook_name>.ipynb"],
    deps = [
        ":<notebook_name>_lib",   # the _lib from jupyter_notebook() rule
        "//cruise/runfiles:py",
        pip_dep("nbconvert"),
        pip_dep("ipykernel"),
        pip_dep("jupyter-client"),
    ],
    tags = ["manual"],
)
```

Key points:
- `name` follows the convention `execute_<notebook_name>`.
- `data` must include the `.ipynb` file so it's available in runfiles.
- `deps` must include the notebook's `_lib` target (which pulls in all notebook deps)
  plus `nbconvert`, `ipykernel`, `jupyter-client`, and `cruise/runfiles:py`.
- `tags = ["manual"]` prevents CI from running it automatically.

### 3. Run it

```bash
bazel run --config=no-tty //<package>:execute_<notebook_name>
```

Override per-cell timeout or output directory:

```bash
bazel run --config=no-tty //<package>:execute_<notebook_name> -- --timeout 3600 --output-dir /tmp/nb_output
```

## Output

By default, files are written to `<workspace>/<package>/output/`:

| File | Description |
|------|-------------|
| `<notebook_name>.html` | Self-contained HTML with inline images |
| `<notebook_name>_executed.ipynb` | Executed notebook with all cell outputs |

## How the driver works

1. **Fix Jupyter template paths** -- nbconvert templates are in bazel runfiles at a
   non-standard location. The driver discovers them via `nbconvert-*.data` glob patterns
   and sets `JUPYTER_PATH`.

2. **Create a temporary kernel spec** -- the system `python3` kernel spec may be stale
   (pointing to a deleted venv). The driver creates a fresh `bazel_python` kernel spec
   in a temp directory with a hermetic wrapper that calls the bazel-provided Python.

3. **Inject `ARTIFACTS_DIR`** -- if the notebook has a config cell with `ARTIFACTS_DIR`
   and `CONFIG_CHOICE`, the driver inserts a cell after it that overrides `ARTIFACTS_DIR`
   to the output directory. This makes `save_artifacts()` calls write to the right place.

4. **Execute** -- `ExecutePreprocessor` runs all cells sequentially with the configured
   timeout.

5. **Export HTML** -- tries templates in order: lab → classic → basic.

6. **Save** -- writes both `.html` and `_executed.ipynb`.

## Troubleshooting

### Kernel fails with "No such file or directory" for a Python path

The system `~/.local/share/jupyter/kernels/python3/kernel.json` may point to a
non-existent venv. The driver works around this by creating its own kernel spec
(`bazel_python`). If you still see this error, check that `_create_kernel_spec()`
is being called and that `JUPYTER_DATA_DIR` is set before `ExecutePreprocessor`.

### nbconvert "No template sub-directory with name 'lab'"

Templates are in bazel runfiles under `nbconvert-X.Y.Z.data/data/share/jupyter/`.
The driver discovers them via `_fix_jupyter_paths()`. If this fails, ensure
`pip_dep("nbconvert")` is in the BUILD target's `deps`.

### GCS data not found (404)

The notebook's dataset config must point to a job_id that has parquet data stored in
GCS. Stage 2 (derived) pipelines that were run via `bazel run` directly (not through
Roboflow) may only create BQ tables without parquet storage. In that case, use the
original Stage 1 job_id or a Roboflow-submitted Stage 2 run.

### Cell execution timeout

Increase `--timeout` (default 1800s). For GPU-heavy notebooks on CPUs, execution can
be much slower.

### torchvision "Failed to load image Python extension"

Harmless warning when `libjpeg`/`libpng` are missing in the bazel sandbox. Does not
affect matplotlib-based plots.

## Publishing to Google Docs

After generating HTML and extracting images, the output can be published as a formatted
Google Doc using the `google-doc-publish` skill (`~/.cursor/skills/google-doc-publish/SKILL.md`).
The typical chain is:

1. Run notebook to HTML (this skill) -> produces `output/<name>.html` + extracted `.png` files
2. Write a markdown report (`write-technical-report` skill) referencing the images
3. Publish markdown + images to Google Doc (`google-doc-publish` skill)

The `google-doc-publish` skill handles base64 image embedding, table formatting, heading
hierarchy, internal linking, pageless mode, and Cruise domain sharing automatically.

---