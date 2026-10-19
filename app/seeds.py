"""Deterministic, separated random-seed blocks.

Exploration/tuning and final evaluation must never share seeds, so a comparison
cannot be tuned against the same outcomes it later claims to validate. Evaluation
seeds are *reserved*: if results from a holdout block inform code changes, bump the
holdout version before making any new claim of validated improvement.

Given a user salt, `draft_seed(salt, block, holdout, index)` returns a stable seed.
All strategies and candidate selections inside one block share the block's seeds, so
their scenarios stay paired.
"""
EXPLORATION_BASE = 100_000
EVALUATION_BASE = 1_000_000
PRODUCTION_LAB_BASE = 7_000_000
ROSTER_EVAL_BASE = 9_000_000
HOLDOUT_STRIDE = 10_000
BLOCKS = ('exploration', 'evaluation', 'production_lab', 'roster_eval')


def block_base(block):
    if block not in BLOCKS:
        raise ValueError('Unknown seed block: ' + repr(block))
    return {'evaluation': EVALUATION_BASE, 'production_lab': PRODUCTION_LAB_BASE,
            'roster_eval': ROSTER_EVAL_BASE}.get(block, EXPLORATION_BASE)


def validate_block(block, holdout):
    if block not in BLOCKS:
        raise ValueError('seed_block must be one of ' + ', '.join(BLOCKS))
    if type(holdout) is not int or not 1 <= holdout <= 50:
        raise ValueError('holdout must be an integer 1-50')


def draft_seed(salt, block, holdout, index):
    validate_block(block, holdout)
    return int(salt) + block_base(block) + holdout * HOLDOUT_STRIDE + index * 7919


def world_seed(salt, block, holdout, draft_index, season_index):
    # Derived from the same block so worlds are paired across strategies at a given
    # (draft, season), and never collide with another block's streams.
    return draft_seed(salt, block, holdout, draft_index) + 2_000_003 + season_index * 1009
