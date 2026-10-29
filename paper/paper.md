## Abstract

I implemented a bounded observation-memory policy for ARC-AGI-3. It records complete commands and their observed effects, then uses that evidence to order further experiments. A separate variant searches the recorded transition graph for nearby states with untested commands. The contribution is an inspectable implementation and a specified comparison protocol, rather than a new planning principle. Kaggle evaluated the current transition-memory policy and displayed a public score of 0.21. That single-policy result does not establish an improvement from memory or planning.

## Intro

[ARC-AGI-3](https://arxiv.org/abs/2603.24621) presents unfamiliar interactive environments in which an agent must learn how to act from observations and feedback. It makes exploration itself part of the problem. Repeating a command without retaining its effect can spend an action budget without adding useful evidence.

I ask whether retaining complete commands and their outcomes can improve a simple explorer, and whether a short planner adds anything beyond that memory. A small policy with explicit capacities and decision records makes these questions easier to inspect, while exposing where a visible-state representation fails.

## Prior work

Learning a transition model during interaction is established work. [Sutton's Dyna architectures](https://proceedings.neurips.cc/paper/1990/hash/d9fc5b73a8d78fad3d6dffe419384e70-Abstract.html) combine interaction with planning over a learned model. This implementation also stores an empirical transition model, but learns no value function and uses no pretrained model. Its narrower purpose is to make candidate generation, command ordering and limited graph search explicit enough to compare.

## Approach

The decision policy represents a visible state with the final rendered image, observed game state, completed-level count and available actions. A hash of those fields identifies the state. Game identifiers and privileged game data are excluded from this representation and action ranking. The gateway still uses identifiers for environment discovery, routing and logs.

For a `NOT_PLAYED` or `GAME_OVER` observation, the command pool contains only RESET. A `WIN` observation has an empty pool. Otherwise it contains legal non-click actions and selected click coordinates. Click candidates combine a coarse grid, representatives of same-color components and deterministic seeded samples. The pool holds at most 64 complete commands. Different coordinates are different experiments, even when they share an action identifier.

A fresh reasoner is created for each game. It retains at most 500 states and 500 transition edges within that game, with no memory transfer between games. A state-command record tracks attempts, observed outcomes, unchanged observations, game-over outcomes, level progress and returns to visited states. At capacity, new admissions are skipped; retained records are not evicted. The runner copies observations before acting so that mutable frame reuse cannot overwrite the before state.

The transition-memory policy first tries untested commands, balancing action types and then commands within a type. After trying the pool, it ranks commands using observed death, progress, unchanged-observation and revisit rates. Ties use the balancing rule and seeded choice.

The loop permits at most 500 policy decisions per game, stops on a win and checks a cooperative ten-second play limit between decisions. Initialization and scorecard closure are outside that clock. The toolkit's initial RESET is outside the policy decision count; subsequent resets are policy decisions when the observed state requires them. The seed controls policy choices, not hidden game randomness.

The planning variant searches retained transitions with one observed destination per command. It seeks a retained state with untested commands, to depth two and with at most 64 inspected edges per decision. One observed destination does not establish determinism. The evaluated policy is `transition_memory`, with planning disabled.

The comparison protocol specifies uniform exploration, least-visited exploration, selection from the fixed candidate pool, transition memory and shallow planning. The candidate-pool baseline chooses an action type uniformly, then a command uniformly within that type. Comparing the first and third policies tests the candidate pool; comparing the third and fourth tests the combined memory ordering, balancing and outcome preferences; comparing the fourth and fifth tests planning. The protocol cannot separate the individual parts of the memory contrast and has not been evaluated here at reportable scale.

## Results

Source repository: [jskinner215/arc-transition-memory](https://github.com/jskinner215/arc-transition-memory).

On October 29, 2026, Kaggle marked the competition submission Succeeded and displayed Public Score 0.21 for [the evaluated notebook, Version 2](https://www.kaggle.com/code/jordanskinner313/arc-transition-memory-baseline?scriptVersionId=363475807), script version 363475807. I report the value as displayed, without a percentage conversion. This is the current transition-memory policy's result; no scored five-policy ablation or per-game outcomes are reported. The aggregate score cannot identify which mechanism contributed to it. No private final score or rank is reported.

Separately, an ordinary CPU commit passed offline installation and runtime preflight in 38.5 seconds. It executed zero games and reported `dry_run`; that duration is a setup result, not the scored run's runtime. Wrapper v3 used the installed CPython 3.12.3 child interpreter and 31 hash-locked dependency wheels. The preserved public-development checkpoint requires CPython 3.12.13 exactly, so this setup check does not establish checkpoint reproduction. No training-set performance is included.

## Conclusion

The contribution is a bounded, inspectable implementation and a specified comparison protocol, accompanied by one current-policy public score. Decisions can be traced to complete commands and retained transition evidence.

Memory can affect experiment ordering only when retained visible states recur. Exact image matching can split semantically equivalent observations or merge identical images with different hidden states. The policy may miss useful clicks outside its pool, and fixed capacities can exclude later evidence. Short planning can miss longer useful paths and cannot resolve hidden state. These limits matter beyond this benchmark whenever an interactive explorer relies on a bounded visible-state model. Whether these controls improve exploration remains unanswered by the single-policy result and requires a comparative evaluation.
