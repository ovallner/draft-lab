"""Validate fantasy opponents, explicit calendar scenarios and benchmark settings."""
import copy
import random
from collections import Counter
from datetime import date, timedelta
from .data import ROOT, CATEGORIES, read_csv
from .draft_model import apply_scenario, uncertainty_barrier

TEAM_IDS = {'ADA':'Adam','ASH':'Ashley','AUS':'Austin','BAR':'Addison','JIP':'Jipples','KOO':'Koo',
            'NIC':'Nick','OSC':'Oscar','RAU':'Raul','SAM':'Samet','SAN':'San','SHI':'Shiven'}
POLICIES = ('live', 'adp', 'adp_stochastic', 'fit', 'playoff', 'auto_punt')
OPPONENT_MODES = ('adp_deterministic','adp_stochastic','validated','persona_experimental','fit')
SCHEDULE_DIR = 'fantasy_league_2026_27_schedule_with_dates'
LEAGUE_WEEKS = 20  # Weeks 21-23 are post-league and are never simulated
EXPECTED_GAMES_PER_TEAM = 82  # standard NBA regular-season slate
# Decision-focused default comparison: the production engine against two baselines
# (an informed ADP+category-fit manager, and a pooled ADP manager) plus one
# playoff-aware heuristic. `live` is authoritative and calls engine.recommend().
DEFAULT_STRATEGIES = [
    {'name':'Live recommendation engine','policy':'live','punts':[],'streaming':'aggressive'},
    {'name':'Competent ADP+fit baseline','policy':'fit','punts':[],'streaming':'aggressive'},
    {'name':'Pure ADP baseline','policy':'adp_stochastic','punts':[],'streaming':'aggressive'},
    {'name':'Balanced playoff fit','policy':'playoff','punts':[],'streaming':'aggressive'},
]


def load_calendar(source):
    """Read Yahoo's official 2026-27 fantasy scoring periods (all 23 weeks)."""
    rows = read_csv(source / 'fantasy_week_calendar.csv')
    if len(rows) != 23:
        raise ValueError('Expected 23 Yahoo scoring weeks')
    periods = []
    previous = None
    for index, row in enumerate(rows, 1):
        try:
            start = date.fromisoformat(row['start_date']); end = date.fromisoformat(row['end_date'])
        except (KeyError, ValueError):
            raise ValueError('Invalid calendar dates')
        if int(row['week']) != index or (end - start).days + 1 != int(row['days']):
            raise ValueError('Calendar week numbering or day count is inconsistent')
        if start > end or (previous is not None and start != previous + timedelta(days=1)):
            raise ValueError('Calendar weeks must be ordered, contiguous and non-overlapping')
        previous = end
        periods.append({'week': index, 'start': start.isoformat(), 'end': end.isoformat(),
                        'days': int(row['days']), 'week_type': row['week_type'],
                        'league_phase': row['league_phase'],
                        'extended': row['is_extended_week'].strip().lower() == 'true'})
    return periods


class SeasonInputs:
    def __init__(self,data):
        self.data=data
        self.matchups={w:[] for w in range(1,18)}
        source=data.root/SCHEDULE_DIR
        teams=read_csv(source/'teams.csv')
        if {r['team_id'] for r in teams} != set(TEAM_IDS) or set(TEAM_IDS.values()) != set(data.teams):
            raise ValueError('Fantasy schedule manager identities do not match this league.')
        names={r['team_id']:r['team_name'] for r in teams}
        pairs=set()
        week_dates={}
        for r in read_csv(source/'weekly_matchups.csv'):
            w=int(r['week']);a,b=r['team_a_id'],r['team_b_id']
            if r['season']!='2026-27' or w not in self.matchups or a==b or a not in TEAM_IDS or b not in TEAM_IDS:
                raise ValueError('Invalid fantasy matchup.')
            if r['team_a_name']!=names[a] or r['team_b_name']!=names[b]:
                raise ValueError('Fantasy schedule ID/name disagreement.')
            key=(w,*sorted((a,b)))
            if key in pairs:raise ValueError('Duplicate fantasy matchup.')
            pairs.add(key);self.matchups[w].append((TEAM_IDS[a],TEAM_IDS[b]))
            week_dates[w]=(r['week_start_date'],r['week_end_date'])
        for w,games in self.matchups.items():
            counts=Counter(t for pair in games for t in pair)
            if len(games)!=6 or counts!=Counter({t:1 for t in data.teams}):
                raise ValueError(f'Week {w} must contain exactly one match per team.')
        reciprocal=read_csv(source/'weekly_team_schedule.csv')
        if len(reciprocal)!=204:raise ValueError('Fantasy reciprocal schedule incomplete.')
        expected={(w,a,b) for w,ps in self.matchups.items() for a,b in ps}|{(w,b,a) for w,ps in self.matchups.items() for a,b in ps}
        observed={(int(r['week']),TEAM_IDS[r['team_id']],TEAM_IDS[r['opponent_team_id']]) for r in reciprocal}
        if observed!=expected:raise ValueError('Fantasy reciprocal schedule disagrees with unique pairings.')
        self.calendar=load_calendar(source)
        self.calendar_source='Yahoo official 2026-27 important game dates (' \
            'https://basketball.fantasysports.yahoo.com/nba/gamedates); opponents from the 12 League Members screenshots'
        league=self.calendar[:LEAGUE_WEEKS]
        if [p['week'] for p in league]!=list(range(1,LEAGUE_WEEKS+1)):
            raise ValueError('Calendar does not cover the league weeks')
        for week,(start,end) in week_dates.items():
            row=self.calendar[week-1]
            if (start,end)!=(row['start'],row['end']):
                raise ValueError(f'Week {week} matchup dates disagree with the Yahoo calendar')
        for index,expected_phase in ((0,'regular_season'),(17,'league_playoffs')):
            if self.calendar[index]['league_phase']!=expected_phase:
                raise ValueError('Calendar phase assignment is inconsistent')
        for offset,playoff in enumerate(self.data.config['playoff_weeks']):
            row=self.calendar[17+offset]
            if row['start']!=playoff['start'] or row['end']!=playoff['end']:
                raise ValueError('Playoff dates disagree with confirmed league settings')
        if any(p['league_phase']!='regular_season' for p in self.calendar[:17]):
            raise ValueError('Weeks 1-17 must be regular season')
        if any(p['league_phase']!='post_league_playoffs' for p in self.calendar[20:]):
            raise ValueError('Weeks 21-23 must be post-league')
        self.league_calendar=league
        self.activity={r['manager']:r for r in read_csv(data.root/'data/streaming_activity_2025.csv')}
        self.games_by_day={}
        base=Counter()
        for g in data.games:
            d=g['date'];self.games_by_day.setdefault(d,set()).update((g['home'],g['away']))
            base[g['home']]+=1;base[g['away']]+=1
        nba_teams=sorted(data.weekly)
        self.observed_games_per_team={t:base.get(t,0) for t in nba_teams}
        self.unresolved_games_per_team={t:max(0,EXPECTED_GAMES_PER_TEAM-self.observed_games_per_team[t]) for t in nba_teams}
        self.unresolved_games_added=self.distribute_unresolved_games()
        self.team_game_days={t:sorted(d for d,teams in self.games_by_day.items() if t in teams) for t in data.weekly}

    def distribute_unresolved_games(self):
        """Represent known-short NBA fixtures explicitly instead of silently
        understating the 82-game slate.

        The source feed drops NBA Cup 'to be announced' placeholders, leaving 80 games
        per team. No specific matchup is invented: each team's shortfall is added as
        extra appearances on existing league game-days it is not already playing,
        seeded from the team name so runs are reproducible. Playoff weeks are
        untouched and the choice is surfaced in metadata(). Returns games added.
        """
        if not any(self.unresolved_games_per_team.values()):return 0
        first=date.fromisoformat(self.league_calendar[0]['start'])
        last=date.fromisoformat(self.league_calendar[16]['end'])   # end of regular season (week 17)
        added=0
        for team in self.observed_games_per_team:
            missing=self.unresolved_games_per_team[team]
            if missing<=0:continue
            rng=random.Random('unresolved-games:'+team)
            days=[(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
            off=[d for d in days if team not in self.games_by_day.get(d,set())]
            # Prefer days the league already plays (a plausible make-up date), then
            # any off-day, so the shortfall is always represented in full.
            league_days=[d for d in off if self.games_by_day.get(d)]
            rng.shuffle(league_days)
            chosen=list(league_days[:missing])
            if len(chosen)<missing:
                remaining=[d for d in off if d not in chosen];rng.shuffle(remaining)
                chosen+=remaining[:missing-len(chosen)]
            for d in sorted(chosen):self.games_by_day.setdefault(d,set()).add(team)
            added+=len(chosen)
        return added

    def metadata(self):
        nonstandard=[{'week':p['week'],'days':p['days'],'week_type':p['week_type']}
                     for p in self.calendar if p['extended']]
        return {'schedule_matchups':102,'regular_weeks':17,'league_weeks':LEAGUE_WEEKS,
                'calendar_weeks':len(self.calendar),'schedule_dates_verified':True,
                'calendar_source':self.calendar_source,'calendar':self.calendar,
                'nonstandard_weeks':nonstandard,
                'schedule_games_per_team':{t:self.observed_games_per_team[t]+self.unresolved_games_per_team[t] for t in self.observed_games_per_team},
                'observed_games_per_team':dict(sorted(self.observed_games_per_team.items())),
                'unresolved_games_per_team':dict(sorted(self.unresolved_games_per_team.items())),
                'unresolved_games_added':self.unresolved_games_added,
                'default_strategies':DEFAULT_STRATEGIES,'opponent_modes':list(OPPONENT_MODES),
                'activity':self.activity,
                'notes':['Fantasy opponents AND scoring-week dates are verified: opponents from the 12 League Members '
                         'screenshots, dates from Yahoo official Important Game Dates.',
                         'The daily fixture feed omits NBA Cup "to be announced" placeholders (80 games/team). Each '
                         'team shortfall is represented as extra appearances on existing league game-days, seeded per '
                         'team, so the full 82-game slate is modeled without inventing matchups.',
                         'Non-standard weeks: W1 is 6 days; W7 (14 days, NBA Cup) and W17 (14 days, All-Star break) are '
                         'long calendar periods with only 6 and 8 NBA game-days, so period length is NOT a proxy for games played.',
                         'League playoffs are Weeks 18-20 (2027-03-01 to 2027-03-21). Weeks 21-23 are post-league and are not simulated.',
                         'Known NBA schedule has 80 defined games per team. Unassigned NBA Cup games are not invented.',
                         'Streaming activity is manually transcribed from five user screenshots covering Feb 24 to Mar 22, 2026 and the supplied playoff bracket.',
                         'Season Moves totals are an ordinal activity signal, NOT a verified successful-acquisition count. Late placement eligibility and inactivity are uncertain.']}

    def prepare(self,state,config):
        if len(self.data.games)<1000 or len(self.team_game_days)!=30 or any(len(ds)<70 for ds in self.team_game_days.values()):
            raise ValueError('Full-season daily NBA fixtures are missing/incomplete. Import the full known-season schedule before benchmarking.')
        if not isinstance(config,dict):raise ValueError('Benchmark config must be an object.')
        c=copy.deepcopy(config)
        unknown=set(c)-{'strategies','opponent_modes','manager_policies','drafts','seasons_per_draft','seed','seed_block','holdout','start_mode',
                       'asset_scenarios','calendar','calendar_source','injury_scale','mean_injury_days',
                       'il_delay_days','starting_fab','minimum_bid','waiver_days','eligibility','streaming_model',
                       'extended_adds','protected_core'}
        if unknown:raise ValueError('Unknown benchmark settings: '+', '.join(sorted(unknown)))
        for key,default,low,high in (('drafts',3,1,500),('seasons_per_draft',3,1,20),('seed',20261018,0,2**31-1),
            ('il_delay_days',2,0,7),('starting_fab',100,0,1000),('minimum_bid',0,0,100),('waiver_days',2,1,7),('protected_core',8,0,13)):
            v=c.get(key,default)
            if type(v) is not int or not low<=v<=high:raise ValueError(f'{key} must be an integer {low}–{high}.')
            c[key]=v
        for key,default,low,high in (('injury_scale',1.,0.,2.),('mean_injury_days',12.,2.,45.)):
            v=c.get(key,default)
            if not isinstance(v,(int,float)) or not low<=v<=high:raise ValueError('Invalid '+key)
            c[key]=v
        from .seeds import validate_block
        c['seed_block']=c.get('seed_block','exploration')
        c['holdout']=c.get('holdout',1)
        validate_block(c['seed_block'],c['holdout'])
        for key,default,allowed in (('start_mode','keepers',('keepers','current')),
                ('eligibility','placement',('placement','championship_only','unlocked')),
                ('streaming_model','observed',('observed','uniform','off')),
                ('extended_adds','same',('same','double'))):
            c[key]=c.get(key,default)
            if c[key] not in allowed:raise ValueError('Invalid '+key)
        c['strategies']=c.get('strategies',copy.deepcopy(DEFAULT_STRATEGIES))
        if not isinstance(c['strategies'],list) or not 1<=len(c['strategies'])<=8:raise ValueError('Choose 1–8 own strategies.')
        names=set()
        for s in c['strategies']:
            self.validate_strategy(s)
            if s['name'] in names:raise ValueError('Strategy names must be unique.')
            names.add(s['name'])
        c['opponent_modes']=c.get('opponent_modes',['adp_stochastic','validated'])
        if not isinstance(c['opponent_modes'],list) or not c['opponent_modes'] or len(set(c['opponent_modes']))!=len(c['opponent_modes']) or any(m not in OPPONENT_MODES for m in c['opponent_modes']):
            raise ValueError('Invalid opponent model selection.')
        policies=c.get('manager_policies',{})
        if not isinstance(policies,dict) or set(policies)-set(self.data.teams):raise ValueError('Manager policies must use canonical manager names.')
        for p in policies.values():
            if isinstance(p,str):
                if p not in OPPONENT_MODES:raise ValueError('Invalid manager policy.')
            elif isinstance(p,dict):
                p.setdefault('streaming','observed');self.validate_strategy(p)
            else:raise ValueError('Invalid manager strategy override.')
        c['manager_policies']=policies
        if c.get('calendar'):
            if not isinstance(c.get('calendar_source'),str) or not c['calendar_source'].strip():raise ValueError('Provide provenance for custom scoring dates.')
            periods=c['calendar']
        else:
            # Verified Yahoo scoring weeks; no acknowledgement is required.
            periods=[dict(p) for p in self.league_calendar]
            c['calendar_source']=self.calendar_source
        if not isinstance(periods,list) or len(periods)!=LEAGUE_WEEKS:raise ValueError(f'Provide exactly {LEAGUE_WEEKS} scoring periods.')
        previous=None
        for week,p in enumerate(periods,1):
            try:a=date.fromisoformat(p['start']);b=date.fromisoformat(p['end'])
            except (KeyError,TypeError,ValueError):raise ValueError('Invalid scoring-period dates.')
            if p.get('week')!=week or a>b or (previous and a!=previous+timedelta(days=1)):
                raise ValueError('Scoring periods must be ordered, contiguous and nonoverlapping.')
            if (b-a).days>20 or week==1 and abs((a-date(2026,10,20)).days)>7:
                raise ValueError('Calendar is outside the supported season window or has an excessively long period.')
            if week>=18:
                expected=self.data.config['playoff_weeks'][week-18]
                if p['start']!=expected['start'] or p['end']!=expected['end']:raise ValueError('Playoff dates disagree with confirmed league settings.')
            previous=b
        c['calendar']=periods
        if min(self.games_by_day)>periods[0]['end'] or max(self.games_by_day)<periods[-1]['end']:
            raise ValueError('NBA fixture dates do not cover the requested fantasy season.')
        base=copy.deepcopy(state)
        if c['start_mode']=='keepers':
            for s in base['slots']:
                s.update(player_id=None,player_name=s['keeper_player'] if s['keeper'] else '')
            base.update(drafted=[],current_slot=next(s['slot'] for s in base['slots'] if not s['keeper']),custom_players=[])
        elif any(p['id'].startswith('manual:') for p in base['custom_players'] if p['id'] in base['drafted']):
            raise ValueError('A recorded player lacks projections; import their stats before season simulation.')
        saved_hypothesis=any('hypoth' in s.get('confidence','') for s in base['slots'])
        scenarios=c.get('asset_scenarios',base['settings'].get('draft_scenarios',[])) or [{'name':'Saved mock asset hypothesis' if saved_hypothesis else 'Confirmed assets'}]
        if not isinstance(scenarios,list) or not 1<=len(scenarios)<=5:raise ValueError('Choose 1–5 explicit asset scenarios.')
        c['asset_scenarios']=scenarios
        states=[]
        for scenario in scenarios:
            hypothetical=apply_scenario(base,scenario,self.data)
            barrier=uncertainty_barrier(hypothetical,self.data)
            if barrier:raise ValueError(f"{scenario['name']}: {barrier[1]}. Full seasons require complete exact assets; use an explicitly named hypothesis, not guessed owners.")
            states.append(hypothetical)
        total=len(c['strategies'])*len(c['opponent_modes'])*len(states)*c['drafts']*c['seasons_per_draft']
        if total>20000:raise ValueError(f'{total} seasons requested; maximum is 20000 per batch. Split the comparison into batches.')
        c['total_seasons']=total
        c['assumptions']={'calendar':c['calendar_source'],
            'fixtures':'Known fixtures plus an explicit, seeded representation of the unresolved NBA Cup / TBD team-games (source feed drops them at 80/team); no specific matchups invented. NBA teams fixed to the projection snapshot',
            'weeks':f'{LEAGUE_WEEKS} league weeks simulated (17 regular + 3 playoff). W1 is 6 days; W7 and W17 are 14-day periods with only 6 and 8 NBA game-days, so period length is not a games-played proxy.',
            'injuries':'Synthetic Markov episodes calibrated approximately to GP/82; injury share is 75% scaled down for low-MPG role players, remainder isolated rest/role absences. No actual injury diagnosis inferred.',
            'il':'Three IL slots; medium/long episodes eligible after configurable delay. Returning players require an active-slot opening.',
            'waivers':'Daily pregame processing; dropped players wait configured calendar days; unsuccessful bids consume no acquisition or budget. Initial waiver order is seeded random, winning bidders move to end for continual rolling tiebreak. Starting FAB/minimum bid are assumptions; old ending balances give only weak spending priors.',
            'tiebreaks':'Category win percentage, then head-to-head category percentage, then last-period category percentage, then common seeded lottery for regular-season ties. Playoff ties use regular head-to-head category percentage, then higher seed. Verify exact Yahoo fallbacks.',
            'streaming':'Shared free-agent pool, four adds per scoring period by default (extended 14-day periods keep four unless the optional double cap is enabled), three IL slots, no future-health or box-score oracle. Source Moves totals used only as weak ordinal regular-season activity priors.',
            'eligibility':c['eligibility']+' (interpretation of eliminated-team locking is unverified)',
            'performance':'Coherent sampled shooting counts plus shared minute/weekly-form variability; projected points reconstructed from shooting makes due rounding. Not calibrated player covariance.',
            'limits':'Population restricted to imported projections; missing Yahoo-eligible players cannot be invented. Fixed NBA teams, no fantasy/NBA trades or schedule revisions, no historical role/injury calibration or injury-driven teammate promotions, no speculative injured-FA stash purchases. No calibration of championship frequencies.'}
        return c,states

    @staticmethod
    def validate_strategy(s):
        if not isinstance(s,dict) or set(s)-{'name','policy','punts','streaming','playoff_weight','risk'}:raise ValueError('Invalid draft strategy fields.')
        if not isinstance(s.get('name'),str) or not s['name'].strip():raise ValueError('Each strategy needs a name.')
        if s.get('policy','playoff') not in POLICIES:raise ValueError('Invalid own draft policy.')
        s.setdefault('policy','playoff');s.setdefault('punts',[]);s.setdefault('streaming','aggressive')
        if not isinstance(s['punts'],list) or len(s['punts'])>2 or len(set(s['punts']))!=len(s['punts']) or any(x not in CATEGORIES for x in s['punts']):raise ValueError('Choose at most two valid punt categories.')
        if s['streaming'] not in ('aggressive','observed','injury_only','off'):raise ValueError('Invalid streaming policy.')
        for k,d in (('playoff_weight',.8),('risk',.5)):
            s.setdefault(k,d)
            if not isinstance(s[k],(float,int)) or not 0<=s[k]<=1:raise ValueError('Strategy weights must be 0–1.')
