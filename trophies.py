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

    expansion(games, hosts, by_night, award)

    # The Collector (122) / Trophy Hunter (123): count everything else earned, in date order.
    per_user = defaultdict(list)
    for aid, holders in won.items():
        for u, d in holders.items():
            per_user[u].append(d)
    for u, ds in per_user.items():
        ds.sort()
        if len(ds) >= 25:
            award(122, u, ds[24])
        if len(ds) >= 45:
            award(123, u, ds[44])
    return won


# The expansion set. 35-76 are SettleStack's own planned badges (names and rules
# from its seed file, never switched on for want of art); 100+ are new here, sized
# for $20 games. tone picks the chip colour on the generated art.
EXTRA = [
    # id, name, description, category, icon, tone
    (35, "The Lifer", "Play 250 games.", "Gameplay Milestones", "workspace_premium", "legend"),
    (36, "Felt for Life", "Play 500 games.", "Gameplay Milestones", "diamond", "legend"),
    (37, "Open Door Policy", "Host 25 poker nights.", "Gameplay Milestones", "door_open", "gold"),
    (38, "Slumlord", "Host 50 poker nights.", "Gameplay Milestones", "apartment", "legend"),
    (39, "Happy Anniversary", "Play a game within a week of your one-year mark at the table.", "Gameplay Milestones", "cake", "gold"),
    (40, "Where Were You?", "Return to the table after a 90+ day absence.", "Gameplay Milestones", "person_search", "gold"),
    (41, "Nemesis", "Play 20 games against the same opponent.", "Player Interaction", "swords", "shame"),
    (42, "Ride or Die", "Play 25 games with the same player.", "Player Interaction", "handshake", "gold"),
    (43, "Six Degrees", "Play with at least 25 different players.", "Player Interaction", "hub", "gold"),
    (44, "Heads Up", "Play a game with exactly 2 players.", "Player Interaction", "group", "gold"),
    (45, "Full House", "Play a game with 8 or more players.", "Player Interaction", "groups", "gold"),
    (46, "The Usual Suspects", "Play 3 games in a row with the exact same lineup.", "Player Interaction", "fingerprint", "gold"),
    (47, "Fresh Meat", "Be at the table for another player's very first game.", "Player Interaction", "kebab_dining", "shame"),
    (48, "Whale", "Win more than $200 in a single game.", "Debt and Balance", "waves", "legend"),
    (49, "Sleeps with the Fishes", "Lose more than $200 in a single game.", "Debt and Balance", "set_meal", "shame"),
    (50, "In the Black", "Hold a lifetime positive balance across 10 or more games.", "Debt and Balance", "trending_up", "money"),
    (51, "In the Red", "Hold a lifetime negative balance across 10 or more games.", "Debt and Balance", "trending_down", "shame"),
    (52, "The Bank", "Finish as the biggest winner at the table in 10 games.", "Debt and Balance", "account_balance", "money"),
    (53, "Loan Shark", "Walk away owed money in 25 games.", "Debt and Balance", "phishing", "money"),
    (54, "Round Number", "Finish a game up or down an exact multiple of $50.", "Debt and Balance", "adjust", "gold"),
    (55, "Pennies on the Dollar", "Win a game by less than $5.", "Debt and Balance", "savings", "money"),
    (56, "On Fire", "Win 7 games in a row.", "Streak Achievements", "local_fire_department", "fire"),
    (57, "Untouchable", "Win 10 games in a row.", "Streak Achievements", "shield", "legend"),
    (58, "Cold as Ice", "Lose 7 games in a row.", "Streak Achievements", "ac_unit", "ice"),
    (59, "The Phoenix", "Win a game right after losing 5 or more in a row.", "Streak Achievements", "flare", "fire"),
    (60, "Rollercoaster", "Alternate win, loss, win, loss for 6 straight games.", "Streak Achievements", "ssid_chart", "gold"),
    (61, "Night Owl", "Play 3 games that kick off after midnight.", "Special Circumstances", "bedtime", "night"),
    (62, "New Year, New Debt", "Play a game on January 1st.", "Special Circumstances", "celebration", "gold"),
    (63, "Festive Felt", "Play a game on a major holiday.", "Special Circumstances", "redeem", "gold"),
    (64, "Wooden Spoon", "Finish dead last in 5 games.", "Special Circumstances", "soup_kitchen", "shame"),
    (65, "Bridesmaid", "Finish in 2nd place in 5 games.", "Special Circumstances", "looks_two", "gold"),
    (66, "The Sweep", "Win a game where every other player pays you directly.", "Special Circumstances", "cleaning_services", "money"),
    (67, "Photo Finish", "Tie another player for the top spot.", "Special Circumstances", "photo_camera", "gold"),
    (76, "Gracious Host", "Host your first poker night.", "Gameplay Milestones", "home", "gold"),
    (100, "Double Up", "Cash out at least double your buy-in.", "Debt and Balance", "keyboard_double_arrow_up", "money"),
    (101, "Triple Threat", "Cash out at least triple your buy-in.", "Debt and Balance", "looks_3", "legend"),
    (102, "Big Night", "Win $40 or more across a single night.", "Debt and Balance", "paid", "money"),
    (103, "Rough Night", "Lose $40 or more across a single night.", "Debt and Balance", "thunderstorm", "shame"),
    (104, "Flawless", "Finish up in every game of a night (3+ games).", "Streak Achievements", "stars", "legend"),
    (105, "Donor of the Night", "Finish down in every game of a night (3+ games).", "Streak Achievements", "volunteer_activism", "shame"),
    (106, "Back-to-Back", "Win the night on two poker nights in a row.", "Streak Achievements", "military_tech", "legend"),
    (107, "Hat Trick", "Finish first in 3 games in one night.", "Streak Achievements", "sports_hockey", "fire"),
    (108, "Iron Man", "Show up for 5 poker nights in a row.", "Gameplay Milestones", "fitness_center", "gold"),
    (109, "Night Shift", "Play every game of a 4-game night.", "Gameplay Milestones", "schedule", "night"),
    (110, "Century Club", "Reach +$100 lifetime.", "Debt and Balance", "price_check", "money"),
    (111, "The Summit", "Sit at #1 on the all-time money list after any night.", "Debt and Balance", "landscape", "legend"),
    (112, "Beginner's Luck", "Finish up in your very first game.", "Gameplay Milestones", "auto_awesome", "gold"),
    (113, "Welcome Tax", "Finish down in your very first game.", "Gameplay Milestones", "receipt_long", "shame"),
    (114, "Pay Day", "Collect from 3 or more different players in a single game.", "Debt and Balance", "payments", "money"),
    (115, "Mr. Consistent", "Finish within $3 of even in 5 straight games.", "Special Circumstances", "balance", "gold"),
    (116, "Bounce Back", "Win the night right after finishing last on your previous night.", "Streak Achievements", "replay", "fire"),
    (117, "Snack Money", "Lose less than $1 in a game.", "Debt and Balance", "cookie", "shame"),
    (118, "Four Seasons", "Play in winter, spring, summer and fall.", "Gameplay Milestones", "eco", "gold"),
    (119, "Heartbreaker", "Finish second, less than $1 behind the winner.", "Special Circumstances", "heart_broken", "shame"),
    (120, "Opening Act", "Win the first game of a night.", "Special Circumstances", "theater_comedy", "gold"),
    (121, "Kingslayer", "Finish ahead of the all-time money leader in 10 games.", "Player Interaction", "chess", "fire"),
    (122, "The Collector", "Earn 25 different trophies.", "Gameplay Milestones", "collections_bookmark", "gold"),
    (123, "Trophy Hunter", "Earn 45 different trophies.", "Gameplay Milestones", "emoji_events", "legend"),
]

HOLIDAYS = {(1, 1), (2, 14), (3, 17), (7, 4), (10, 31), (12, 24), (12, 25), (12, 31)}


def _holiday(d: date) -> bool:
    if (d.month, d.day) in HOLIDAYS:
        return True
    first_thu = 1 + (3 - d.replace(day=1).weekday()) % 7
    return d.month == 11 and d.day == first_thu + 21      # Thanksgiving


def expansion(games, hosts, by_night, award):
    nights = sorted(by_night)
    # each player's seats in order, with placing and the table
    seats = defaultdict(list)
    for g in games:
        ranked = sorted(g["seats"], key=lambda s: -s["net"])
        hi, lo = ranked[0]["net"], ranked[-1]["net"]
        contested = hi - lo > EPS
        nets = sorted((s["net"] for s in g["seats"]), reverse=True)
        n_top = sum(1 for x in nets if abs(x - hi) <= EPS)
        live = g["t"].second or g["t"].microsecond
        game_no = by_night[g["night"]].index(g) + 1
        late = (live and 0 <= g["t"].hour < 6) or (not live and game_no >= 4)
        for s in g["seats"]:
            n = s["net"]
            first = contested and abs(n - hi) <= EPS
            # second place: best net strictly below the top
            below = [x for x in nets if x < hi - EPS]
            second = contested and len(g["seats"]) >= 3 and below and abs(n - below[0]) <= EPS
            seats[s["uid"]].append({
                "g": g, "s": s, "n": n, "night": g["night"], "first": first, "second": second,
                "last": contested and abs(n - lo) <= EPS, "tie_top": first and n_top >= 2,
                "gap_to_second": (hi - below[0]) if first and below else None,
                "gap_to_first": (hi - n) if second else None,
                "others": [o["uid"] for o in g["seats"] if o["uid"] != s["uid"]],
                "late": late, "game_no": game_no,
            })
    debut = {u: es[0]["g"]["id"] for u, es in seats.items()}

    for u, es in seats.items():
        n_games = len(es)
        for aid, thr in [(35, 250), (36, 500)]:
            if n_games >= thr:
                award(aid, u, es[thr - 1]["night"])
        first_night = date.fromisoformat(es[0]["night"])
        shared = defaultdict(int)
        opps = set()
        run_w = run_l = alt = 0
        prev = None
        calm = 0
        cum = 0.0
        tally = defaultdict(int)
        seasons = set()
        for i, e in enumerate(es):
            g, n, night = e["g"], e["n"], e["night"]
            d = date.fromisoformat(night)
            if i and (d - date.fromisoformat(es[i - 1]["night"])).days >= 90:
                award(40, u, night)                                  # Where Were You?
            yrs = d.year - first_night.year
            for k in (yrs - 1, yrs, yrs + 1):
                if k >= 1:
                    try:
                        mark = first_night.replace(year=first_night.year + k)
                    except ValueError:
                        mark = first_night.replace(year=first_night.year + k, day=28)
                    if abs((d - mark).days) <= 7:
                        award(39, u, night)                          # Happy Anniversary
            for o in e["others"]:
                shared[o] += 1
                opps.add(o)
            if shared and max(shared.values()) >= 20:
                award(41, u, night)                                  # Nemesis
            if shared and max(shared.values()) >= 25:
                award(42, u, night)                                  # Ride or Die
            if len(opps) >= 25:
                award(43, u, night)                                  # Six Degrees
            size = len(e["others"]) + 1
            if size == 2:
                award(44, u, night)                                  # Heads Up
            if size >= 8:
                award(45, u, night)                                  # Full House
            if i >= 2 and len({frozenset(x["others"] + [u]) for x in es[i - 2:i + 1]}) == 1:
                award(46, u, night)                                  # The Usual Suspects
            if any(debut.get(o) == g["id"] for o in e["others"]):
                award(47, u, night)                                  # Fresh Meat
            if n > 200:
                award(48, u, night)                                  # Whale
            if n < -200:
                award(49, u, night)                                  # Sleeps with the Fishes
            if abs(n) > EPS and abs(round(n, 2)) % 50 == 0:
                award(54, u, night)                                  # Round Number
            if e["first"]:
                tally["first"] += 1
                if tally["first"] >= 10:
                    award(52, u, night)                              # The Bank
                if e["gap_to_second"] is not None and e["gap_to_second"] < 5:
                    award(55, u, night)                              # Pennies on the Dollar
                if e["game_no"] == 1:
                    award(120, u, night)                             # Opening Act
            if n > EPS:
                tally["up"] += 1
                if tally["up"] >= 25:
                    award(53, u, night)                              # Loan Shark
            if e["last"]:
                tally["last"] += 1
                if tally["last"] >= 5:
                    award(64, u, night)                              # Wooden Spoon
            if e["second"]:
                tally["second"] += 1
                if tally["second"] >= 5:
                    award(65, u, night)                              # Bridesmaid
                if e["gap_to_first"] is not None and e["gap_to_first"] < 1:
                    award(119, u, night)                             # Heartbreaker
            if e["tie_top"]:
                award(67, u, night)                                  # Photo Finish
            if e["late"]:
                tally["late"] += 1
                if tally["late"] >= 3:
                    award(61, u, night)                              # Night Owl
            if d.month == 1 and d.day == 1:
                award(62, u, night)                                  # New Year, New Debt
            if _holiday(d):
                award(63, u, night)                                  # Festive Felt
            # streaks
            if n > EPS:
                if run_l >= 5:
                    award(59, u, night)                              # The Phoenix
                run_w, run_l = run_w + 1, 0
            elif n < -EPS:
                run_w, run_l = 0, run_l + 1
            else:
                run_w = run_l = 0
            if run_w >= 7:
                award(56, u, night)                                  # On Fire
            if run_w >= 10:
                award(57, u, night)                                  # Untouchable
            if run_l >= 7:
                award(58, u, night)                                  # Cold as Ice
            sign = 1 if n > EPS else -1 if n < -EPS else 0
            alt = alt + 1 if sign and prev and sign != prev else (1 if sign else 0)
            prev = sign or None
            if alt >= 6:
                award(60, u, night)                                  # Rollercoaster
            # money
            s = e["s"]
            if s["buy"] > 0 and s["out"] >= 2 * s["buy"] - EPS:
                award(100, u, night)                                 # Double Up
            if s["buy"] > 0 and s["out"] >= 3 * s["buy"] - EPS:
                award(101, u, night)                                 # Triple Threat
            cum += n
            if cum >= 100 - EPS:
                award(110, u, night)                                 # Century Club
            if i == 0 and n > EPS:
                award(112, u, night)                                 # Beginner's Luck
            if i == 0 and n < -EPS:
                award(113, u, night)                                 # Welcome Tax
            if -1 < n < -EPS:
                award(117, u, night)                                 # Snack Money
            calm = calm + 1 if abs(n) <= 3 else 0
            if calm >= 5:
                award(115, u, night)                                 # Mr. Consistent
            payers = {pr for pr, pe, _ in g["txns"] if pe == u}
            if len(payers) >= 3:
                award(114, u, night)                                 # Pay Day
            if len(e["others"]) >= 2 and set(e["others"]) <= payers and e["first"]:
                award(66, u, night)                                  # The Sweep
            seasons.add({12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2}.get(d.month, 3))
            if len(seasons) == 4:
                award(118, u, night)                                 # Four Seasons
        if n_games >= 10:
            total = sum(e["n"] for e in es)
            if total > EPS:
                award(50, u, es[-1]["night"])                        # In the Black
            if total < -EPS:
                award(51, u, es[-1]["night"])                        # In the Red

    # ---- night-level ---------------------------------------------------------
    lifetime = defaultdict(float)
    kings_prev: set = set()
    attended_run = defaultdict(int)
    last_place_prev: dict = {}          # player -> were they last on their previous night
    ahead_of_leader = defaultdict(int)
    for night in nights:
        gs = by_night[night]
        tot = defaultdict(float)
        played = defaultdict(list)
        for g in gs:
            for s in g["seats"]:
                tot[s["uid"]] += s["net"]
                played[s["uid"]].append(s["net"])
        hi, lo = max(tot.values()), min(tot.values())
        kings = {u for u, v in tot.items() if abs(v - hi) <= EPS} if hi - lo > EPS else set()
        lasts = {u for u, v in tot.items() if abs(v - lo) <= EPS} if hi - lo > EPS else set()
        leader = max(lifetime, key=lifetime.get) if lifetime else None
        for g in gs:
            if leader is not None:
                lnet = next((s["net"] for s in g["seats"] if s["uid"] == leader), None)
                if lnet is not None:
                    for s in g["seats"]:
                        if s["uid"] != leader and s["net"] > lnet + EPS:
                            ahead_of_leader[s["uid"]] += 1
                            if ahead_of_leader[s["uid"]] >= 10:
                                award(121, s["uid"], night)          # Kingslayer
        for u, v in tot.items():
            if v >= 40 - EPS:
                award(102, u, night)                                 # Big Night
            if v <= -40 + EPS:
                award(103, u, night)                                 # Rough Night
            ns = played[u]
            if len(ns) >= 3 and all(x > EPS for x in ns):
                award(104, u, night)                                 # Flawless
            if len(ns) >= 3 and all(x < -EPS for x in ns):
                award(105, u, night)                                 # Donor of the Night
            if len(gs) >= 4 and len(ns) == len(gs):
                award(109, u, night)                                 # Night Shift
            firsts = sum(1 for g in gs for s in g["seats"]
                         if s["uid"] == u and s["net"] > EPS and
                         abs(s["net"] - max(x["net"] for x in g["seats"])) <= EPS)
            if firsts >= 3:
                award(107, u, night)                                 # Hat Trick
            if u in kings and last_place_prev.get(u):
                award(116, u, night)                                 # Bounce Back
            last_place_prev[u] = u in lasts
        for u in kings & kings_prev:
            award(106, u, night)                                     # Back-to-Back
        kings_prev = kings
        for u in set(attended_run) | set(tot):
            attended_run[u] = attended_run[u] + 1 if u in tot else 0
            if attended_run[u] >= 5:
                award(108, u, night)                                 # Iron Man
        for u, v in tot.items():
            lifetime[u] += v
        top = max(lifetime, key=lifetime.get)
        award(111, top, night)                                       # The Summit

    hosted = defaultdict(list)
    for night in sorted(hosts):
        if night in by_night:
            hosted[hosts[night]].append(night)
    for u, ns in hosted.items():
        award(76, u, ns[0])                                          # Gracious Host
        if len(ns) >= 25:
            award(37, u, ns[24])                                     # Open Door Policy
        if len(ns) >= 50:
            award(38, u, ns[49])                                     # Slumlord
