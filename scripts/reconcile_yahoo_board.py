#!/usr/bin/env python3
"""Read-only reconciliation check: Yahoo completed board vs Draft Lab live board.

Transcribed from the completed-board screenshot (2026-10-19 10.51.49). Each entry is
(round, pick, owning_team, player); the owning team is the Yahoo column, which already
reflects traded picks. Overall slot = (round-1)*12 + pick.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import Data, normalize
from app.engine import Engine
from app.store import Store

# (round, pick, owner, player)
YAHOO = [
 (1,1,'Shiven','Victor Wembanyama'),(1,2,'Koo','Luka Doncic'),(1,3,'Raul','Nikola Jokic'),(1,4,'Ashley','Tyrese Maxey'),
 (1,5,'Addison','Giannis Antetokounmpo'),(1,6,'Oscar','Cade Cunningham'),(1,7,'Austin','Karl-Anthony Towns'),(1,8,'Nick','Kevin Durant'),
 (1,9,'Jipples','Josh Giddey'),(1,10,'Samet','Scottie Barnes'),(1,11,'San','Evan Mobley'),(1,12,'Adam','Trae Young'),
 (2,1,'Adam','Cooper Flagg'),(2,2,'San','Jamal Murray'),(2,3,'Samet','LaMelo Ball'),(2,4,'Jipples','Walker Kessler'),
 (2,5,'Nick','Anthony Davis'),(2,6,'Austin','Chet Holmgren'),(2,7,'Oscar','Donovan Mitchell'),(2,8,'Addison','Alperen Sengun'),
 (2,9,'Ashley','Bam Adebayo'),(2,10,'Raul','Devin Booker'),(2,11,'Koo','James Harden'),(2,12,'Shiven','Lauri Markkanen'),
 (3,1,'Shiven','Kawhi Leonard'),(3,2,'Koo','Stephen Curry'),(3,3,'Raul','Brandon Miller'),(3,4,'Ashley','Anthony Edwards'),
 (3,5,'Addison','Derrick White'),(3,6,'Oscar','Shai Gilgeous-Alexander'),(3,7,'Austin','Donovan Clingan'),(3,8,'Nick','Darius Garland'),
 (3,9,'Jipples','Jayson Tatum'),(3,10,'Samet','Jalen Williams'),(3,11,'San','Jaylen Brown'),(3,12,'Adam','Domantas Sabonis'),
 (4,1,'Adam','Paolo Banchero'),(4,2,'San','Jaren Jackson Jr.'),(4,3,'Samet','Cameron Boozer'),(4,4,'Jipples','Dyson Daniels'),
 (4,5,'Nick','LeBron James'),(4,6,'Austin','Desmond Bane'),(4,7,'Oscar','Matas Buzelis'),(4,8,'Addison','Pascal Siakam'),
 (4,9,'Ashley','Mikal Bridges'),(4,10,'Raul','OG Anunoby'),(4,11,'Koo','Onyeka Okongwu'),(4,12,'Shiven','Trey Murphy III'),
 (5,1,'Shiven','Cason Wallace'),(5,2,'Koo','Kyrie Irving'),(5,3,'Raul','Damian Lillard'),(5,4,'Ashley','Jarrett Allen'),
 (5,5,'Addison','Franz Wagner'),(5,6,'Oscar','Ivica Zubac'),(5,7,'Austin','Michael Porter Jr.'),(5,8,'Nick','Joel Embiid'),
 (5,9,'Jipples','Ausar Thompson'),(5,10,'Samet','Zach Edey'),(5,11,'San','Josh Hart'),(5,12,'Adam','Ryan Rollins'),
 (6,1,'Adam','Dejounte Murray'),(6,2,'San','Jalen Brunson'),(6,3,'Samet','Ty Jerome'),(6,4,'Jipples',"Kel'el Ware"),
 (6,5,'Nick','Tyler Herro'),(6,6,'Austin','Payton Pritchard'),(6,7,'Oscar','Paul George'),(6,8,'Addison','Austin Reaves'),
 (6,9,'Ashley','Immanuel Quickley'),(6,10,'Raul','Caleb Wilson'),(6,11,'Koo','Julius Randle'),(6,12,'Shiven','Collin Murray-Boyles'),
 (7,1,'Shiven','Tyrese Haliburton'),(7,2,'Koo','Naz Reid'),(7,3,'Raul','Egor Demin'),(7,4,'Ashley','AJ Dybantsa'),
 (7,5,'Addison','Coby White'),(7,6,'Oscar',"De'Aaron Fox"),(7,7,'Austin',"Day'Ron Sharpe"),(7,8,'Nick','Jalen Suggs'),
 (7,9,'Jipples','Amen Thompson'),(7,10,'Samet','Isaiah Hartenstein'),(7,11,'San','Ajay Mitchell'),(7,12,'Adam','Jalen Duren'),
 (8,1,'Adam','Darius Acuff Jr.'),(8,2,'San','Norman Powell'),(8,3,'Samet','Jalen Johnson'),(8,4,'Jipples','Rudy Gobert'),
 (8,5,'Nick','Ja Morant'),(8,6,'Austin','Andrew Wiggins'),(8,7,'Oscar','Cedric Coward'),(8,8,'Addison','Zion Williamson'),
 (8,9,'Ashley','Jalen Green'),(8,10,'Raul','Deni Avdija'),(8,11,'Koo','John Collins'),(8,12,'Shiven','Jakob Poeltl'),
 (9,1,'Shiven','Zach LaVine'),(9,2,'Koo','Darryn Peterson'),(9,3,'Raul','Derik Queen'),(9,4,'Ashley','Myles Turner'),
 (9,5,'Addison','Brandin Podziemski'),(9,6,'Oscar','Robert Williams III'),(9,7,'Austin','CJ McCollum'),(9,8,'Nick','Keegan Murray'),
 (9,9,'Jipples','Yaxel Lendeborg'),(9,10,'Raul','Brandon Ingram'),(9,11,'San','Wendell Carter Jr.'),(9,12,'Adam','Nic Claxton'),
 (10,1,'Adam','Rui Hachimura'),(10,2,'San','Toumani Camara'),(10,3,'Samet','VJ Edgecombe'),(10,4,'Jipples','Stephon Castle'),
 (10,5,'Samet','Dylan Harper'),(10,6,'Austin','Miles Bridges'),(10,7,'Oscar','DeMar DeRozan'),(10,8,'Addison','Alex Sarr'),
 (10,9,'Ashley','Nickeil Alexander-Walker'),(10,10,'Raul','Neemias Queta'),(10,11,'Koo','Peyton Watson'),(10,12,'Shiven','Collin Gillespie'),
 (11,1,'Shiven','Sandro Mamukelashvili'),(11,2,'Koo','Jonathan Kuminga'),(11,3,'Nick','Ace Bailey'),
 (11,4,'Ashley','Kon Knueppel'),(11,5,'Addison','RJ Barrett'),(11,6,'Oscar','Cam Spencer'),(11,7,'Austin','Kevin Porter Jr.'),
 (11,8,'Nick','Jabari Smith Jr.'),(11,9,'Jipples','Davion Mitchell'),(11,10,'Samet','Jimmy Butler III'),
 (11,11,'San','Aaron Gordon'),(11,12,'Adam','Khaman Maluach'),
 (12,1,'Adam','Cameron Johnson'),(12,2,'San','Keyonte George'),(12,3,'Samet','Jeremiah Fears'),(12,4,'Jipples','Draymond Green'),
 (12,5,'Nick','Reed Sheppard'),(12,6,'Austin','Fred VanVleet'),(12,7,'Oscar','Kyshawn George'),(12,8,'Addison','Quentin Grimes'),
 (12,9,'Ashley','Anthony Black'),(12,10,'Raul','Jaden McDaniels'),(12,11,'Koo','Jaime Jaquez Jr.'),(12,12,'Shiven','Ayo Dosunmu'),
 (13,1,'Shiven','Gui Santos'),(13,2,'Koo','P.J. Washington'),(13,3,'Raul','Daniel Gafford'),(13,4,'Ashley','Jared McCain'),
 (13,5,'Addison','Aday Mara'),(13,6,'Oscar','Paul Reed'),(13,7,'Austin','Christian Braun'),(13,8,'Nick','Isaiah Jackson'),
 (13,9,'Jipples','Zaccharie Risacher'),(13,10,'Samet','Jrue Holiday'),(13,11,'San','Precious Achiuwa'),(13,12,'Adam','Yves Missi'),
]

YAHOO_KEEPERS = {'Donovan Mitchell','Jamal Murray','Cooper Flagg','Kawhi Leonard','Anthony Edwards','Derrick White',
 'Shai Gilgeous-Alexander','Darius Garland','Jayson Tatum','Trey Murphy III','Onyeka Okongwu','OG Anunoby','Kyrie Irving',
 'Austin Reaves','Jalen Brunson','Dejounte Murray','Tyrese Haliburton','Naz Reid','Amen Thompson','Jalen Duren','Deni Avdija',
 'Jalen Johnson','VJ Edgecombe','Nickeil Alexander-Walker','Alex Sarr','Ace Bailey','Stephon Castle','Dylan Harper',
 'Kon Knueppel','Kevin Porter Jr.','Jabari Smith Jr.','Jaden McDaniels','Kyshawn George','Fred VanVleet','Keyonte George'}

# Yahoo display names that differ from the Hashtag projection name (normalized keys).
NAME_ALIASES = {'nicclaxton': 'nicolasclaxton', 'alexsarr': 'alexandresarr'}


def yahoo_slots():
    out = {}
    for rnd, pick, owner, player in YAHOO:
        slot = (rnd - 1) * 12 + pick
        if slot in out:
            raise SystemExit(f'Duplicate Yahoo slot #{slot}')
        out[slot] = (owner, player)
    return out


def main():
    data = Data(); store = Store('local/draft.sqlite3', data); state = store.state()
    engine = Engine(data)
    yahoo = yahoo_slots()
    print(f'Yahoo matrix: {len(yahoo)} slots, {len(YAHOO_KEEPERS)} keepers')
    by_norm = {}
    for p in data.players.values():
        by_norm.setdefault(normalize(p['name']), []).append(p)
    resolved = {}
    for slot, (team, name) in yahoo.items():
        key = normalize(NAME_ALIASES.get(normalize(name), name))
        matches = by_norm.get(key, [])
        if len(matches) != 1:
            raise SystemExit(f'Yahoo name {name!r} matched {len(matches)} projection players')
        resolved[slot] = (team, matches[0])
    diffs = []
    for slot in sorted(resolved):
        yteam, yplayer = resolved[slot]
        s = state['slots'][slot - 1]
        db_name = s['player_name'] if s['player_id'] else (s['keeper_player'] if s['keeper'] else '')
        if s['player_id']:
            db_player = data.players.get(s['player_id'])
            same = db_player is not None and db_player['id'] == yplayer['id']
        else:
            db_key = normalize(NAME_ALIASES.get(normalize(db_name), db_name)) if db_name else ''
            same = bool(db_name) and db_key == normalize(NAME_ALIASES.get(normalize(yplayer['name']), yplayer['name']))
        if not same or s['current_team'] != yteam:
            diffs.append((slot, s['current_team'], db_name or '(empty)', yteam, yplayer['name'], s['keeper'],
                          yplayer['name'] in YAHOO_KEEPERS))
    print(f'Slot-level differences: {len(diffs)}')
    for d in diffs:
        print('  #%-3d DL: %-8s %-26s -> Yahoo: %-8s %-26s %s%s' % (
            d[0], d[1], d[2], d[3], d[4], 'KEEPER' if d[5] else '', '' if d[6] else '  [NOT-YAHOO-KEEPER]'))

    print('\nRoster differences:')
    dl = engine.rosters(state)
    any_diff = False
    for team in data.teams:
        have = {p['id'] for p in dl[team]}
        want = {resolved[s][1]['id'] for s in resolved if resolved[s][0] == team}
        if have != want:
            any_diff = True
            print(f'  {team}: only-DL={sorted(data.players[i]["name"] for i in have - want)} only-Yahoo={sorted(data.players[i]["name"] for i in want - have)}')
    if not any_diff:
        print('  none')

    all_ids = [resolved[s][1]['id'] for s in resolved]
    print(f'\nYahoo: {len(all_ids)} entries, {len(set(all_ids))} unique, per-team={sorted({sum(1 for s in resolved if resolved[s][0]==t) for t in data.teams})}')
    print(f'Draft Lab: drafted={len(state["drafted"])}, keeper_slots={sum(1 for s in state["slots"] if s["keeper"])}, current_slot={state["current_slot"]}')
    store.db.close()


if __name__ == '__main__':
    main()
