# How Heard should hold a conversation

The reported opening kept returning to requests for personal disclosure while the person was checking their microphone and asking who Heard was. More context alone cannot fix that: the assistant needs to recognize what the person is doing in the current turn.

## Research translated into behavior

| Guidance | Application in Heard |
| --- | --- |
| BACP describes introductions, explaining how counseling works, and room for the client's questions in an initial meeting. | Answer identity, microphone, and process questions directly. Allow someone to settle in before asking about a concern. [BACP](https://www.bacp.co.uk/about-therapy/what-is-counselling/) |
| SAMHSA describes partnership, autonomy, reflective listening, and the problems with a question-and-answer trap. | Follow the person's chosen focus. Use specific reflections between questions and explore their own options before offering advice. [SAMHSA TIP 35, Chapter 3](https://www.ncbi.nlm.nih.gov/books/NBK571068/) |
| The same guidance describes reflections that explore meaning and summaries that bring together what a person has said. | Offer tentative interpretations grounded in their words, invite correction when useful, and summarize at meaningful transitions. Avoid guessing motives or merely paraphrasing every sentence. [SAMHSA TIP 35, Chapter 3](https://www.ncbi.nlm.nih.gov/books/NBK571068/) |

These are product adaptations of professional guidance. SAMHSA's chapter concerns motivational interviewing in substance use treatment; it is not evidence that this AI provides effective therapy. Public guidance is being used to design behavior, not copied into a training corpus.

## The opening

The greeting identifies Heard as AI and leaves room to begin. A narrow voice-only microphone check receives an immediate acknowledgement that words arrived; it does not claim to measure sound quality or emotion. Questions such as "Who are you?" and "How can you help?" receive ordinary, concrete answers without an appended invitation to disclose feelings.

Standalone voice fillers such as "Like," remain visible in the transcript while Heard waits for continuation. Meaningful short replies such as "yes," "no," and "help" are not filtered. Typed messages always receive a turn. Voice detection also allows a longer pause before treating speech as finished.

## Working through a concern

The conversation can move between understanding the story, agreeing what matters, exploring a tension or meaning, bringing the thread together, and considering an action the person wants. These are possible directions, not a mandatory interview or assessment. Corrections and the latest explicit request take precedence over earlier assumptions and the selected conversation style.

Heard uses the eligible session history and an optional user-written note. It does not create inferred clinical memories. Replies can be short acknowledgements, reflections, a useful question, a summary, or a requested practical answer. Recent question frequency provides an additional pacing cue. Identity and capability claims must remain truthful.

## Evidence and next improvements

Thirteen synthetic evaluation cases cover the reported opening across several turns, reflections, corrections, rejected advice, continuity, direct requests, language, safety context, meaning, and summaries. Reports save actual replies and latency for human review. Passing API calls and deterministic tests do not establish counseling quality.

Further improvements should be evaluated on fresh conversations with appropriately qualified reviewers. Any future tuning dataset needs suitable consent, permission, review, and separate holdout examples. The configured [Gemini 3.1 Pro model does not support tuning](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-pro); this implementation improves context and conversation behavior without launching a training job.
