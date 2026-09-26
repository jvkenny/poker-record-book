# Trophy audit — 2026-09-26

The Trophy Case used to mirror SettleStack's `earned_achievements` table. That
table was wrong in five ways, so the site now recomputes every trophy itself
(`trophies.py`) from the same cleaned games as the rest of the page. Run
`build.py --audit` to print the current differences from SettleStack.

## What was wrong in SettleStack

1. **Stale.** The last recompute ran the morning of Sep 19, 2026. Nothing from the
   Sep 19 or Sep 25 games is in it: Tim W. had no First Chips Down, and Grabowski
   was missing King of the Night, Giant Slayer, Quarterly Grinder, Profit Machine
   and The ATM.
2. **Test games count.** A game where all six players finished at exactly $0.00
   (Sep 1, 2025) handed out Debt Houdini, The Equalizer and Perfectly Balanced to
   everyone in it. Nobody has earned those in a real game. The heads-up test games
   with Jones and Celine also earned Celine and Jones a King of the Night, The Glue,
   The Closer and more. (Jones, Guy, mlibby, victoria and Alyssa are test accounts.)
3. **Nights are split by session.** SettleStack's recompute treats a session as a night,
   and sessions don't match nights. Two sessions span two nights
   (Sep 18–19 and Jul 17–18, 2026), and two nights are split at midnight into two sessions
   (Mar 17 and May 2, 2025). That's why Jon got King of the Night for winning the
   one game after midnight on May 2, and why Grabowski didn't get it for Sep 19.
4. **Rules that don't match the description.**
   - *Master of Margins* ("Win a game by less than $1") went to anyone who finished
     up by less than $1, whether or not they won. Now: finished first, less than $1
     ahead of second.
   - *Giant Slayer* used today's all-time leader for every past night. Now: the leader
     going into that night.
   - *Late-Night Gambler* ("a game that starts after midnight") was "4+ games in a day".
     Now: a real after-midnight start for games started live in the app; games logged
     afterwards only have a placeholder time, so for those the night's 4th game stands in.
   - *Participation Trophy* keeps SettleStack's reading: 10+ games, never finished first.
     Nobody qualifies.
5. **Dates were UTC.** A 9 pm Friday game is 2 am Saturday in UTC, so Friday games
   counted toward "weekend" trophies by accident and earned dates ran a day late.

## Readings chosen (say the word to change any)

- **Weekend Warrior**: 3 games across one Friday–Sunday weekend (poker night is Friday).
- **Debt Dynamo**: 10 games played with the lifetime total never worse than −$50.
- **Group Guru / Diverse Dealer** and **The Equalizer / Perfectly Balanced** are
  duplicate badges in SettleStack (same rule, different names). They're kept as-is.
- **Hosting trophies** can't be judged: SettleStack only knows the host for 3 nights.

## Not fixed here

SettleStack's own table is unchanged; the app, recaps and emails still show the old
set. Fixing it means correcting `settle-stack/scripts/recompute_achievements.py`
(nights, test accounts, Chicago dates, the rules above) and rerunning it against the
live database.
