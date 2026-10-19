# Hyphen Compliance Evaluation — 20261019-120816Z-cf71da

## 1. Research question

How frequently does an instruction-tuned language model produce the ASCII hyphen-minus character (`-`) in email drafts when explicitly instructed not to use it, and how does the violation rate vary across email-writing scenarios and prompt formulations?

This is a descriptive evaluation of one model, prompt set, and generation configuration. It does not establish why violations occur.

## 2. Model and configuration

- Model: `Qwen/Qwen3-1.7B`
- Model revision: `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- Tokenizer: `Qwen/Qwen3-1.7B` @ `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- Precision: `float16`
- Device: `cuda`
- Non-thinking mode: `True`
- EOS token ids: `[151643, 151645]`

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

A fixed seed is recorded per trial. A fixed seed does not guarantee bit-for-bit identical output across hardware, PyTorch, Transformers, or CUDA versions.

## 3. Prompt set

- Enabled prompts: 50 (planned trials: 50; attempted: 50)
- Attempted distinct prompts: 50
- Repetitions per prompt: 1
- Categories: `{"academic_communication": 2, "administrative_request": 2, "announcement": 2, "apology": 3, "asking_for_feedback": 1, "client_communication": 2, "concise_email": 1, "deadline_extension": 1, "deadline_reminder": 2, "declining_invitation": 3, "feedback_request": 2, "follow_up": 2, "formal_request": 1, "general_workplace": 1, "information_request": 2, "job_application": 2, "meeting_follow_up": 2, "professional_email": 2, "recruitment": 2, "request_for_extension": 2, "request_for_information": 1, "research_collaboration": 2, "rewrite": 4, "scheduling": 3, "technical_support": 2, "workplace_communication": 1}`
- Prompt variants: `{"direct_instruction": 29, "natural_instruction": 21}`

## 4. Scoring methodology

A successful generation violates the constraint if it contains at least one literal ASCII hyphen-minus character (U+002D). En dash (U+2013), em dash (U+2014), and Unicode minus sign (U+2212) do not count. No normalization or replacement is applied.

The primary score applies to the complete raw generated text. Email-body extraction is not implemented, so violations are not attributed to body versus commentary. Failed generations are excluded from compliance denominators and reported separately.

Confidence interval: Wilson score interval at 95% confidence, computed on successful generations only. It does not account for clustering by prompt.

## 5. Overall results

- Attempted trials: 50
- Successful generations: 50
- Failed generations: 0
- Compliant: 43/50 (86.0%)
- Violating: 7/50 (14.0%)
- Technical failure proportion: 0/50 (0.0%)
- 95% Wilson CI for violation proportion: [7.0%, 26.2%] (n=50)

## 6. Results by category and formulation

### By category

| Category | Attempted | Successful | Failed | Compliant | Violating | Violation rate |
|---|---:|---:|---:|---:|---:|---:|
| academic_communication | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| administrative_request | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| announcement | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| apology | 3 | 3 | 0 | 3 | 0 | 0/3 (0.0%) |
| asking_for_feedback | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| client_communication | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| concise_email | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| deadline_extension | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| deadline_reminder | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| declining_invitation | 3 | 3 | 0 | 3 | 0 | 0/3 (0.0%) |
| feedback_request | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| follow_up | 2 | 2 | 0 | 1 | 1 | 1/2 (50.0%) |
| formal_request | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| general_workplace | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| information_request | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| job_application | 2 | 2 | 0 | 1 | 1 | 1/2 (50.0%) |
| meeting_follow_up | 2 | 2 | 0 | 1 | 1 | 1/2 (50.0%) |
| professional_email | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| recruitment | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| request_for_extension | 2 | 2 | 0 | 1 | 1 | 1/2 (50.0%) |
| request_for_information | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| research_collaboration | 2 | 2 | 0 | 2 | 0 | 0/2 (0.0%) |
| rewrite | 4 | 4 | 0 | 4 | 0 | 0/4 (0.0%) |
| scheduling | 3 | 3 | 0 | 2 | 1 | 1/3 (33.3%) |
| technical_support | 2 | 2 | 0 | 1 | 1 | 1/2 (50.0%) |
| workplace_communication | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |

### By prompt formulation

| Prompt variant | Attempted | Successful | Failed | Compliant | Violating | Violation rate |
|---|---:|---:|---:|---:|---:|---:|
| direct_instruction | 29 | 29 | 0 | 24 | 5 | 5/29 (17.2%) |
| natural_instruction | 21 | 21 | 0 | 19 | 2 | 2/21 (9.5%) |

### By prompt

| Prompt | Attempted | Successful | Failed | Compliant | Violating | Violation rate |
|---|---:|---:|---:|---:|---:|---:|
| email_001 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_002 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_003 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_004 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_005 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_006 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_007 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_008 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_009 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_010 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_011 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_012 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_013 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_014 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_015 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_016 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_017 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_018 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_019 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_020 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_021 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_022 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_023 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_024 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_025 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_026 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_027 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_028 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_029 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_030 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_031 | 1 | 1 | 0 | 0 | 1 | 1/1 (100.0%) |
| email_032 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_033 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_034 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_035 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_036 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_037 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_038 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_039 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_040 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_041 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_042 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_043 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_044 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_045 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_046 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_047 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_048 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_049 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |
| email_050 | 1 | 1 | 0 | 1 | 0 | 0/1 (0.0%) |

Percentages are shown with numerators and denominators. No significance test is applied; do not interpret differences as statistically significant.

## 7. Representative violations

### Trial `email_003_t000` (email_003, follow_up)

ASCII hyphen count: 1; positions: [15]

```text
Subject: Follow-Up on Interview  

Dear [Recruiter's Name],  

Thank you for taking the time to interview me last week. I truly appreciate your support and the opportunity to discuss my qualifications.  

I wanted to check in to see if there’s any update on the hiring decision. If you’ve received any further information, I’d be grateful if you could let me know.  

Thank you again for your time and consideration. I look forward to hearing from you.  

Best regards,  
[Your Full Name]
```

Context excerpts:

- position 15: `Subject: Follow-Up on Interview Dear [Recruiter's Nam`

### Trial `email_015_t000` (email_015, deadline_extension)

ASCII hyphen count: 1; positions: [173]

```text
Subject: Request for Extension on Application Submission  

Dear [Fellowship Coordinator's Name],  

I hope this message finds you well. I am writing to kindly request a two-day extension for the submission of my application. Due to unforeseen circumstances, the required supporting document has been delayed, and I am unable to meet the original deadline as scheduled.  

I would greatly appreciate it if you could consider granting this extension. If possible, I would be grateful for any guidance or clarification you might have on the process for submitting the updated application.  

Thank you for your understanding and support. I look forward to your response.  

Best regards,  
[Your Full Name]  
[Your Contact Information]
```

Context excerpts:

- position 173: `ll. I am writing to kindly request a two-day extension for the submission of my a`

### Trial `email_017_t000` (email_017, job_application)

ASCII hyphen count: 2; positions: [27, 163]

```text
Subject: Inquiry About Part-Time Research Position  

Dear [Hiring Manager's Name],  

I hope this message finds you well. I am writing to inquire whether the part-time research position is still open. I have been following your organization’s work and am particularly interested in contributing to [specific project or area of focus].  

My background in [relevant field or experience] aligns well with the goals of the role, and I would be grateful for the opportunity to discuss how my skills and interests could support your team. If the position is still available, I would be happy to provide additional information or express my willingness to apply.  

Thank you for your time and consideration. I look forward to hearing from you.  

Best regards,  
[Your Full Name]  
[Your Contact Information]
```

Context excerpts:

- position 27: `Subject: Inquiry About Part-Time Research Position Dear [Hiring M`
- position 163: `I am writing to inquire whether the part-time research position is still open. I`

4 additional violating output(s) are in `outputs.md` and `violations.jsonl`.

## 8. Technical failures and missing data

No technical failures were recorded.

## 9. Limitations

- Results describe only the tested model, prompt set, and generation settings. They must not be generalized to all language models or all prompts.
- The prompt set contains 50 enabled prompts. The PRD suggests 30 to 50; the enabled set is the configuration for this run and any deviation is recorded in the manifest.
- The evaluated model is Qwen/Qwen3-1.7B. The PRD default was Qwen/Qwen3-4B; any model substitution is recorded in the known deviations.
- Scoring uses the entire raw generated text because email-body extraction is not implemented. Any commentary around the email is scored too.
- A fixed seed does not guarantee bit-identical output across hardware and software versions.
- With repeated trials, observations are clustered by prompt; the Wilson interval treats generations as independent and may understate uncertainty.
- No significance tests were performed. Category and formulation differences are descriptive only.
- This experiment does not explain why violations occur and does not evaluate training interventions.

### Recorded project deviations

- Model: Qwen/Qwen3-1.7B is used instead of the PRD default Qwen/Qwen3-4B. The smaller model was explicitly approved for Colab free-tier memory headroom. No automatic model switching occurs.
- Prompt count: 15 prompts are used instead of the PRD's suggested 30 to 50. The user approved this smaller set as sufficient for the demonstration.
- Email-body extraction is disabled. Primary scoring applies to the complete raw generated text, exactly as returned by the model.

## 10. Reproduction

```bash
# From the repository root; run in a Colab GPU runtime
bash scripts/setup_colab.sh
bash scripts/start_model.sh
bash scripts/check_model.sh
bash scripts/run_experiment.sh
python summarize_results.py results/20261019-120816Z-cf71da --show
```

Report generated at 2026-10-19T12:11:23Z from `trials.jsonl`. All numbers are derived from recorded trials.
