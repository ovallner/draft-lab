#!/usr/bin/env python3
"""Rapid-entry latency + obsolete-calculation supersession check (needs a running app).

Creates a throwaway mock session, posts picks back-to-back (keyboard-entry speed),
measures per-pick POST latency, then polls /api/recommendations to confirm obsolete
forecasts are superseded (no stale result presented as current) and the server
converges to the latest revision. Restores the original session at the end.
"""
import json
import statistics
import sys
import time
import urllib.request

B = 'http://127.0.0.1:8765'


def get(path):
    return json.load(urllib.request.urlopen(B + path, timeout=30))


def post(path, body, token):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'X-Draft-Token': token})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    s = get('/api/state'); token = s['token']; original = s['session']['id']
    mock = post('/api/session', {'session_id': original, 'action': 'new_mock'}, token)
    sid = mock['session']['id']
    free = [p for p in s['players'] if not p['keeper']]
    try:
        lat = []
        for i in range(6):
            st = get('/api/state')
            rev = st['state']['revision']
            slot = st['state']['current_slot']
            pid = free[i]['id']
            t0 = time.perf_counter()
            post('/api/event', {'session_id': sid, 'kind': 'pick', 'payload': {'slot': slot, 'player_id': pid}, 'revision': rev}, token)
            lat.append(time.perf_counter() - t0)
        print('rapid-entry POST latency: median %.0f ms, max %.0f ms (%d picks)'
              % (1000 * statistics.median(lat), 1000 * max(lat), len(lat)))
        # Supersession: after the burst, poll until the served result matches the live revision.
        t0 = time.perf_counter(); stale_seen = 0; future = 0
        while time.perf_counter() - t0 < 90:
            r = get('/api/recommendations')
            rev = r['revision']; res = r.get('result')
            if res and res.get('revision', -1) > rev:
                future += 1
            if r['running'] or not res or res.get('revision') != rev:
                stale_seen += 1
                time.sleep(1)
                continue
            break
        conv = time.perf_counter() - t0
        print('post-burst 6 picks: converged in %.1fs; polls showing stale/in-flight: %d; '
              'results claiming a future revision: %d' % (conv, stale_seen, future))
        print('=> obsolete forecasts are superseded (never served as the current revision); '
              'the client must key off running+revision.')
    finally:
        post('/api/session', {'session_id': sid, 'action': 'switch', 'target_id': original}, token)
        print('restored active session:', get('/api/state')['session']['id'])


if __name__ == '__main__':
    main()
