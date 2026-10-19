"""Daily fantasy season, shared ownership, IL, FAB, streaming and fixed playoffs.

Policies see projections, published schedules, current health and past box scores.
They never consult future injuries or future sampled production.
"""
import math
import random
import statistics
from collections import Counter
from datetime import date,timedelta
from .engine import lineup,matchup
from .season_world import categories,compare_categories


class Cancelled(Exception):pass


class SeasonSimulator:
    def __init__(self,engine,inputs):
        self.engine=engine;self.data=engine.data;self.inputs=inputs

    def value(self,pid,punts=(),trend=None):
        p=self.data.players[pid]
        return (self.engine.value(p,punts,0)+2)*(trend or {}).get(pid,1)-2

    def projected(self,draft,calendar):
        """Post-draft baseline: expected starts, no acquisitions, no realized health."""
        expected={t:[] for t in self.data.teams}
        for period in calendar[:17]:
            start=date.fromisoformat(period['start']);end=date.fromisoformat(period['end'])
            for team,ids in draft['rosters'].items():
                totals=[0.]*11;punts=draft['punts'][team]
                for offset in range((end-start).days+1):
                    teams=self.inputs.games_by_day.get((start+timedelta(days=offset)).isoformat(),set())
                    playing=[self.data.players[p] for p in ids if self.data.players[p]['team'] in teams]
                    for p in lineup(playing,lambda p:self.value(p['id'],punts)+3):
                        a=p['gp']/82
                        totals=[x+a*y for x,y in zip(totals,p['stats'])]
                expected[team].append(categories(totals))
        wins={t:0. for t in self.data.teams}
        for week,pairs in self.inputs.matchups.items():
            for a,b in pairs:
                ca,cb=expected[a][week-1],expected[b][week-1]
                scales=[.025,.025]+[max(1,max(x,y)*.18) for x,y in zip(ca[2:],cb[2:])]
                _,edges=matchup(ca,cb,scales)
                wins[a]+=sum(edges);wins[b]+=9-sum(edges)
        order=sorted(self.data.teams,key=lambda t:(-wins[t],t))
        return {t:{'rank':order.index(t)+1,'expected_category_win_pct':wins[t]/153,
                   'roster':draft['rosters'][t],'punt':draft['punts'][t]} for t in self.data.teams}

    def target_adds(self,team,week,context,config,strategy,seed,cap,manager_strategy=None):
        rng=random.Random(f'activity:{seed}:{team}:{week}')
        if config['streaming_model']=='off':return 0
        if team==self.data.config['team_name']:
            mode=strategy['streaming']
            if mode=='off':return 0
            if mode in ('aggressive','injury_only'):return cap
        elif isinstance(manager_strategy,dict):
            mode=manager_strategy['streaming']
            if mode=='off':return 0
            if mode in ('aggressive','injury_only'):return cap
        else:mode='observed'
        if config['streaming_model']=='uniform':prob=.6
        else:
            row=self.inputs.activity[team]
            # Moves are not successful-add counts. Only a weak relative signal.
            regular=max(.15,min(.85,.55+.3*(int(row['season_moves_as_displayed'])/60-1)))
            if week<=17:prob=regular
            else:
                observed=[]
                for key in ('qf','sf','final'):
                    observed_context=row[key+'_context']
                    if context=='championship' and observed_context=='championship':observed.append(int(row[key+'_adds']))
                    elif context=='third_place' and observed_context=='third_place':observed.append(int(row[key+'_adds']))
                    elif context=='placement' and observed_context=='placement':
                        # Eligibility is not verified: zero after elimination is
                        # not treated as evidence of a passive drafting persona.
                        if int(row[key+'_adds'])>0:observed.append(int(row[key+'_adds']))
                prior=.65 if context=='championship' else .4 if context in ('placement','third_place') else regular*.6
                prob=(12*prior+sum(observed))/(12+4*len(observed))
        # Uncertain weekly intent, then a target—not a guarantee of useful adds.
        p=rng.betavariate(max(.5,prob*12),max(.5,(1-prob)*12))
        return sum(rng.random()<p for _ in range(cap))

    def standings_order(self,records,heads,last,seed):
        groups={}
        for team,r in records.items():
            pct=(r['w']+.5*r['t'])/max(1,r['w']+r['l']+r['t'])
            groups.setdefault(pct,[]).append(team)
        order=[]
        for pct,group in sorted(groups.items(),reverse=True):
            def tie(team):
                own=sum(heads.get((team,o),[0,0,0])[0]+.5*heads.get((team,o),[0,0,0])[2] for o in group if o!=team)
                total=sum(sum(heads.get((team,o),[0,0,0])) for o in group if o!=team)
                lottery=random.Random(f'tie:{seed}:{team}').random()
                return (own/max(1,total),last.get(team,0),lottery)
            order.extend(sorted(group,key=tie,reverse=True))
        return order

    def playoff_winner(self,a,b,result,heads,seeds):
        wins=sum(x>0 for x in result);losses=sum(x<0 for x in result)
        if wins!=losses:return a if wins>losses else b
        h=heads.get((a,b),[0,0,0])
        if h[0]!=h[1]:return a if h[0]>h[1] else b
        return a if seeds[a]<seeds[b] else b

    def run(self,draft,world,config,check_cancel=lambda:False):
        teams=self.data.teams;players=self.data.players;strategy=draft['own_strategy']
        state={t:{'active':list(draft['rosters'][t]),'il':[],'fab':config['starting_fab'],'adds':0,'target':0,
                  'core':set(sorted(draft['rosters'][t],key=lambda p:self.value(p,draft['punts'][t]),reverse=True)[:config['protected_core']])} for t in teams}
        owner={p:t for t,r in draft['rosters'].items() for p in r}
        waiver_until={};claims={};transactions=[];weekly=[];trends={};games_observed=Counter()
        metrics={t:Counter(adds=0,waiver_wins=0,failed_claims=0,injury_replacements=0,stream_adds=0,
                           starts=0,blocked_games=0,injured_active_days=0,il_player_days=0,budget_spent=0) for t in teams}
        records={t:{'w':0,'l':0,'t':0,'matchup_wins':0} for t in teams};heads={};last={}
        seed_order=None;seeds={};champ_games=[];placement_games=[];final_order=[];qualified=set()
        advanced={t:{'qualified':False,'semifinal':False,'final':False,'champion':False} for t in teams}
        global_day=0
        waiver_priority=list(teams)
        random.Random(f'initial-waiver-order:{world.seed}').shuffle(waiver_priority)

        def release(team,pid,day,reason):
            if pid in state[team]['active']:state[team]['active'].remove(pid)
            if pid in state[team]['il']:state[team]['il'].remove(pid)
            if owner.get(pid)!=team:raise RuntimeError('Ownership invariant failed on drop.')
            del owner[pid];waiver_until[pid]=day+config['waiver_days']
            transactions.append({'day':world.days[day],'team':team,'type':'drop','player_id':pid,'reason':reason})

        def acquire(team,pid,drop,day,bid=0,reason='stream'):
            if pid in owner or state[team]['adds']>=cap or bid>state[team]['fab']:return False
            if len(state[team]['active'])>=13:
                if drop not in state[team]['active'] or drop in state[team]['core']:return False
                release(team,drop,day,'make room for '+pid)
            state[team]['active'].append(pid);owner[pid]=team;waiver_until.pop(pid,None)
            state[team]['adds']+=1;state[team]['fab']-=bid
            metrics[team]['adds']+=1;metrics[team]['budget_spent']+=bid
            metrics[team]['waiver_wins']+=bool(bid or reason=='waiver')
            metrics[team]['injury_replacements' if reason=='injury replacement' else 'stream_adds']+=1
            transactions.append({'day':world.days[day],'team':team,'type':'add','player_id':pid,'bid':bid,'reason':reason})
            return True

        for period in config['calendar']:
            if check_cancel():raise Cancelled()
            week=period['week'];length=(date.fromisoformat(period['end'])-date.fromisoformat(period['start'])).days+1
            cap=self.data.config['acquisitions_per_week']*(2 if config['extended_adds']=='double' and length>7 else 1)
            if week<=17:
                pairs=self.inputs.matchups[week];contexts={t:'regular' for t in teams};eligible=set(teams)
            elif week==18:
                seeds={t:i+1 for i,t in enumerate(seed_order)};qualified=set(seed_order[:8])
                champ_games=[(seed_order[i],seed_order[j]) for i,j in ((0,7),(3,4),(1,6),(2,5))]
                placement_games=[];pairs=champ_games
                contexts={t:('championship' if t in qualified else 'nonqualified') for t in teams}
                eligible=set(teams) if config['eligibility']=='unlocked' else set(qualified)
                for t in qualified:advanced[t]['qualified']=True
            else:
                pairs=champ_games+placement_games
                contexts={t:'nonqualified' for t in teams}
                for a,b in champ_games:contexts[a]=contexts[b]='championship'
                for index,(a,b) in enumerate(placement_games):
                    contexts[a]=contexts[b]='third_place' if week==20 and index==0 else 'placement'
                if config['eligibility']=='unlocked':eligible=set(teams)
                elif config['eligibility']=='placement':eligible={t for pair in pairs for t in pair}
                else:
                    eligible={t for pair in champ_games for t in pair}
                    if week==20 and placement_games:eligible.update(placement_games[0])
            opponents={a:b for a,b in pairs}|{b:a for a,b in pairs}
            totals={t:[0]*11 for t in teams}
            for t in teams:
                state[t]['adds']=0
                state[t]['target']=self.target_adds(t,week,contexts[t],config,strategy,world.seed,cap,draft['manager_policies'].get(t))

            def public_value(pid,team):return self.value(pid,draft['punts'][team],trends)

            for offset in range(length):
                if check_cancel():raise Cancelled()
                day=global_day;day_string=world.days[day];game_teams=self.inputs.games_by_day.get(day_string,set())
                remaining=length-offset
                # First process returns and legal IL placement. Locked managers do
                # not release healthy players into the league's free-agent pool.
                for team in sorted(eligible):
                    s=state[team]
                    for pid in list(s['il']):
                        if not world.status(pid,day)['injured']:
                            if len(s['active'])>=13:
                                droppable=[p for p in s['active'] if p not in s['core']]
                                if not droppable:
                                    release(team,pid,day,'no legal active slot on IL return');continue
                                weakest=min(droppable,key=lambda p:public_value(p,team))
                                if pid not in s['core'] and public_value(pid,team)<public_value(weakest,team):
                                    release(team,pid,day,'replacement retained on IL return');continue
                                release(team,weakest,day,'IL return activation')
                            s['il'].remove(pid);s['active'].append(pid)
                            transactions.append({'day':day_string,'team':team,'type':'activate','player_id':pid})
                    patients=[p for p in s['active'] if world.status(p,day)['il_eligible']]
                    for pid in sorted(patients,key=lambda p:public_value(p,team),reverse=True)[:max(0,3-len(s['il']))]:
                        s['active'].remove(pid);s['il'].append(pid)
                        transactions.append({'day':day_string,'team':team,'type':'IL','player_id':pid})

                # Claims compete for a single player and real budget. Invalid or
                # losing claims do not consume adds. Claims mature on waiver day.
                for pid in list(claims):
                    if waiver_until.get(pid,day+1)>day:continue
                    bidders=[c for c in claims.pop(pid) if c['team'] in eligible and state[c['team']]['adds']<cap and state[c['team']]['fab']>=c['bid'] and pid not in owner]
                    bidders.sort(key=lambda c:(-c['bid'],waiver_priority.index(c['team'])))
                    winner=None
                    for bid in bidders:
                        if acquire(bid['team'],pid,bid['drop'],day,bid['bid'],'waiver'):
                            winner=bid['team'];waiver_priority.remove(winner);waiver_priority.append(winner);break
                    for bid in bidders:
                        if bid['team']!=winner:metrics[bid['team']]['failed_claims']+=1

                # Randomized daily first-come ordering, shared between strategy
                # experiments; never independent copies of the same free agent.
                order=sorted(eligible,key=lambda t:random.Random(f'order:{world.seed}:{day}:{t}').random())
                for team in order:
                    s=state[team]
                    if s['adds']>=cap:continue
                    missing=len(s['active'])<13
                    custom=draft['manager_policies'].get(team)
                    own_mode=strategy['streaming'] if team=='Oscar' else custom['streaming'] if isinstance(custom,dict) else 'observed'
                    if config['streaming_model']=='off' or own_mode=='off':continue
                    if not missing and (own_mode=='injury_only' or s['adds']>=s['target']):continue
                    # Pace discretionary moves; empty injury slots can be filled
                    # immediately. At most one decision per manager per day.
                    desired=max(0,s['target']-s['adds'])
                    if not missing and random.Random(f'act:{world.seed}:{team}:{day}').random()>min(1,desired/max(1,remaining)):continue
                    drop=None
                    if not missing:
                        droppable=[p for p in s['active'] if p not in s['core']]
                        if not droppable:continue
                        drop=min(droppable,key=lambda p:self.future_starts_value(p,team,s['active'],day,remaining,world,draft,trends))
                    pool=[pid for pid in players if pid not in owner and not world.status(pid,day)['injured']]
                    # Bounded scan is an explicit practical approximation; include
                    # projected quality, not only low ADP, and re-evaluate trend.
                    pool=sorted(pool,key=lambda p:public_value(p,team),reverse=True)[:70]
                    best=None
                    utility=self.lineup_utility(team,opponents[team],totals,day,remaining,state,world,draft,trends) if team in opponents else lambda pid:0
                    for pid in pool:
                        if pid==drop:continue
                        # A player on waivers cannot be used before their release date.
                        # Separate TODAY's observed health from the future eligible window:
                        # health is read at `day`; games are counted only from the release.
                        release_day=waiver_until.get(pid)
                        eligible_from=release_day-day if (release_day is not None and release_day>day) else 0
                        gain=self.future_starts_value(pid,team,[p for p in s['active'] if p!=drop],day,remaining,world,draft,trends,adding=True,eligible_from=eligible_from)
                        if drop:gain-=self.future_starts_value(drop,team,s['active'],day,remaining,world,draft,trends,eligible_from=eligible_from)
                        gain+=2*(utility(pid)-(utility(drop) if drop else 0))
                        if not missing and gain<=.15:continue
                        if best is None or gain>best[0]:best=(gain,pid)
                    if not best:continue
                    gain,pid=best
                    if waiver_until.get(pid,-1)>day:
                        bids=claims.setdefault(pid,[])
                        if not any(c['team']==team for c in bids):
                            rng=random.Random(f'bid:{world.seed}:{team}:{pid}:{day}')
                            # Ending FAB is only a weak spending proxy: initial
                            # budget/trades aren't verified by the screenshot.
                            spent=max(0,min(1,(100-int(self.inputs.activity[team]['remaining_fab_as_displayed']))/100))
                            willingness=.4 if config['streaming_model']=='uniform' else .25+.35*spent
                            amount=(2+max(0,public_value(pid,team))*6+rng.random()*4)*(.8+.4*spent)
                            bid=0 if rng.random()>willingness else int(round(amount))
                            bid=max(config['minimum_bid'],min(s['fab'],bid))
                            if bid<=s['fab']:bids.append({'team':team,'bid':bid,'drop':drop})
                    else:acquire(team,pid,drop,day,reason='injury replacement' if missing else 'stream')

                for team in teams:
                    s=state[team]
                    if len(s['active'])>13 or len(s['il'])>3 or set(s['active'])&set(s['il']):raise RuntimeError('Roster capacity invariant failed.')
                    metrics[team]['il_player_days']+=len(s['il'])
                    metrics[team]['injured_active_days']+=sum(world.status(p,day)['injured'] for p in s['active'])
                    if team not in opponents:continue
                    playing=[players[p] for p in s['active'] if players[p]['team'] in game_teams and not world.status(p,day)['injured'] and not world.status(p,day)['rest']]
                    utility=self.lineup_utility(team,opponents[team],totals,day,remaining,state,world,draft,trends)
                    chosen=lineup(playing,lambda p:utility(p['id']))
                    # Don't force negative marginal starts on the final day; TO
                    # and shooting efficiency can make deliberate benching useful.
                    if offset==length-1:chosen=[p for p in chosen if utility(p['id'])>0]
                    metrics[team]['blocked_games']+=len(playing)-len(chosen)
                    for p in chosen:
                        box=world.box(p['id'],day)
                        if box is not None:
                            totals[team]=[x+y for x,y in zip(totals[team],box)];metrics[team]['starts']+=1
                # Only after decisions/games, reveal past production to policies.
                for pid,p in players.items():
                    box=world.box(pid,day)
                    if box is not None and p['stats'][1]>1:
                        observed=max(.4,min(1.8,box[1]/p['stats'][1]))
                        trends[pid]=.88*trends.get(pid,1)+.12*observed;games_observed[pid]+=1
                flat=[p for s in state.values() for p in s['active']+s['il']]
                if len(flat)!=len(set(flat)) or set(flat)!=set(owner):raise RuntimeError('Duplicate or lost ownership.')
                global_day+=1

            outcomes=[];winners=[];losers=[]
            for a,b in pairs:
                result=compare_categories(totals[a],totals[b]);wa=sum(x>0 for x in result);wb=sum(x<0 for x in result);ties=9-wa-wb
                outcomes.append({'a':a,'b':b,'a_wins':wa,'b_wins':wb,'ties':ties,'totals_a':totals[a],'totals_b':totals[b]})
                if week<=17:
                    for t,w,l in ((a,wa,wb),(b,wb,wa)):
                        records[t]['w']+=w;records[t]['l']+=l;records[t]['t']+=ties;records[t]['matchup_wins']+=w>l;last[t]=w+.5*ties
                    for x,y,w,l in ((a,b,wa,wb),(b,a,wb,wa)):
                        h=heads.setdefault((x,y),[0,0,0]);h[0]+=w;h[1]+=l;h[2]+=ties
                else:
                    winner=self.playoff_winner(a,b,result,heads,seeds);loser=b if winner==a else a
                    outcomes[-1]['winner']=winner
                    if (a,b) in champ_games:winners.append(winner);losers.append(loser)
            weekly.append({'week':week,'start':period['start'],'end':period['end'],'matchups':outcomes,
                           'adds':{t:state[t]['adds'] for t in teams},'eligible':sorted(eligible),'contexts':contexts})
            if week==17:seed_order=self.standings_order(records,heads,last,world.seed)
            elif week==18:
                for t in winners:advanced[t]['semifinal']=True
                champ_games=[(winners[0],winners[1]),(winners[2],winners[3])]
                placement_games=[(losers[0],losers[1]),(losers[2],losers[3])]
            elif week==19:
                for t in winners:advanced[t]['final']=True
                champ_games=[(winners[0],winners[1])]
                placement_results=[o for o in outcomes if (o['a'],o['b']) in placement_games]
                placement_winners=[o['winner'] for o in placement_results]
                placement_losers=[o['b'] if o['winner']==o['a'] else o['a'] for o in placement_results]
                placement_games=[(losers[0],losers[1]),tuple(placement_winners),tuple(placement_losers)]
            elif week==20:
                advanced[winners[0]]['champion']=True
                final_order=[winners[0],losers[0]]
                for o in outcomes[1:]:final_order.extend([o['winner'],o['b'] if o['winner']==o['a'] else o['a']])
                final_order+=seed_order[8:]
        summary={t:{'regular_rank':seed_order.index(t)+1,'finish':final_order.index(t)+1,
                    'record':records[t],**advanced[t],**dict(metrics[t]),'fab_remaining':state[t]['fab'],
                    'final_active':state[t]['active'],'final_il':state[t]['il']} for t in teams}
        return {'seed':world.seed,'teams':summary,'weekly':weekly,'transactions':transactions,
                'injury_events':world.events,'regular_order':seed_order,'final_order':final_order,
                'health_model':'Synthetic; not actual injury news or calibrated season odds.'}

    def future_starts_value(self,pid,team,roster,day,remaining,world,draft,trends,adding=False,eligible_from=0):
        """Schedule-aware next-three-day starts. NO future world health access: health is
        observed TODAY (`day`), while `eligible_from` skips the first days before a waiver
        release so a just-dropped player is not credited for games he cannot play."""
        p=self.data.players[pid];current=world.status(pid,day)
        if current['injured']:return 0
        quality=lambda q:self.value(q['id'],draft['punts'][team],trends)+3
        starts=0
        for offset in range(min(3,remaining)):
            if offset<eligible_from:continue
            d=world.days[day+offset];teams=self.inputs.games_by_day.get(d,set())
            if p['team'] not in teams or offset==0 and current['rest']:continue
            others=[self.data.players[q] for q in roster if self.data.players[q]['team'] in teams and not world.status(q,day)['injured']]
            if adding:others.append(p)
            if any(q['id']==pid for q in lineup(others,quality)):starts+=1 if offset==0 else p['gp']/82
        return starts*max(.15,self.value(pid,draft['punts'][team],trends)+2)

    def lineup_utility(self,team,opponent,totals,day,remaining,state,world,draft,trends):
        # Published schedule + today's health approximate the remaining matchup.
        expected={t:list(totals[t]) for t in (team,opponent)}
        for t in expected:
            for offset in range(remaining):
                game_teams=self.inputs.games_by_day.get(world.days[day+offset],set())
                playing=[self.data.players[p] for p in state[t]['active'] if self.data.players[p]['team'] in game_teams and not world.status(p,day)['injured']]
                for p in lineup(playing,lambda q:self.value(q['id'],draft['punts'][t],trends)+3):
                    factor=trends.get(p['id'],1)*p['gp']/82
                    expected[t]=[x+y*factor for x,y in zip(expected[t],p['stats'])]
        ca,cb=categories(expected[team]),categories(expected[opponent]);punts=draft['punts'][team]
        weights=[]
        for j in range(9):
            sd=.025 if j<2 else max(1,max(ca[j],cb[j])*.18)
            gap=(ca[j]-cb[j])/sd
            weights.append(0 if self.data.config['categories'][j] in punts else math.exp(-.5*min(9,gap*gap))/sd)
        def utility(pid):
            s=self.data.players[pid]['stats'];factor=trends.get(pid,1)
            fg=(s[0]-ca[0]*s[1])/max(1,expected[team][1])
            ft=(s[2]-ca[1]*s[3])/max(1,expected[team][3])
            impact=[fg,ft]+s[4:10]+[-s[10]]
            score=sum(w*x for w,x in zip(weights,impact))*factor
            if remaining>1:score+=.01
            return score
        return utility
