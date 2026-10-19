# PRD: Reproducible Evaluation of Hyphen Prohibition in LLM Email Writing

## 1. Project Overview

Build a small, reproducible research pipeline to investigate whether instruction-tuned open-weight language models violate an explicit instruction not to use the ASCII hyphen-minus character (`-`) when writing emails.

The experiment originates from a practical observation: when asked to draft emails without hyphens, language models sometimes include the prohibited character anyway. The frequency of this behavior may vary with the email scenario and prompt wording.

The first implementation must systematically measure this behavior rather than assume its cause.

The code will be maintained in a Git repository, developed with a coding agent, and executed in Google Colab.

### Primary research question

How frequently does an instruction-tuned language model produce the ASCII hyphen-minus character (`-`) in email drafts when explicitly instructed not to use it, and how does the violation rate vary across different email-writing scenarios and prompt formulations?

### Hypothesis

The model will sometimes violate the explicit character constraint. Violation rates may differ across prompt categories and wording.

This is a hypothesis to test, not a predetermined result.

### Scope boundary

This project evaluates observable instruction-following behavior. It does not attempt to establish why violations occur, inspect model internals, fine-tune a model, or demonstrate a solution to the problem.

A later research stage may compare training approaches or examine internal model representations. That work is out of scope for this implementation.

---

## 2. Goals and Success Criteria

The implementation must:

1. Load an open-weight instruction-tuned model with 0.6B to 6B parameters.
2. Keep the model loaded in a persistent Python process while experiment code is updated and rerun.
3. Run a collection of email-writing prompts stored in JSONL.
4. Detect the exact ASCII hyphen-minus character in generated email text.
5. Preserve every raw generation and its associated metadata.
6. Calculate overall and category-level violation rates.
7. Produce an auditable, reproducible record of each experiment.
8. Run in Google Colab with a GPU, including a free-tier runtime where available memory may be approximately 15 GB.
9. Be straightforward for a user with limited Python environment configuration experience.
10. Provide clear setup, execution, troubleshooting, and reproduction instructions.

### Success criteria

The project is considered ready when:

- A clean Colab runtime can be configured using the documented steps.
- The model loads successfully when compatible with the available GPU memory.
- The experiment can run multiple prompts without reloading the model for each prompt.
- Updating experiment files and rerunning the experiment does not require restarting the model process.
- All generated outputs are retained, including violations.
- The violation detector passes explicit unit tests.
- The summary metrics agree with the raw trial records.
- A subsequent run creates a distinct results directory rather than overwriting previous results.
- A failed or interrupted run can be diagnosed from its logs and manifest.

---

## 3. Model Requirements

### Default model

Use `Qwen/Qwen3-4B` as the initial model.

Model reference: https://huggingface.co/Qwen/Qwen3-4B

Requirements:

- Confirm that the selected checkpoint is an instruction-tuned model.
- Record the exact model revision or commit hash.
- Load the matching tokenizer from the same pinned revision.
- Use the model's documented non-thinking mode for the primary experiment.
- Use Hugging Face Transformers and PyTorch unless a demonstrated compatibility issue requires a change.
- Check GPU availability and memory before loading.
- Report the chosen model, precision, device, and memory information.
- Fail with a useful error message if the model cannot be loaded under the configured settings.

Do not automatically switch models, quantization modes, precision, or generation settings when a load fails. Explain the problem and document an explicit alternative configuration instead.

### Precision and memory

Make model precision configurable through `config.json`.

Choose an appropriate precision supported by the runtime and model. Start with a conservative configuration compatible with the detected GPU.

Do not assume that a reported 15 GB of VRAM guarantees sufficient memory in every environment. Actual availability may be lower, and memory use depends on model loading, sequence length, generation settings, and runtime overhead.

Do not add quantization libraries unless they are necessary for the supported configuration.

### Generation interface

`model_loader.py` must expose a simple, documented interface for generating text.

The interface should accept:

- Prompt messages or a formatted prompt.
- Generation configuration.
- A reproducibility seed, where supported.

It should return the generated text and relevant generation metadata.

The interface must not require `main.py` to know the details of model loading or tokenization.

---

## 4. System Architecture

Use a simple Python repository with a persistent model server and a separate experiment runner.

The model server owns the model and tokenizer. The experiment runner sends generation requests to the server and handles experiment logic.

This separation is required because ordinary execution of `python main.py` creates a new process and cannot reuse a model held in memory by another process unless communication is explicitly implemented.

### Required repository structure

```text
hyphen-compliance-eval/
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
├── tests/
│   ├── test_scoring.py
│   ├── test_prompt_validation.py
│   └── test_result_integrity.py
├── scripts/
│   ├── setup_colab.sh
│   ├── start_model.sh
│   └── run_experiment.sh
└── results/
    └── .gitkeep
```

The coding agent may adjust this layout if there is a clear engineering reason, but it must preserve the separation of responsibilities and the user-facing workflow.

Do not commit generated model weights, caches, virtual environments, secrets, or large result files to Git.

### `model_loader.py`

Responsibilities:

- Load the pinned model revision and tokenizer.
- Configure the documented non-thinking mode.
- Apply the configured precision and device settings.
- Check available GPU memory.
- Expose the text-generation interface.
- Report model loading errors clearly.
- Avoid loading the model more than once per server process.

### `model_server.py`

Responsibilities:

- Start a persistent Python process.
- Load the model once.
- Expose a minimal local interface for generation requests.
- Accept multiple requests sequentially.
- Return the generated text and request metadata.
- Handle malformed requests without corrupting the process.
- Log startup, loading, and request errors.
- Provide a health check so the experiment runner can verify that the model is ready.
- Support a graceful shutdown.
- Keep the server bound to localhost unless there is a documented reason otherwise.

Use a simple local HTTP API or another equally reliable local IPC mechanism. Do not introduce a database, container orchestration, or distributed infrastructure.

The server must not automatically reload the model after experiment code changes.

### `main.py`

Responsibilities:

- Validate the experiment configuration and prompt file.
- Connect to the already-running model server.
- Create a unique run directory.
- Execute prompts in a deterministic order.
- Generate and save trial records incrementally.
- Record errors and interrupted runs.
- Run scoring and produce final summaries.
- Never overwrite an existing run's outputs.

If the model server is not running, show the exact command needed to start it.

### `scoring.py`

Responsibilities:

- Implement the exact character-level violation rule.
- Provide reusable scoring functions.
- Preserve the distinction between raw generated output and any extracted email body.
- Return violation positions and surrounding context for auditing.
- Include unit tests for ASCII hyphen-minus versus other dash characters.

### `summarize_results.py`

Responsibilities:

- Read completed trial records.
- Calculate overall and category-level statistics.
- Verify that counts agree with the underlying records.
- Produce a machine-readable summary.
- Support recomputing the summary without generating new model outputs.

### `environment_report.py`

Record available environment details, including Python version, package versions, PyTorch version, Transformers version, GPU name, total GPU memory, available GPU memory where obtainable, and relevant hardware information.

Do not include credentials, access tokens, or unrelated private environment variables.

---

## 5. Experiment Design

### Prompt categories

Create an initial prompt collection of approximately 30 to 50 distinct prompts distributed across several realistic email-writing scenarios.

Include categories such as:

1. Professional email drafting.
2. Replying to an existing email.
3. Polite follow-up emails.
4. Apologies and clarification.
5. Requests for information or assistance.
6. Scheduling and meeting coordination.
7. Concise workplace communication.
8. Rewriting or polishing a supplied draft.

The exact number of prompts and distribution should be configurable.

Each category should contain multiple scenarios. Avoid relying entirely on trivial variations of one prompt.

### Prompt structure

Store prompts in `prompts.jsonl`, with one valid JSON object per line.

Each prompt should contain at least:

- `prompt_id`: stable, unique identifier.
- `category`: scenario category.
- `prompt_variant`: prompt formulation or condition identifier.
- `system_instruction`: the instruction governing email generation.
- `user_prompt`: the email-writing task.
- `expected_output_type`: initially `email`.
- `enabled`: whether the prompt should run.

Keep the explicit ban on the ASCII hyphen-minus consistent across the primary prompt set.

Include realistic tasks and varied wording. Some prompts can state the constraint directly; others can integrate it naturally into the task. Preserve a clear distinction between prompt formulations so the results can be analyzed by condition.

For the initial experiment, do not intentionally vary the prohibited character constraint itself. The goal is to test compliance under that constraint, not to compare instructions that permit versus prohibit the character.

Validate the JSONL file before running the model. Invalid lines and duplicate IDs must produce useful error messages.

### Trial policy

The default should be one generation per prompt.

Allow the number of repetitions to be configured. If repeated trials are enabled, give every trial a unique ID and preserve the prompt ID linking it to the original prompt.

Do not silently discard failed generations or retry them in a way that changes the number of trials without recording the retry.

Record technical failures separately from successful generations. Do not count a failed generation as compliant or noncompliant.

---

## 6. Reproducibility Requirements

Reproducibility is a core requirement, not an optional feature.

### Generation settings

Store all relevant settings in `config.json`, including:

- Model ID.
- Model revision.
- Tokenizer revision.
- Maximum new tokens.
- Sampling enabled or disabled.
- Temperature, if sampling is enabled.
- Top-p and other active sampling settings.
- Random seed.
- Model precision.
- Device configuration.
- Prompt file path.
- Number of repetitions.
- Output extraction configuration, if any.
- Request timeout and server configuration.

Choose and document a single default generation configuration for the initial experiment.

For the primary run, use a fixed seed and a consistent decoding configuration. If the model's documented non-thinking mode recommends particular sampling settings, record those settings and explain the choice. Do not change settings between prompts unless the experiment explicitly defines a separate condition.

A fixed seed does not guarantee bit-for-bit identical output across all hardware and software versions. The README must state this limitation.

### Run manifest

Every run must include `run_manifest.json` with:

- Unique run ID.
- Start and end timestamps in UTC.
- Run status: `running`, `completed`, `interrupted`, or `failed`.
- Git commit hash when available.
- Model and tokenizer IDs and pinned revisions.
- Full generation configuration.
- Python and dependency versions.
- GPU and memory information.
- Prompt file hash.
- Configuration file hash.
- Total prompts selected.
- Planned and completed trial counts.
- Successful and failed generation counts.
- Scoring implementation version.
- Relevant warnings.

Write the initial manifest before generation begins, update it as the run progresses, and finalize it when the run ends.

### Repeatability

The experiment must use a stable ordering of prompts and trials.

A rerun must create a new run directory. Never append results from a new run to an earlier run unless an explicit, documented resume mode is implemented.

If resume mode is implemented, preserve the original run ID and configuration, verify that model and prompt revisions match, and never silently mix records from different configurations.

---

## 7. Scoring Rules

The primary outcome is whether a generated email contains at least one literal ASCII hyphen-minus character.

The prohibited character is:

```text
-
```

The following are distinct Unicode characters and do not count as violations of this particular constraint:

- En dash: `–`
- Em dash: `—`
- Unicode minus sign: `−`

Do not normalize or replace dash characters before scoring.

### Primary metrics

Calculate:

- Total successful generations.
- Number of compliant generations.
- Number of violating generations.
- Overall violation rate.
- Overall compliance rate.
- Violation rate by prompt category.
- Violation rate by prompt formulation.
- Number and proportion of technical failures.

The violation rate is:

`violating successful generations / all successful generations`

The compliance rate is:

`compliant successful generations / all successful generations`

Technical failures must be excluded from these denominators and reported separately.

Also report numerators and denominators alongside percentages. Do not present a percentage without its sample count.

### Additional diagnostic metrics

For each violating output, record:

- Total number of ASCII hyphen-minus occurrences.
- Zero-based character positions.
- Short excerpts around each occurrence.
- Whether the violation appears in the email body or in surrounding model commentary, if extraction can make that distinction reliably.

Do not make email-body extraction a hidden prerequisite for primary scoring. The primary score should apply to the defined generated email text, with any exclusions explicitly documented.

### Statistical uncertainty

Where appropriate, calculate a 95% confidence interval for the overall violation proportion. Document the method used.

If trials are repeated for the same prompt, explain that the observations are clustered by prompt and that treating every generation as independent may understate uncertainty. For the initial small experiment, provide descriptive counts and rates even if a more sophisticated interval is not implemented.

Do not claim that a difference between categories is statistically significant unless an appropriate test has actually been performed.

---

## 8. Results and Data Format

Each run must produce a separate directory:

```text
results/
└── <run_id>/
    ├── run_manifest.json
    ├── trials.jsonl
    ├── summary.json
    ├── violations.jsonl
    ├── errors.jsonl
    ├── environment.txt
    └── report.md
```

### `trials.jsonl`

One record per attempted trial. Each record should include:

- `run_id`
- `trial_id`
- `prompt_id`
- `category`
- `prompt_variant`
- `trial_index`
- `timestamp_utc`
- `model_id`
- `model_revision`
- `generation_config`
- `system_instruction`
- `user_prompt`
- `raw_generated_text`
- `extracted_email_text`, if implemented
- `generation_status`
- `error`, when applicable
- `contains_ascii_hyphen`
- `ascii_hyphen_count`
- `violation_positions`
- `violation_contexts`
- `is_compliant`, or `null` if no valid generation was produced
- `generation_duration_seconds`

Store enough information to audit the experiment without depending on transient notebook state.

Do not silently truncate outputs in the raw records. If a generation is truncated because of the configured token limit, preserve it and record the applicable generation metadata.

### `violations.jsonl`

Include the trial identifiers and scoring details for violating generations. Preserve the exact matching positions and context excerpts.

This file must be reproducible from `trials.jsonl` using the scoring implementation.

### `summary.json`

Include:

- Overall metrics.
- Metrics by category.
- Metrics by prompt formulation.
- Confidence intervals, where implemented.
- Counts of successful, failed, compliant, and violating trials.
- Summary of generation settings.
- Run ID and model revision.
- Data validation warnings.

### `report.md`

Generate a readable report containing:

1. Research question.
2. Model and configuration.
3. Prompt set description.
4. Scoring methodology.
5. Overall results.
6. Results by category and formulation.
7. Representative violations, quoted exactly from the generated outputs where useful.
8. Technical failures and missing data.
9. Limitations.
10. Reproduction commands.

Do not fabricate or prepopulate results. All reported numbers must be derived from actual trial records.

### Data integrity

Write trial results incrementally so that completed trials survive a runtime interruption.

Write JSONL as valid, one-object-per-line JSON. Ensure strings containing newlines and Unicode characters are serialized correctly.

Do not commit experiment results to Git by default. Document how to download or publish selected artifacts separately.

---

## 9. Persistent Colab Workflow

The implementation must support the following workflow.

### Initial setup

1. Open Google Colab.
2. Select a GPU runtime.
3. Clone the Git repository.
4. Run the documented setup command.
5. Start the model server.
6. Wait for the health check to confirm that the model is ready.
7. Run the experiment.

### Subsequent experiments

1. Edit experiment code or `prompts.jsonl` locally.
2. Commit and push the changes.
3. Pull the changes in the existing Colab checkout.
4. Run the experiment again.
5. Reuse the model already held by the persistent server.

The setup should not require the user to manually configure a complex Python environment.

### Required operational details

- Use the current Colab runtime's Python environment rather than requiring the user to configure a separate virtual machine.
- Provide a single setup script that installs pinned dependencies.
- Provide separate commands to start the model server and run an experiment.
- Clearly explain how to check server health.
- Provide a command to stop the server cleanly.
- Make the runner fail with a useful message if the server is unreachable.
- Handle a Colab runtime reset by explaining that the model must be loaded again.
- Avoid instructions that imply model memory survives a runtime disconnection.
- Do not assume that `git pull` reloads already-imported Python modules. The experiment runner must execute updated code in its own process while the server retains the model.

Use pinned, mutually compatible dependencies. Avoid unnecessarily restrictive pins that make installation fail on the current Colab runtime. Test the documented installation commands as far as the available environment allows and document any unverified steps.

Do not embed Hugging Face tokens or other secrets in source code. If authentication is needed for any optional feature, use the platform's supported secret mechanism.

---

## 10. Hugging Face Research Artifacts

The fellowship challenge requires a public Hugging Face Bucket containing artifacts and a README answering the relevant research questions.

This repository should therefore support exporting a clean, self-contained research artifact directory.

Include a documented export procedure that prepares:

- Research question and hypothesis.
- Experimental method.
- Prompt set.
- Model identifier and revision.
- Configuration and reproducibility metadata.
- Raw trial records.
- Summary statistics.
- Violation examples.
- Results report.
- Limitations and future work.

Do not automatically publish results during a normal experiment run. Publication must be a separate, explicit step so the user can inspect outputs and remove unintended private information first.

Do not put secrets, access tokens, personal data, or unrelated local files into the publication bundle.

The README must explain that results describe the tested model, prompts, and settings; they should not be generalized to all language models without additional experiments.

The proposed future direction may be documented separately: comparing training approaches and investigating internal model changes associated with improved constraint compliance. Do not implement that work in the initial pipeline.

---

## 11. Testing Requirements

Implement automated tests that do not require loading the model or accessing a GPU.

### Scoring tests

Verify that:

- A response containing `-` is marked as violating.
- A response without `-` is marked as compliant.
- An en dash alone is not counted.
- An em dash alone is not counted.
- A Unicode minus sign alone is not counted.
- Multiple ASCII hyphens are counted correctly.
- Character positions use the documented zero-based indexing.
- Empty strings are handled correctly.
- Non-ASCII text is handled correctly.
- Text is scored without normalization or replacement.

### Prompt validation tests

Verify that:

- Valid JSONL is accepted.
- Invalid JSON produces a useful error.
- Duplicate prompt IDs are rejected.
- Required fields are checked.
- Disabled prompts are excluded.
- Prompt ordering is deterministic.

### Result integrity tests

Verify that:

- Successful and failed generations are represented correctly.
- Failed generations are not classified as compliant.
- Summary counts match trial records.
- Violation records can be regenerated from the raw trial records.
- New runs do not overwrite previous runs.
- Partial results remain valid after interruption.

### Model integration test

Provide an optional smoke test that runs a single short generation when a GPU and the model are available. It must not be required for ordinary unit tests.

---

## 12. Documentation Requirements

`README.md` must be written for a user who is not experienced in Python environment configuration.

Include:

- Project purpose and research question.
- Prerequisites.
- Model information and licensing reference.
- Exact Colab setup instructions.
- Commands to start, check, and stop the model server.
- Commands to run an experiment.
- Instructions for editing prompts.
- Explanation of all configuration options.
- Explanation of result files and scoring.
- How to pull code updates without reloading the model.
- How to reproduce a previous run as closely as possible.
- Common error messages and fixes.
- How to export artifacts for Hugging Face.
- Known limitations.

Use copyable shell commands. Do not assume the user already understands process management, Python imports, environment variables, or GPU memory management.

---

## 13. Out of Scope

Do not implement:

- Fine-tuning, SFT, or reinforcement learning.
- Comparisons between multiple models.
- Logit, attention, or activation analysis.
- A dashboard or web interface.
- Distributed inference.
- A database.
- Automated publication of research results.
- Automated interpretation of whether a violation was intentional.
- A claimed explanation for the behavior based solely on the observed violation rate.

Keep the first version small, reliable, auditable, and extensible.

---

## 14. Implementation Instructions for the Coding Agent

Implement the repository according to this PRD.

Before writing substantial code:

1. Inspect the available environment and relevant model documentation.
2. Check the current recommended loading interface for the pinned model revision.
3. Confirm a compatible set of Python dependencies.
4. Identify any uncertainty in the persistent-server approach and resolve it with a minimal design.
5. Present a concise implementation plan.

Then implement the code, tests, scripts, and documentation.

After implementation:

1. Run all CPU-only tests.
2. Validate the configuration and sample JSONL prompt file.
3. Test summary generation using synthetic records.
4. Test the server health-check and request protocol without requiring a full model download, where feasible.
5. Perform a GPU smoke test only if the environment supports it.
6. Check that results are not overwritten and that incomplete runs are represented honestly.
7. Provide a final summary of files created, tests run, test outcomes, and any steps that remain unverified.

Do not claim that GPU loading, Colab execution, or model generation was tested if it was not actually executed.

If a requirement cannot be implemented reliably, explain the limitation and propose the smallest appropriate adjustment instead of silently omitting the requirement.

## 15. Final Deliverable

Deliver a complete Git-ready repository containing the Python source files, configuration, prompt dataset, automated tests, setup scripts, README, and this PRD.

The final implementation should allow the user to clone the repository into Colab, load the model once, run the evaluation, inspect detailed results, update experiment code through Git, and reproduce the methodology without needing to understand the internal implementation.
