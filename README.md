When a Language Model Ignores a Writing Constraint
1. The observation
I have noticed a small but recurring problem when using language models to write emails. Even when I explicitly ask a model not to use hyphens, it sometimes includes them in the subject line or body.

This may seem like a minor formatting issue. However, it raises a broader question about instruction following. If a model cannot consistently respect a simple constraint, how reliable is it when a task has several requirements that must all be followed?

I chose to study this behavior because it comes from my own experience using language models, rather than from a standard benchmark. I wanted to see whether I could measure it in a controlled setting.

2. Research question
How often does an instruction tuned language model use the ASCII hyphen minus character when explicitly instructed not to use it in an email?

I also wanted to see whether violations appeared in different parts of an email and whether their frequency varied across prompt formulations.

My initial expectation was that the model would sometimes violate the instruction. I did not assume that the wording of the prompt would explain those violations.

#DISCLAIMER
Though all the coding for this project was done using Claude Code. I designed the experiment myself, including the research question, prompt set, instruction variations, scoring rule, and evaluation plan. Each adn every decision of the architecture of this experiment is mine and I can defend/discuss my choices with my own rational.

3. Model evaluation

I evaluated Qwen/Qwen3-1.7B, an open weight model hosted on Hugging Face, using Google Colab.

I created 50 email writing prompts covering different situations and two instruction styles, direct and natural. Each prompt was run once using the same model revision and generation configuration.

I counted a response as a violation if it contained the ASCII hyphen minus character, U+002D, anywhere in the output, including the subject line. Other dash characters did not count.

The model completed all 50 generations. Of these, 43 followed the constraint and 7 contained at least one prohibited character. The observed violation rate was 14%, with a 95% Wilson confidence interval of 7.0% to 26.2%.

The violations appeared in subject lines and email bodies. Examples included Follow-Up, two-day, and check-in.

This shows that the model did not consistently follow the constraint in this set of trials. It does not explain why. Common writing patterns may contribute, but prompt wording, instruction placement, and generation variability are other possible explanations.

The result is limited to one model, one generation per prompt, and a dataset I constructed for this experiment. The two instruction styles were not tested as matched pairs, so their observed difference cannot establish a causal effect.

4. Path forward

My next step would be to run ablation style studies using matched prompts. I would change one factor at a time, such as the wording or placement of the instruction, and repeat generations to measure how these changes affect compliance.

I also want to compare instruction fine tuning (IFT) with reinforcement learning (RL) to see which approach improves compliance more effectively. After evaluating both on the same tasks and held out prompts, I would investigate their internal differences at a lower level like activations, attentions patterns etc to see precise changes from the base model that made the difference. This could help me understand how each training approach changes model behavior.

One possible direction is to train models on examples where they must satisfy writing goals while respecting precise constraints. The aim would not be to remove hyphens from all text, but to use them only when permitted by the user's instructions.

These are proposed directions, not findings from the current experiment. I have not yet tested either training method.

Artifacts

The repository contains the evaluation code, prompt definitions, scoring logic, and recorded results.

Model: Qwen/Qwen3-1.7B

Revision: 70d244cc86cc

Prompts: 50

Generations per prompt: 1

Public Hugging Face Bucket: Add the verified public link here.
