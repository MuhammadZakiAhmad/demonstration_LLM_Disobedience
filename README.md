# When a Language Model Ignores a Writing Constraint

## 1. The observation

It is from my own again and again personal expereince, when using language models to write emails it uses lots of hyphens. Even when I explicitly ask a model not to use them, it sometimes includes them in the subject line or body.

This may seem like a minor formatting issue. However, it raises a broader question about **instruction following**. If a model cannot consistently respect a simple constraint, how reliable is it when a task has several requirements that must all be followed?

I chose to study this behavior because it comes from my own experience using language models, rather than from a standard benchmark and I have seen it sometimes happening even in the largest frontier models aswells.

## 2. Research question

> How often does an instruction tuned language model use the ASCII hyphen minus character when explicitly instructed not to use it in an email?

I also wanted to see whether violations appeared in different parts of an email and whether their frequency varied across prompt formulations.

My initial expectation was that the model would sometimes violate the instruction. I did not assume that the wording of the prompt would explain those violations.

### Disclaimer on authorship

Though all the coding for this project was primarily done using Claude Code. I designed the experiment myself, including the research question, prompt set, instruction variations, scoring rule, and evaluation plan. Each and every decision of the architecture of this experiment is mine and I can defend/discuss my choices with my own rational.

## 3. Model evaluation

I evaluated **Qwen/Qwen3-1.7B**, an open weight model hosted on Hugging Face, using Google Colab.

I created 50 email writing prompts covering different situations and two instruction styles, direct and natural. Each prompt was run once using the same model revision and generation configuration.

I counted a response as a violation if it contained the ASCII hyphen minus character, `U+002D`, anywhere in the output, including the subject line. Other dash characters did not count.

### Results at a glance

| Evaluation measure | Result |
|:--|--:|
| Model | Qwen3-1.7B |
| Prompts evaluated | 50 |
| Generations per prompt | 1 |
| Successful generations | 50 |
| Compliant responses | 43 |
| Responses with violations | 7 |
| **Observed violation rate** | **14.0%** |
| 95% Wilson confidence interval | 7.0% to 26.2% |

### What did the violations look like?

The violations appeared in both subject lines and email bodies. Examples included `Follow-Up`, `two-day`, and `check-in`.

The findings show that the model did not consistently follow the constraint in this set of trials. They do not explain why. Common writing patterns may contribute, but prompt wording, instruction placement, and generation variability are other possible explanations.

### Limitations

The result is limited to one model, one generation per prompt, and a dataset I constructed for this experiment. The two instruction styles were not tested as matched pairs, so their observed difference cannot establish a causal effect.

The **14% violation rate describes this evaluation set**, not the general behavior of all language models or even all tasks performed by this model.

## 4. Path forward

My next step would be to run ablation style studies using matched prompts. I would change one factor at a time, such as the wording or placement of the instruction, and repeat generations to measure how these changes affect compliance.

I also want to compare **instruction fine tuning (IFT) with reinforcement learning (RL)** to see which approach improves compliance more effectively. After evaluating both on the same tasks and held out prompts, I would investigate their internal differences at a lower level, including activations, attention patterns, and layer wise changes from the base model. This could help explain why one approach performs better than the other and how each changes the model's ability to follow explicit instructions.

I see this as relevant beyond email writing. As LLMs increasingly act as the brains of AI agents, they must follow constraints across multiple steps, tools, and decisions. An agent might be asked to use a specific format, avoid certain actions, or respect limits while completing a larger task. If it ignores one of these constraints, the consequences can extend beyond a single response. By studying how models learn to respect precise instructions, this research could contribute to more reliable agents that follow user requirements consistently, even when those requirements conflict with common patterns in their training data.

Ultimately, I want to understand not only whether a model follows an instruction, but also which training methods make it more reliable and what changes inside the model accompany that improvement. This could help guide the development of models that are not only capable of completing tasks, but also more dependable in how they complete them.

These are proposed directions, not findings from the current experiment. I have not yet tested either training method.

## 5. Artifacts and reproducibility

The repository contains the evaluation code, prompt definitions, scoring logic, and recorded results.

| Artifact detail | Value |
|:--|:--|
| Model | `Qwen/Qwen3-1.7B` |
| Model revision | `70d244cc86cc` |
| Number of prompts | 50 |
| Generations per prompt | 1 |
| Evaluation environment | Google Colab |

**Public Hugging Face Bucket:** [demonstration_llm_disobedience](https://huggingface.co/buckets/mza2001/demonstration_llm_disobedience-bucket)

The public repository provides access to the project artifacts for further inspection.
