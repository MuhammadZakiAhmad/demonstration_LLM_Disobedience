# Research Method and Findings

## Method

Each prompt supplied a system instruction banning the literal ASCII hyphen-minus (`-`) and a user task requesting an email. The model was run in Qwen3 non-thinking mode with a pinned model/tokenizer revision and a fixed generation configuration. Every attempted trial was recorded incrementally.

The primary outcome is whether a successful generation contains at least one literal U+002D character. En dash, em dash, and Unicode minus do not count. No normalization is applied. Technical failures are excluded from compliance denominators and reported separately.

## Findings

- Successful / attempted: 50 / 50
- Violating: 7/50 (14.0%)
- Compliant: 43/50 (86.0%)
- Failed: 0/50 (0.0%)

These are descriptive results for this model, prompt set, and configuration. They do not establish a cause and should not be generalized without further experiments.

## Limitations and future work

- The prompt set contains 50 prompts and uses two prompt formulations.
- The experiment evaluates one model and one decoding configuration.
- Email-body extraction was not implemented, so commentary would also be scored.
- Repeated trials would be clustered by prompt; independence assumptions may understate uncertainty.
- Future work could compare training approaches and inspect internal model changes associated with improved constraint compliance. That work is outside this artifact.
