"""
Recompute SettleStack's trophies from the record book's cleaned games.

SettleStack's own earned_achievements table is stale and polluted (see
AUDIT.md), so the Trophy Case is computed here instead, from the same games
every other number on the page uses: real group games only, test accounts
out, duplicate accounts merged, and nights cut on Chicago time.

Each rule follows the badge's own description. Where a description is loose,
the reading chosen is written next to the rule.

    compute(games, hosts) -> {achievement_id: {user_id: "YYYY-MM-DD"}}

`games` is chronological; each game is
    {"id", "night": "YYYY-MM-DD", "t": naive Chicago datetime,
     "seats": [{"uid", "net", "buy", "out"}], "txns": [(payer, payee, amount)]}
`hosts` maps night -> host user id, where SettleStack knows it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations

EPS = 0.005


def compute(games: list[dict], hosts: dict[str, int]) -> dict[int, dict[int, str]]:
    won: dict[int, dict[int, str]] = defaultdict(dict)

    def award(aid: int, uid: int, night: str):
        won[aid].setdefault(uid, night)   # first time the rule is met

    # ---- per-player running state, walked game by game ---------------------
    count = defaultdict(int)
    wins = defaultdict(int)
    firsts = defaultdict(int)
    mids = defaultdict(int)
    evens = defaultdict(int)
    run_w = defaultdict(int)
    run_l = defaultdict(int)
    cum = defaultdict(float)
    low = defaultdict(float)            # lowest lifetime running total so far
    shared = defaultdict(lambda: defaultdict(int))
    opps = defaultdict(set)
    weekend = defaultdict(lambda: defaultdict(int))
    pairs_seen: set[frozenset] = set()
    per_night_game = defaultdict(int)   # games so far in a night (for the late-night proxy)

    for g in games:
        seats, night = g["seats"], g["night"]
        nets = {s["uid"]: s["net"] for s in seats}
        ranked = sorted(seats, key=lambda s: -s["net"])
        hi, lo = ranked[0]["net"], ranked[-1]["net"]
        contested = hi - lo > EPS
        per_night_game[night] += 1
        nd = date.fromisoformat(night)

        # Group Loyalty (14): everyone at the table has shared a game with everyone else before.
        ids = [s["uid"] for s in seats]
        if all(frozenset(p) in pairs_seen for p in combinations(ids, 2)):
            for u in ids:
                award(14, u, night)
        pairs_seen.update(frozenset(p) for p in combinations(ids, 2))

        # The ATM (74) and The Glue (27) come from the settlement transfers.
        payees = defaultdict(set)
        linked = defaultdict(set)
        for pr, pe, _ in g["txns"]:
            payees[pr].add(pe)
            linked[pr].add(pe)
            linked[pe].add(pr)

        for s in seats:
            u, n = s["uid"], s["net"]
            count[u] += 1
            c = count[u]
            for aid, thr in [(1, 1), (2, 5), (3, 10), (4, 20), (5, 25), (6, 50), (7, 100)]:
                if c == thr:
                    award(aid, u, night)

            others = [o for o in ids if o != u]
            for o in others:
                shared[u][o] += 1
                opps[u].add(o)
            top_shared = max(shared[u].values())
            if top_shared >= 5:
                award(11, u, night)                       # Friendly Rival
            if top_shared >= 10:
                award(10, u, night)                       # Table Talk Champ
            if len(opps[u]) >= 10:
                award(12, u, night)                       # Group Guru
                award(13, u, night)                       # Diverse Dealer (same rule as 12 in SettleStack)

            if abs(n) <= EPS:
                evens[u] += 1
                award(15, u, night)                       # Debt Houdini: broke exactly even
                if evens[u] >= 3:
                    award(28, u, night)                   # Even Steven
            if n > EPS:
                wins[u] += 1
                if wins[u] >= 10:
                    award(18, u, night)                   # Profit Machine

            cum[u] += n
            low[u] = min(low[u], cum[u])
            # Debt Dynamo (17): 10 games in and the lifetime total has never been worse than -$50.
            if c >= 10 and low[u] >= -50 - EPS:
                award(17, u, night)
            # Comeback Kid (69): was $100+ down lifetime, now back above zero.
            if low[u] <= -100 and cum[u] > EPS:
                award(69, u, night)

            # streaks: a break-even game ends both
            if n > EPS:
                if run_l[u] >= 3:
                    award(23, u, night)                   # Cold Streak Survivor
                run_w[u] += 1
                run_l[u] = 0
            elif n < -EPS:
                run_l[u] += 1
                run_w[u] = 0
            else:
                run_w[u] = run_l[u] = 0
            if run_w[u] >= 3:
                award(22, u, night)                       # Victory Lap
            if run_w[u] >= 5:
                award(21, u, night)                       # Lucky Streak
            if run_l[u] >= 5:
                award(24, u, night)                       # Unlucky Streak

            if contested:
                if abs(n - hi) <= EPS:
                    firsts[u] += 1
                    # Master of Margins (34): won the game, less than $1 ahead of second place.
                    second = ranked[1]["net"]
                    if len(seats) > 1 and EPS < n - second < 1:
                        award(34, u, night)
                elif n > lo + EPS:
                    mids[u] += 1
                    if mids[u] >= 10:
                        award(30, u, night)               # Consistently Mediocre

            if s["buy"] > 0 and s["out"] <= 0.01:
                award(68, u, night)                       # Broke Boy
            if len(payees[u]) >= 3:
                award(74, u, night)                       # The ATM
            if others and set(others) <= linked[u]:
                award(27, u, night)                       # The Glue

            # Weekend Warrior (25): 3 games across one Fri-Sun weekend (poker night is Friday).
            if nd.weekday() in (4, 5, 6):
                fri = nd - timedelta(days=nd.weekday() - 4)
                weekend[u][fri] += 1
                if weekend[u][fri] >= 3:
                    award(25, u, night)

            # Late-Night Gambler (26): the game started after midnight. Only games started
            # live in the app carry a real clock time (it has seconds on it); imported and
            # Discord-logged games sit on a round placeholder like 9:00:00 pm. For those,
            # a night's 4th game stands in for "after midnight".
            live = g["t"].second or g["t"].microsecond
            if (live and 0 <= g["t"].hour < 6) or (not live and per_night_game[night] >= 4):
                award(26, u, night)

    # Participation Trophy (73): 10+ games and never once finished first.
    last_seen = {}
    for g in games:
        for s in g["seats"]:
            last_seen[s["uid"]] = g["night"]
    for u, c in count.items():
        if c >= 10 and firsts[u] == 0:
            award(73, u, last_seen[u])

    # ---- night-level trophies ---------------------------------------------
    by_night = defaultdict(list)
    for g in games:
        by_night[g["night"]].append(g)
    lifetime = defaultdict(float)
    for night in sorted(by_night):
        gs = by_night[night]
        tot = defaultdict(float)
        for g in gs:
            for s in g["seats"]:
                tot[s["uid"]] += s["net"]
        hi, lo = max(tot.values()), min(tot.values())
        # the all-time money leader going into tonight
        leader = max(lifetime, key=lifetime.get) if lifetime else None
        if hi - lo > EPS:
            for u, v in tot.items():
                if abs(v - hi) <= EPS:
                    award(72, u, night)                   # King of the Night
                    if leader in tot and u != leader:
                        award(70, u, night)               # Giant Slayer
            host = hosts.get(night)
            if host in tot and abs(tot[host] - lo) <= EPS:
                award(75, host, night)                    # Worst Host Ever
        last = gs[-1]
        lnets = [s["net"] for s in last["seats"]]
        if max(lnets) - min(lnets) > EPS:
            for s in last["seats"]:
                if abs(s["net"] - max(lnets)) <= EPS:
                    award(71, s["uid"], night)            # The Closer
        for u, v in tot.items():
            lifetime[u] += v

    # ---- hosting (only where SettleStack recorded a host) -------------------
    hosted = defaultdict(list)
    for night in sorted(hosts):
        if night in by_night:
            hosted[hosts[night]].append(night)
    for u, ns in hosted.items():
        if len(ns) >= 5:
            award(9, u, ns[4])                            # The Invite King
        if len(ns) >= 10:
            award(8, u, ns[9])                            # Host with the Most

    # ---- lifetime money: Debt King / Debt Mountain --------------------------
    got = defaultdict(float)
    paid = defaultdict(float)
    for g in games:
        for pr, pe, amt in g["txns"]:
            paid[pr] += amt
            got[pe] += amt
    last_night = games[-1]["night"] if games else None
    for u, v in got.items():
        if v > 500:
            award(19, u, last_night)
    for u, v in paid.items():
        if v > 500:
            award(20, u, last_night)

    # Equalizer (16) / Perfectly Balanced (29) need every player on the same net,
    # which a counted game can't have (it would be all zeros), so nobody earns them.
    return won
