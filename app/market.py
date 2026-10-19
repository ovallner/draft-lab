"""Yahoo-first draft order, with a labeled monotone source-rank ADP fallback."""
from bisect import bisect_left


def apply_market_estimates(players):
    known = sorted((p for p in players if p['adp'] is not None), key=lambda p: p['rank'])
    # Pool adjacent violators: smooth the rank/ADP relationship without treating
    # source rank as the same numeric scale as ADP or inventing a Yahoo value.
    blocks = []
    for p in known:
        blocks.append({'ranks': [p['rank']], 'sum': p['adp'], 'count': 1})
        while len(blocks) > 1 and blocks[-2]['sum'] / blocks[-2]['count'] > blocks[-1]['sum'] / blocks[-1]['count']:
            b = blocks.pop()
            a = blocks[-1]
            a['ranks'].extend(b['ranks'])
            a['sum'] += b['sum']
            a['count'] += b['count']
    curve = sorted((r, b['sum'] / b['count']) for b in blocks for r in b['ranks'])
    ranks = [r for r, _ in curve]
    for p in players:
        estimate = p['adp']
        if estimate is None:
            if not curve:
                estimate = float(p['rank'])
            else:
                i = bisect_left(ranks, p['rank'])
                if i == 0:
                    estimate = max(1., curve[0][1] * p['rank'] / curve[0][0])
                elif i == len(curve):
                    estimate = curve[-1][1] + (p['rank'] - curve[-1][0]) * max(.5, curve[-1][1] / curve[-1][0])
                else:
                    lo, hi = curve[i - 1], curve[i]
                    estimate = lo[1] + (hi[1] - lo[1]) * (p['rank'] - lo[0]) / (hi[0] - lo[0])
        p['market_adp'] = round(estimate, 3)
        p['adp_estimated'] = p['adp'] is None


def market_key(player):
    return (player.get('market_adp', player.get('adp') or player['rank']), player['rank'], player['id'])
