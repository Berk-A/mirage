"""MIRAGE experiment harness.

A neutral orchestration + logging layer that drives the agent's *existing* pieces
(the Content studio renderer, the reaction reader, the rule guard, the API client)
across a matrix of message "form factors" and records what happened.

It writes no message content and encodes no persuasion of its own: every spec is a
controlled permutation of the dimensions in `form_factors`, rendered by the studio and
recorded by the harness. The point is measurement — how the generation cascade and (in
live mode) the target personas behave as the channel/objective/tone/link vary.
"""
