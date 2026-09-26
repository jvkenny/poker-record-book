#!/usr/bin/env python3
"""
Build data.json for the poker record book from SettleStack.

    build.py                      # read the local snapshot db (ss_snapshot)
    build.py --dsn "dbname=foo"   # any Postgres holding a SettleStack dump
    build.py --live               # read production through settlestack_db

Refreshing from a backup:

    dropdb --if-exists ss_snapshot && createdb ss_snapshot
    psql -q ss_snapshot -f ~/dev/settle-stack/db_backups/<latest>_auto.sql
    ../settle-stack/.venv/bin/python build.py

Everything the page shows is computed here; index.html only draws it.
A "night" is the Chicago date six hours before a game started, so the
1 a.m. game belongs to the night it was played.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {k.strip(): v for k, v in json.loads((HERE / "names.json").read_text()).items()
         if not k.startswith("_")}
REGULAR_MIN_GAMES = 8   # who gets a line in head-to-head and the colour slots
EPS = 0.005
# A game counts toward the record book only if it looks like a real group game:
# three or more players, somebody actually won, and the money balances.
# That drops the heads-up test games and the day-one game that created $25.
MIN_PLAYERS = 3
MAX_IMBALANCE = 1.00


def connect(args):
    if args.live:
        sys.path.insert(0, str(Path.home() / "dev/settle-stack/agent"))
        import settlestack_db as ss
        return ss._conn()
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(args.dsn, row_factory=dict_row)


def r2(v: float) -> float:
    return round(float(v) + 0.0, 2)


def streaks(nets: list[float]) -> tuple[int, int, int]:
    """(longest win streak, longest losing streak, current: +wins / -losses)."""
    best_w = best_l = w = l = 0
    for n in nets:
        w = w + 1 if n > EPS else 0
        l = l + 1 if n < -EPS else 0
        best_w, best_l = max(best_w, w), max(best_l, l)
    cur = 0
    for n in reversed(nets):
        if n > EPS and cur >= 0:
            cur += 1
        elif n < -EPS and cur <= 0:
            cur -= 1
        else:
            break
    return best_w, best_l, cur


def build(conn) -> dict:
    with conn as c:
        users = {r["id"]: r["username"].strip() for r in c.execute("SELECT id, username FROM users")}
        rows = c.execute("""
            SELECT g.id AS game_id, g.default_buy_in, g.transactions,
                   (g.start_time AT TIME ZONE 'America/Chicago') AS t,
                   ((g.start_time AT TIME ZONE 'America/Chicago') - interval '6 hours')::date AS night,
                   COALESCE(g.seq, 0) AS seq, g.session_id,
                   p.user_id, p.buy_in, p.final_balance
            FROM players p JOIN games g ON g.id = p.game_id
            WHERE g.start_time IS NOT NULL AND g.status = 'completed'
            ORDER BY g.start_time, COALESCE(g.seq, 0), g.id""").fetchall()
        hosts = {r["session_id"]: r["host_id"] for r in c.execute(
            "SELECT id AS session_id, host_id FROM sessions WHERE host_id IS NOT NULL")}
        badge_rows = c.execute("""
            SELECT a.id, a.name, a.description, a.category, a.image_path,
                   e.user_id, e.date_earned
            FROM achievements a LEFT JOIN earned_achievements e ON e.achievement_id = a.id
            ORDER BY a.id, e.date_earned""").fetchall()

    def name(uid: int) -> str:
        u = users.get(uid, f"#{uid}")
        return NAMES.get(u, u)

    # ---- games -----------------------------------------------------------
    games: dict[int, dict] = {}
    for r in rows:
        g = games.setdefault(r["game_id"], {
            "id": r["game_id"], "night": r["night"].isoformat(), "t": r["t"],
            "session": r["session_id"], "default": float(r["default_buy_in"] or 20),
            "txns": r["transactions"] or [], "seats": []})
        buy, out = float(r["buy_in"]), float(r["final_balance"])
        rebuys = max(0, round((buy - g["default"]) / g["default"])) if g["default"] else 0
        g["seats"].append({"uid": r["user_id"], "buy": r2(buy), "out": r2(out),
                           "net": r2(out - buy), "rebuys": rebuys, "bust": out <= 0.01})
    def real(g):
        nets = [s["net"] for s in g["seats"]]
        return (len(nets) >= MIN_PLAYERS and any(abs(n) > EPS for n in nets)
                and abs(sum(nets)) <= MAX_IMBALANCE)
    dropped = sorted(gid for gid, g in games.items() if not real(g))
    games = {gid: g for gid, g in games.items() if real(g)}
    order = list(games)  # already chronological

    # number games within their night
    per_night = defaultdict(int)
    for gid in order:
        g = games[gid]
        per_night[g["night"]] += 1
        g["n"] = per_night[g["night"]]
        g["seats"].sort(key=lambda s: -s["net"])
        g["pot"] = r2(sum(s["buy"] for s in g["seats"]))
        g["spread"] = r2(g["seats"][0]["net"] - g["seats"][-1]["net"])

    # ---- nights ----------------------------------------------------------
    nights: dict[str, dict] = {}
    for gid in order:
        g = games[gid]
        nt = nights.setdefault(g["night"], {"date": g["night"], "games": [], "nets": defaultdict(float),
                                            "played": defaultdict(int), "pot": 0.0, "host": None})
        nt["games"].append(gid)
        nt["pot"] += g["pot"]
        if g["session"] in hosts and not nt["host"]:
            nt["host"] = hosts[g["session"]]
        for s in g["seats"]:
            nt["nets"][s["uid"]] += s["net"]
            nt["played"][s["uid"]] += 1
    night_order = sorted(nights)

    # ---- per player --------------------------------------------------------
    uids = sorted({s["uid"] for g in games.values() for s in g["seats"]})
    seats_by = defaultdict(list)
    for gid in order:
        g = games[gid]
        for rank, s in enumerate(g["seats"], 1):
            seats_by[s["uid"]].append({**s, "game": gid, "night": g["night"], "n": g["n"],
                                       "rank": rank, "of": len(g["seats"])})

    players = []
    for uid in uids:
        ss = seats_by[uid]
        nets = [s["net"] for s in ss]
        night_nets = [(d, r2(nights[d]["nets"][uid])) for d in night_order if uid in nights[d]["nets"]]
        nn = [v for _, v in night_nets]
        bw, bl, cur = streaks(nets)
        nbw, nbl, ncur = streaks(nn)
        best = max(ss, key=lambda s: s["net"])
        worst = min(ss, key=lambda s: s["net"])
        bought = sum(s["buy"] for s in ss)
        players.append({
            "id": uid, "name": name(uid), "username": users.get(uid, ""),
            "games": len(ss), "nights": len(night_nets),
            "net": r2(sum(nets)), "avg": r2(sum(nets) / len(nets)),
            "won": sum(1 for n in nets if n > EPS), "lost": sum(1 for n in nets if n < -EPS),
            "firsts": sum(1 for s in ss if s["rank"] == 1 and s["net"] > EPS),
            "lasts": sum(1 for s in ss if s["rank"] == s["of"] and s["net"] < -EPS),
            "bought": r2(bought), "roi": r2(100 * sum(nets) / bought) if bought else 0,
            "rebuys": sum(s["rebuys"] for s in ss), "busts": sum(1 for s in ss if s["bust"]),
            "best": {"net": best["net"], "night": best["night"], "game": best["game"]},
            "worst": {"net": worst["net"], "night": worst["night"], "game": worst["game"]},
            "best_night": max(night_nets, key=lambda x: x[1]),
            "worst_night": min(night_nets, key=lambda x: x[1]),
            "nights_won": sum(1 for v in nn if v > EPS),
            "win_streak": bw, "lose_streak": bl, "streak": cur,
            "night_win_streak": nbw, "night_lose_streak": nbl,
            "first": ss[0]["night"], "last": ss[-1]["night"],
            "debut": {"night": ss[0]["night"], "net": ss[0]["net"]},
            "series": [[s["game"], s["net"]] for s in ss],
            "sd": r2((sum((n - sum(nets) / len(nets)) ** 2 for n in nets) / len(nets)) ** 0.5),
        })
    players.sort(key=lambda p: -p["net"])
    pname = {p["id"]: p["name"] for p in players}

    regulars = sorted([p for p in players if p["games"] >= REGULAR_MIN_GAMES], key=lambda p: -p["games"])
    reg_ids = [p["id"] for p in regulars]

    # ---- head to head (regulars): shared games, who finished with more ----
    h2h = {a: {b: [0, 0] for b in reg_ids} for a in reg_ids}  # [ahead, shared]
    for gid in order:
        seated = {s["uid"]: s["net"] for s in games[gid]["seats"] if s["uid"] in h2h}
        for a, b in combinations(seated, 2):
            h2h[a][b][1] += 1
            h2h[b][a][1] += 1
            if seated[a] > seated[b] + EPS:
                h2h[a][b][0] += 1
            elif seated[b] > seated[a] + EPS:
                h2h[b][a][0] += 1

    # ---- money flow: settlement transfers, payer -> payee -----------------
    paid = defaultdict(float)
    for g in games.values():
        for t in g["txns"]:
            try:
                paid[(t["payer_id"], t["payee_id"])] += float(t["amount"])
            except (KeyError, TypeError, ValueError):
                continue
    flows = sorted(([pr, pe, r2(v)] for (pr, pe), v in paid.items() if v > 0.009), key=lambda x: -x[2])
    rivals = []
    for p in players:
        out = {pe: v for (pr, pe), v in paid.items() if pr == p["id"]}
        inc = {pr: v for (pr, pe), v in paid.items() if pe == p["id"]}
        nem = max(out.items(), key=lambda kv: kv[1], default=None)
        atm = max(inc.items(), key=lambda kv: kv[1], default=None)
        rivals.append({"id": p["id"],
                       "nemesis": [nem[0], r2(nem[1])] if nem else None,
                       "atm": [atm[0], r2(atm[1])] if atm else None,
                       "paid": r2(sum(out.values())), "received": r2(sum(inc.values()))})

    # ---- records -----------------------------------------------------------
    all_seats = [s for ss in seats_by.values() for s in ss]
    night_seats = [(d, uid, r2(v)) for d in night_order for uid, v in nights[d]["nets"].items()]

    def seat_rec(s):
        return {"who": s["uid"], "value": s["net"], "night": s["night"], "game": s["game"]}

    top_games = sorted(all_seats, key=lambda s: -s["net"])
    top_nights = sorted(night_seats, key=lambda x: -x[2])
    by = lambda key, rev=True: sorted(players, key=lambda p: p[key], reverse=rev)
    qualified = [p for p in players if p["games"] >= REGULAR_MIN_GAMES]
    biggest_pot = max(games.values(), key=lambda g: g["pot"])
    closest = min((g for g in games.values() if len(g["seats"]) >= 4), key=lambda g: g["spread"])
    widest = max(games.values(), key=lambda g: g["spread"])
    biggest_night = max(nights.values(), key=lambda n: n["pot"])
    longest_night = max(nights.values(), key=lambda n: len(n["games"]))
    rec = [
        {"k": "Biggest single-game win", "icon": "💰", **seat_rec(top_games[0]), "fmt": "money"},
        {"k": "Biggest single-game loss", "icon": "🔥", **seat_rec(top_games[-1]), "fmt": "money"},
        {"k": "Best night", "icon": "🌙", "who": top_nights[0][1], "value": top_nights[0][2],
         "night": top_nights[0][0], "fmt": "money"},
        {"k": "Worst night", "icon": "🕳️", "who": top_nights[-1][1], "value": top_nights[-1][2],
         "night": top_nights[-1][0], "fmt": "money"},
        {"k": "Longest winning streak", "icon": "📈", "who": by("win_streak")[0]["id"],
         "value": by("win_streak")[0]["win_streak"], "fmt": "games"},
        {"k": "Longest losing streak", "icon": "📉", "who": by("lose_streak")[0]["id"],
         "value": by("lose_streak")[0]["lose_streak"], "fmt": "games"},
        {"k": "Most games played", "icon": "🪑", "who": by("games")[0]["id"],
         "value": by("games")[0]["games"], "fmt": "games"},
        {"k": "Most last-place finishes", "icon": "🧻", "who": by("lasts")[0]["id"],
         "value": by("lasts")[0]["lasts"], "fmt": "count"},
        {"k": "Most nights won", "icon": "👑", "who": by("nights_won")[0]["id"],
         "value": by("nights_won")[0]["nights_won"], "fmt": "count"},
        {"k": "Most busts, all time", "icon": "💀", "who": by("busts")[0]["id"],
         "value": by("busts")[0]["busts"], "fmt": "count"},
        {"k": "Best win rate (8+ games)", "icon": "🎯",
         "who": max(qualified, key=lambda p: p["won"] / p["games"])["id"],
         "value": round(100 * max(p["won"] / p["games"] for p in qualified)), "fmt": "pct"},
        {"k": "Best average per game (8+)", "icon": "📊",
         "who": max(qualified, key=lambda p: p["avg"])["id"],
         "value": max(p["avg"] for p in qualified), "fmt": "money"},
        {"k": "Most volatile (8+ games)", "icon": "🎢",
         "who": max(qualified, key=lambda p: p["sd"])["id"],
         "value": max(p["sd"] for p in qualified), "fmt": "sd"},
        {"k": "Most game wins (1st place)", "icon": "🥇", "who": by("firsts")[0]["id"],
         "value": by("firsts")[0]["firsts"], "fmt": "count"},
        {"k": "Biggest pot", "icon": "🏦", "value": biggest_pot["pot"], "night": biggest_pot["night"],
         "game": biggest_pot["id"], "fmt": "pot", "note": f"{len(biggest_pot['seats'])} players"},
        {"k": "Biggest night (money in play)", "icon": "🎰", "value": r2(biggest_night["pot"]),
         "night": biggest_night["date"], "fmt": "pot", "note": f"{len(biggest_night['games'])} games"},
        {"k": "Longest night", "icon": "⏰", "value": len(longest_night["games"]),
         "night": longest_night["date"], "fmt": "games", "note": "games in one night"},
        {"k": "Closest game (4+ players)", "icon": "🤏", "value": closest["spread"],
         "night": closest["night"], "game": closest["id"], "fmt": "spread",
         "note": "first to last"},
        {"k": "Widest game", "icon": "↔️", "value": widest["spread"], "night": widest["night"],
         "game": widest["id"], "fmt": "spread", "note": "first to last"},
    ]

    # ---- badges ------------------------------------------------------------
    badges: dict[int, dict] = {}
    for r in badge_rows:
        b = badges.setdefault(r["id"], {
            "id": r["id"], "name": r["name"], "desc": r["description"], "cat": r["category"],
            "img": "assets/badges/" + Path(r["image_path"] or "").name, "holders": []})
        if r["user_id"] is not None and r["user_id"] in pname:
            b["holders"].append([r["user_id"], r["date_earned"].date().isoformat() if r["date_earned"] else None])

    # ---- time --------------------------------------------------------------
    months = defaultdict(lambda: {"games": 0, "pot": 0.0, "nights": set()})
    dow = defaultdict(int)
    for g in games.values():
        m = g["night"][:7]
        months[m]["games"] += 1
        months[m]["pot"] += g["pot"]
        months[m]["nights"].add(g["night"])
    for d in night_order:
        dow[datetime.fromisoformat(d).strftime("%a")] += 1

    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "summary": {
            "games": len(games), "nights": len(nights), "players": len(players),
            "money": r2(sum(g["pot"] for g in games.values())),
            "moved": r2(sum(v for _, _, v in flows)),
            "first": night_order[0], "last": night_order[-1],
            "dropped": dropped,
        },
        "players": players,
        "regulars": reg_ids,
        "games": [{"id": gid, "night": games[gid]["night"], "n": games[gid]["n"], "pot": games[gid]["pot"],
                   "spread": games[gid]["spread"],
                   "seats": [[s["uid"], s["net"], s["buy"], s["out"]] for s in games[gid]["seats"]]}
                  for gid in order],
        "nights": [{"date": d, "games": nights[d]["games"], "pot": r2(nights[d]["pot"]),
                    "host": nights[d]["host"],
                    "nets": sorted(([u, r2(v), nights[d]["played"][u]] for u, v in nights[d]["nets"].items()),
                                   key=lambda x: -x[1])}
                   for d in night_order],
        "h2h": {str(a): {str(b): v for b, v in row.items()} for a, row in h2h.items()},
        "flows": flows,
        "rivals": rivals,
        "records": rec,
        "fame": [seat_rec(s) for s in top_games[:10]],
        "shame": [seat_rec(s) for s in top_games[::-1][:10]],
        "badges": sorted(badges.values(), key=lambda b: (b["cat"], b["name"])),
        "months": [{"m": m, "games": v["games"], "pot": r2(v["pot"]), "nights": len(v["nights"])}
                   for m, v in sorted(months.items())],
        "dow": dow,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="dbname=ss_snapshot")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    data = build(connect(args))
    (HERE / "data.json").write_text(json.dumps(data, separators=(",", ":"), default=str))
    try:
        import make_og
        make_og.main()
    except ImportError:
        print("Pillow not installed; assets/og.png left as is")
    s = data["summary"]
    print(f"data.json: {s['games']} games, {s['nights']} nights, {s['players']} players")


if __name__ == "__main__":
    main()
