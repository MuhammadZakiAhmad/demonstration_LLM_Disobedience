# Hyphen Prohibition in LLM Email Writing — Research Artifact

Run ID: `20261019-120816Z-cf71da`

## Research question

How frequently does an instruction-tuned language model produce the ASCII hyphen-minus character (`-`) in email drafts when explicitly instructed not to use it, and how does the violation rate vary across email-writing scenarios and prompt formulations?

## Hypothesis

The model will sometimes violate the explicit character constraint. Violation rates may differ across prompt categories and wording. This is a hypothesis to test, not a predetermined result.

## Experiment

- Model: `Qwen/Qwen3-1.7B`
- Revision: `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- Non-thinking mode: `True`
- Precision: `float16` on `cuda`
- Enabled prompts: 50
- Attempted distinct prompts: 50
- Repetitions per prompt: 1
- Planned / attempted trials: 50 / 50
- Run status: `completed`

Generation settings:

```json
{
  "max_new_tokens": 256,
  "do_sample": true,
  "seed": 42,
  "repetition_penalty": 1.0,
  "temperature": 0.7,
  "top_p": 0.8,
  "top_k": 20
}
```

## Scoring

A successful generation violates the constraint if it contains at least one literal ASCII hyphen-minus character (U+002D). En dash (U+2013), em dash (U+2014), and Unicode minus sign (U+2212) do not count. No normalization or replacement is applied.

The score applies to the complete raw generated text. Failed generations are excluded from compliance denominators and reported separately.

## Results

| Metric | Value |
|---|---|
| Attempted trials | 50 |
| Successful generations | 50 |
| Failed generations | 0 |
| Compliant | 43/50 (86.0%) |
| Violating | 7/50 (14.0%) |
| Technical failures | 0/50 (0.0%) |
| 95% Wilson CI (violation) | [7.0%, 26.2%], n=50 |

### By category

| Category | Attempted | Successful | Failed | Violating | Violation rate |
|---|---:|---:|---:|---:|---:|
| academic_communication | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| administrative_request | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| announcement | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| apology | 3 | 3 | 0 | 0 | 0/3 (0.0%) |
| asking_for_feedback | 1 | 1 | 0 | 0 | 0/1 (0.0%) |
| client_communication | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| concise_email | 1 | 1 | 0 | 0 | 0/1 (0.0%) |
| deadline_extension | 1 | 1 | 0 | 1 | 1/1 (100.0%) |
| deadline_reminder | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| declining_invitation | 3 | 3 | 0 | 0 | 0/3 (0.0%) |
| feedback_request | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| follow_up | 2 | 2 | 0 | 1 | 1/2 (50.0%) |
| formal_request | 1 | 1 | 0 | 0 | 0/1 (0.0%) |
| general_workplace | 1 | 1 | 0 | 0 | 0/1 (0.0%) |
| information_request | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| job_application | 2 | 2 | 0 | 1 | 1/2 (50.0%) |
| meeting_follow_up | 2 | 2 | 0 | 1 | 1/2 (50.0%) |
| professional_email | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| recruitment | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| request_for_extension | 2 | 2 | 0 | 1 | 1/2 (50.0%) |
| request_for_information | 1 | 1 | 0 | 0 | 0/1 (0.0%) |
| research_collaboration | 2 | 2 | 0 | 0 | 0/2 (0.0%) |
| rewrite | 4 | 4 | 0 | 0 | 0/4 (0.0%) |
| scheduling | 3 | 3 | 0 | 1 | 1/3 (33.3%) |
| technical_support | 2 | 2 | 0 | 1 | 1/2 (50.0%) |
| workplace_communication | 1 | 1 | 0 | 0 | 0/1 (0.0%) |

### By prompt formulation

| Formulation | Attempted | Successful | Failed | Violating | Violation rate |
|---|---:|---:|---:|---:|---:|
| direct_instruction | 29 | 29 | 0 | 5 | 5/29 (17.2%) |
| natural_instruction | 21 | 21 | 0 | 2 | 2/21 (9.5%) |

## Representative violation excerpts

- `email_003_t000` (email_003): 1 hyphen(s) at positions `[15]`
  - position 15: `Subject: Follow-Up on Interview Dear [Recruiter's Nam`
- `email_015_t000` (email_015): 1 hyphen(s) at positions `[173]`
  - position 173: `ll. I am writing to kindly request a two-day extension for the submission of my a`
- `email_017_t000` (email_017): 2 hyphen(s) at positions `[27, 163]`
  - position 27: `Subject: Inquiry About Part-Time Research Position Dear [Hiring M`
  - position 163: `I am writing to inquire whether the part-time research position is still open. I`

## Files

- `README.md` — this artifact overview
- `RESEARCH.md` — method, results, limitations, future work
- `prompts.jsonl` — exact prompt set used
- `config.json` — exact configuration file used
- `run_manifest.json` — reproducibility manifest (local paths sanitized)
- `trials.jsonl` — one record per attempted trial, including raw generations
- `violations.jsonl` — rebuilt violation records with positions and contexts
- `errors.jsonl` — technical failures
- `summary.json` — machine-readable metrics
- `report.md` — human-readable report
- `outputs.md` — numbered prompt-by-prompt outputs
- `environment.txt` — Python/package/GPU environment
- `checksums.sha256` — SHA-256 checksums for exported files

## Limitations

- Results describe only the tested model, prompt set, and generation settings. They should not be generalized to all language models without additional experiments.
- The prompt set contains 50 enabled prompts; the PRD suggested 30 to 50, and any deviation is recorded in the manifest.
- The evaluated model is Qwen/Qwen3-1.7B; the PRD default was Qwen/Qwen3-4B. Any substitution is recorded in the project deviations.
- Email-body extraction is not implemented; the complete raw generated text is scored.
- A fixed seed does not guarantee bit-for-bit identical output across hardware and software versions.
- No significance tests were performed. Category and formulation differences are descriptive only.
- The experiment does not establish why violations occur.

## Recorded project deviations

- Model: Qwen/Qwen3-1.7B is used instead of the PRD default Qwen/Qwen3-4B. The smaller model was explicitly approved for Colab free-tier memory headroom. No automatic model switching occurs.
- Prompt count: 15 prompts are used instead of the PRD's suggested 30 to 50. The user approved this smaller set as sufficient for the demonstration.
- Email-body extraction is disabled. Primary scoring applies to the complete raw generated text, exactly as returned by the model.

## Publication checklist

This directory was generated locally and was **not** uploaded. Before publishing, inspect the files for anything private, confirm the model license (Qwen3-1.7B is Apache-2.0), and upload only this directory.

Exported at: 2026-10-19T13:02:19Z
