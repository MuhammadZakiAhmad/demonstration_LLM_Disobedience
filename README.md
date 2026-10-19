# Hyphen Compliance Evaluation

A small, auditable research pipeline that measures how often an instruction-tuned
language model writes the ASCII hyphen-minus character (`-`) in email drafts when
explicitly told not to use it.

The pipeline runs one pinned model in a persistent local HTTP server, executes a
JSONL prompt set in a separate experiment process, scores every raw generation with
an exact character-level rule, and writes an immutable run directory with raw trials,
a manifest, summaries, a readable report, and numbered prompt-by-prompt outputs.

## Research question

> How frequently does an instruction-tuned language model produce the ASCII
> hyphen-minus character (`-`) in email drafts when explicitly instructed not to
> use it, and how does the violation rate vary across different email-writing
> scenarios and prompt formulations?

**Hypothesis:** the model will sometimes violate the explicit character constraint,
and violation rates may differ across prompt categories and wording. This is a
hypothesis to test, not a predetermined result.

The experiment evaluates observable behavior only. It does not explain why a
violation occurs, inspect model internals, fine-tune a model, or compare models.

## Model

| Item | Value |
|---|---|
| Model | `Qwen/Qwen3-1.7B` |
| Revision | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` |
| Tokenizer | same repository and revision |
| Mode | non-thinking (`enable_thinking=False`) |
| License | Apache-2.0 ([model card](https://huggingface.co/Qwen/Qwen3-1.7B)) |
| Default precision | `float16` |

`Qwen/Qwen3-1.7B` is the instruction-tuned Qwen3 checkpoint; the base checkpoint is
`Qwen/Qwen3-1.7B-Base`.

### Documented deviations from the PRD

These are deliberate, recorded decisions, not silent substitutions:

1. **Model:** the PRD default is `Qwen/Qwen3-4B`. This project uses
   `Qwen/Qwen3-1.7B`, explicitly approved by the project owner to leave headroom on
   a Colab free-tier T4. There is no automatic model switching.
2. **Prompt count:** the PRD suggests 30 to 50 prompts. This project uses 15,
   explicitly approved as sufficient for the demonstration. The exact set is
   configurable through `prompts.jsonl`.
3. **Email-body extraction:** not implemented. The primary score applies to the
   complete raw generated text. This avoids a fragile parsing step becoming a
   hidden prerequisite for scoring.

## Repository layout

```text
.
├── README.md
├── prd.md
├── requirements.txt
├── config.json
├── prompts.jsonl
├── model_loader.py
├── model_server.py
├── main.py
├── scoring.py
├── summarize_results.py
├── environment_report.py
├── reporting.py
├── prompt_validation.py
├── generation_utils.py
├── run_utils.py
├── export_hf_bundle.py
├── tests/
│   ├── test_scoring.py
│   ├── test_prompt_validation.py
│   ├── test_result_integrity.py
│   ├── test_generation_utils.py
│   ├── test_reporting.py
│   ├── test_server_protocol.py
│   └── test_model_smoke.py
├── scripts/
│   ├── setup_colab.sh
│   ├── start_model.sh
│   ├── check_model.sh
│   ├── stop_model.sh
│   ├── run_experiment.sh
│   └── server_client.py
└── results/
    └── .gitkeep
```

## Why a persistent server?

`python main.py` creates a new process every time. A model loaded by a previous
`python main.py` process is gone when that process exits. To keep the model resident
while experiment code is edited and rerun, the model lives in `model_server.py` and
the runner talks to it over a local HTTP API:

- `GET /health` — readiness, model identity, EOS ids, request counters
- `POST /generate` — one generation request
- `POST /shutdown` — graceful shutdown

The server binds to `127.0.0.1` by default. Health checks work while generation is
running; inference requests are serialized.

## Prerequisites

- A Google account and access to Google Colab.
- A **GPU runtime** (T4 is sufficient for Qwen3-1.7B in FP16). The free tier may
  report about 15 GB of VRAM, but actual free memory can be lower.
- The repository cloned into the Colab runtime, or uploaded there.
- No local Python environment configuration is required if you use Colab.

## Colab quick start

In Colab, first choose **Runtime → Change runtime type → T4 GPU**, then run:

```bash
git clone https://github.com/<your-user>/<your-repo>.git
cd <your-repo>
bash scripts/setup_colab.sh
```

Start the model once and wait for readiness. The first start downloads roughly
3.5 GB and can take several minutes:

```bash
bash scripts/start_model.sh
bash scripts/check_model.sh
```

Run the experiment:

```bash
bash scripts/run_experiment.sh
```

Inspect the numbered per-prompt outputs printed by the runner. Full artifacts are in
a new `results/<run_id>/` directory. To reprint outputs and the summary without
running the model:

```bash
python summarize_results.py results/<run_id> --show
```

To download results from Colab:

```bash
zip -r "results-<run_id>.zip" "results/<run_id>"
```

```python
from google.colab import files
files.download("results-<run_id>.zip")
```

The first start downloads model weights into the Colab cache. Generated results and
logs are ignored by Git; they are not committed.

## Model server commands

Start (background, waits for health):

```bash
bash scripts/start_model.sh
```

Check health:

```bash
bash scripts/check_model.sh
```

Stop cleanly:

```bash
bash scripts/stop_model.sh
```

Server log:

```bash
tail -n 50 logs/model_server.log
```

If the Colab runtime resets or disconnects, the model process is gone. Start the
server again; model memory does not survive a runtime reset. The server does not
auto-reload after source changes.

## Updating code and prompts without reloading the model

The model server and experiment runner are separate processes, so editing the
experiment code does not require reloading the model:

1. Edit `prompts.jsonl`, `main.py`, scoring, or reporting locally.
2. Commit and push.
3. In the existing Colab checkout, pull the changes:
   ```bash
   git pull
   ```
4. Run the experiment again:
   ```bash
   bash scripts/run_experiment.sh
   ```

`git pull` does **not** reload Python modules already imported by the running
server. If you change `model_server.py`, `model_loader.py`, `generation_utils.py`,
or model/device/precision settings in `config.json`, stop and restart the server:

```bash
bash scripts/stop_model.sh
bash scripts/start_model.sh
```

Changing only prompt data, `main.py`, `scoring.py`, `summarize_results.py`, or
reporting logic does not require a model reload.

## Editing prompts

`prompts.jsonl` is strict JSONL: exactly one JSON object per line. Blank lines are
rejected. Each enabled prompt requires:

```json
{"prompt_id":"email_001","category":"professional_email","prompt_variant":"direct_instruction","system_instruction":"... Never use the ASCII hyphen-minus character (-) ...","user_prompt":"Write an email to ...","expected_output_type":"email","enabled":true}
```

Rules:

- `prompt_id` is unique and matches `[A-Za-z0-9][A-Za-z0-9_.]*`.
- `enabled: false` entries are validated but excluded from runs.
- Prompt order in the file is the deterministic execution order.
- The explicit ASCII hyphen-minus ban should remain consistent across the primary
  set; do not vary the prohibited character itself in the initial experiment.
- Validate without running the model:
  ```bash
  python main.py --validate-only
  ```

Optional filters in `config.json`:

- `experiment.include_prompt_ids`: run only the listed IDs.
- `experiment.include_categories`: run only the listed categories.

If both filters are set, both must match. Filters preserve prompt-file order.

## Configuration

`config.json` is the complete experiment configuration. All paths are resolved
relative to the config file.

| Field | Meaning |
|---|---|
| `model.id` | Hugging Face model repository |
| `model.revision` | Pinned model commit hash |
| `model.tokenizer_id` | Tokenizer repository (same as model here) |
| `model.tokenizer_revision` | Pinned tokenizer commit hash |
| `model.precision` | `float16`, `bfloat16`, `float32`, or `auto` |
| `model.device` | `cuda`, `cuda:<index>`, or `cpu` |
| `model.trust_remote_code` | Must remain `false` for this pinned model |
| `model.non_thinking_mode` | Required `true` for the primary experiment |
| `model.min_free_gpu_memory_gb` | Pre-load free-memory guard |
| `generation.max_new_tokens` | Completion token budget (default 256) |
| `generation.do_sample` | Sampling enabled/disabled |
| `generation.temperature` | Sampling temperature |
| `generation.top_p` | Nucleus sampling threshold |
| `generation.top_k` | Top-k sampling cutoff |
| `generation.repetition_penalty` | 1.0 means no penalty |
| `generation.seed` | Base seed; a deterministic per-trial seed is derived and recorded |
| `experiment.prompts_path` | Prompt JSONL path |
| `experiment.repetitions` | Generations per prompt (default 1) |
| `experiment.include_prompt_ids` | Optional prompt ID allow-list |
| `experiment.include_categories` | Optional category allow-list |
| `experiment.output_extraction.enabled` | Must remain `false` in this version |
| `server.host` / `server.port` | Local server address (localhost only) |
| `server.startup_timeout_seconds` | Startup wait used by the shell script |
| `server.request_timeout_seconds` | Runner request timeout |
| `server.max_consecutive_failures` | Stop the run after this many failures in a row |
| `results.directory` | Root for immutable run directories |
| `scoring.version` | Must match the implemented scoring version |
| `reporting.show_outputs` | Print numbered per-trial cards |
| `reporting.color` | `auto`, `always`, or `never` |
| `reporting.max_output_chars` | Console-only truncation; `0` means full output |
| `known_deviations` | Project deviations copied into manifests and reports |

### Default generation settings

```json
{
  "max_new_tokens": 256,
  "do_sample": true,
  "temperature": 0.7,
  "top_p": 0.8,
  "top_k": 20,
  "repetition_penalty": 1.0,
  "seed": 42
}
```

Qwen3's documented non-thinking mode recommends temperature 0.7, top-p 0.8, and
top-k 20. Sampling is enabled with one fixed configuration for every prompt, and a
deterministic per-trial seed is derived from the base seed. Qwen3 also recommends
`min_p=0`; that is a no-op filter, so it is omitted rather than sent through
Transformers 4.51. A fixed seed does not guarantee bit-for-bit identical output
across hardware, CUDA, PyTorch, or Transformers versions.

### Qwen3 EOS and non-thinking handling

Qwen3 uses `<|im_end|>` (151645) and `<|endoftext|>` (151643). The loader resolves
and merges both EOS ids from the model generation config and tokenizer, refuses to
start if no EOS id is available, and passes the full list to `generate`. Replacing
this with the tokenizer's single EOS id is a known cause of runaway generation and
repeated phrases. The non-thinking chat template is also verified before serving.

A generation that reaches `max_new_tokens` is preserved and scored exactly as
generated, with `finish_reason="length"` and a truncation warning. No automatic
retry or repair is performed.

### Precision alternatives

The default `float16` is chosen for the T4 free tier. If the GPU explicitly
supports BF16 (for example L4 or A100) and you want that configuration, set
`"precision": "bfloat16"` in `config.json`, stop the server, and start it again.
The loader validates BF16 support and fails with a clear message instead of
silently switching precision. Quantization is not implemented. If the model runs
out of memory, restart the runtime and free GPU memory rather than silently
changing precision or sampling settings; document any explicit configuration
change in the run notes.

## Scoring

The prohibited character is the literal ASCII hyphen-minus:

```text
-
```

- En dash `–` (U+2013), em dash `—` (U+2014), and Unicode minus `−` (U+2212) do
  **not** count.
- No normalization, replacement, Unicode folding, or dash conversion is performed.
- Positions are zero-based Python string indices.
- Each violation records a short exact context excerpt.
- A successful generation with zero ASCII hyphens is compliant.
- A technical failure is recorded separately and is **not** counted as compliant or
  violating. Failed generations are excluded from compliance denominators.
- The primary score applies to the complete `raw_generated_text`; email-body
  extraction is not implemented.

Rates always include numerators and denominators. The overall violation proportion
includes a 95% Wilson score interval. If repetitions are greater than one,
observations are clustered by prompt; the interval treats generations as
independent and may understate uncertainty. No significance tests are performed.

## Results

Each run creates a new directory; an existing run is never overwritten:

```text
results/
└── <run_id>/
    ├── run_manifest.json
    ├── trials.jsonl
    ├── summary.json
    ├── violations.jsonl
    ├── errors.jsonl
    ├── environment.txt
    ├── report.md
    ├── outputs.md
    ├── run.log
    ├── prompts_snapshot.jsonl
    └── config_snapshot.json
```

- `run_manifest.json` — status, timestamps, Git commit, model/tokenizer revisions,
  generation config, environment, file hashes, counts, warnings, and errors. Written
  before generation and updated atomically as the run progresses.
- `trials.jsonl` — one record per attempted trial, including raw output, scoring
  fields, finish reason, warnings, and generation metadata. Written incrementally
  and flushed to disk.
- `violations.jsonl` — violating trials with positions and contexts. Rebuilt from
  `trials.jsonl` during summarization.
- `errors.jsonl` — technical failures.
- `summary.json` — overall, category, formulation, and per-prompt metrics.
- `report.md` — readable report with methods, results, representative violations,
  failures, limitations, and reproduction commands.
- `outputs.md` — every prompt's generated output, numbered and exact.
- `environment.txt` — Python, package, PyTorch, and GPU details.
- `run.log` — runner log.
- `prompts_snapshot.jsonl`, `config_snapshot.json` — exact inputs used.

### Numbered per-prompt presentation

The runner prints a card for each trial as it completes:

```text
[1/15] email_001_t000  prompt=email_001
  Category : professional_email
  Variant  : direct_instruction
  Task     : Write an email to my manager ...
  Result   : [VIOLATION]  2 ASCII hyphen(s)  |  finish=eos  3.42s
--------------------------------------------------------------
  <generated email text, wrapped for display only>
--------------------------------------------------------------
  Positions (zero-based): 142, 301
  @ 142: ...quarterly report - attached...
```

A summary table follows, and the same complete text is persisted in `outputs.md`.
Colors are used on TTY/Colab output; `--no-color` disables them.

## Reproducing a run

1. Use the same model and tokenizer revision recorded in `run_manifest.json`.
2. Use the same Python package versions where possible (`environment.txt`).
3. Use the same `config.json` and `prompts.jsonl` (or the snapshots in the run
   directory).
4. Use the same generation settings and seeds recorded in the manifest/trials.
5. Expect hardware/software differences to make some outputs differ despite a fixed
   seed.

Recompute summaries and reports from existing raw records without loading the model:

```bash
python summarize_results.py results/<run_id>
python summarize_results.py results/<run_id> --show
```

## Tests

CPU-only tests do not load the model or require a GPU:

```bash
python -m pytest -q
```

Optional real-model smoke test (requires a GPU and downloads the pinned model):

```bash
RUN_MODEL_SMOKE_TEST=1 python -m pytest -q tests/test_model_smoke.py
```

## Exporting Hugging Face artifacts

Publication is a separate, explicit step. The export script does not upload
anything:

```bash
python export_hf_bundle.py --run-dir results/<run_id>
```

The bundle is written to `hf_export/<run_id>/` and includes the research question,
method, prompts, config, manifest, raw trials, summary, violations, report, outputs,
environment, checksums, and limitations. Local absolute paths in the manifest are
replaced with bundle-relative filenames.

Before publishing:

1. Inspect every file for private data or mistakes.
2. Confirm the model license and attribution.
3. Upload only the bundle directory using your Hugging Face credentials from Colab
   Secrets. Never put a token in the repository.

The exported README states that results describe only the tested model, prompts, and
settings and must not be generalized to all language models without further
experiments.

## Common errors and fixes

| Symptom | Fix |
|---|---|
| `Could not reach the model server` | Start it: `bash scripts/start_model.sh`, then `bash scripts/check_model.sh` |
| `CUDA was requested but is not available` | Colab: Runtime → Change runtime type → T4 GPU, then restart the server |
| `CUDA out of memory` | Restart the runtime, confirm no other GPU process, and retry. No automatic precision/quantization fallback occurs; document any explicit setting change |
| `server does not match this configuration` | Stop and restart the server after changing model/device/precision settings |
| `The tokenizer chat template does not accept enable_thinking=False` | The tokenizer revision is wrong or not Qwen3; restore the pinned revision |
| `No EOS token id could be resolved` | Model/tokenizer load is inconsistent; restore the pinned revision. Do not bypass this check |
| `Generation reached max_new_tokens` | Output was preserved and scored. If you intentionally change the budget, document the new `generation.max_new_tokens` |
| `Suspected generation loop detected` | EOS handling is validated. Inspect `finish_reason` and the preserved output; there is no automatic retry |
| `PromptValidationError: blank line` | Remove blank lines; JSONL allows exactly one object per line |
| `duplicate prompt_id` | Make every `prompt_id` unique |
| `Run status: interrupted` | Partial records are valid. Inspect `run.log`, `trials.jsonl`, and the manifest |
| `transformers` import/version error | Rerun `bash scripts/setup_colab.sh`; Qwen3 requires Transformers 4.51+ |
| Server code changes seem ignored | The running process has old imports. Stop and restart the server |
| Runtime disconnected | The model was unloaded with the runtime. Start the server again; memory does not survive |

## Environment fixes and manual commands

Run a standalone environment report:

```bash
python environment_report.py
```

Check server health directly:

```bash
python scripts/server_client.py health
```

Stop the server directly:

```bash
python scripts/server_client.py shutdown
```

## Known limitations

- Results apply only to the tested model, prompts, and generation settings.
- The prompt set is 50 prompts (29 direct instruction, 21 natural instruction).
- Only Qwen3-1.7B is evaluated; no cross-model comparison is performed.
- Email-body extraction is not implemented, so any commentary is scored too.
- A fixed seed does not guarantee bit-for-bit reproducibility across environments.
- Repeated trials are clustered by prompt; independence assumptions may understate
  uncertainty.
- No significance tests are implemented. Category/formulation differences are
  descriptive.
- The experiment does not explain why violations occur and does not evaluate
  training interventions.
- Free-tier Colab GPU memory can be lower than reported; the model may still fail
  to load under some conditions.

## Future work

A later research stage could compare training approaches or examine internal model
changes associated with improved constraint compliance. That work is not implemented
here. The initial pipeline deliberately measures observable behavior only.

## Verification status

This repository was implemented and tested on a CPU-only Windows environment.
Dependency installation in Colab was not executed here. CPU-only unit tests,
synthetic summary generation, prompt/config validation, the fake-backend HTTP
protocol, the fake end-to-end runner, and bundle export were tested locally.
**GPU model loading, Colab execution, and real model generation were not executed
in that environment** and must be verified in Colab using the optional smoke test
and a real run.
