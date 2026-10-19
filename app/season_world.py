"""Common health and performance worlds, generated independently of draft policy."""
import math
import random
from datetime import date,timedelta
from .engine import aggregate


def poisson(rng,mean):
    if mean<=0:return 0
    if mean>25:return max(0,int(round(rng.gauss(mean,math.sqrt(mean)))))
    limit=math.exp(-mean);product=1.;k=0
    while product>limit:k+=1;product*=rng.random()
    return k-1


def binomial(rng,n,p):
    p=max(0,min(1,p))
    return sum(rng.random()<p for _ in range(n))


def categories(totals):return aggregate([totals])


def compare_categories(a,b):
    result=[]
    for j in range(9):
        if j<2:
            make,attempt=(0,1) if j==0 else (2,3)
            if not a[attempt] and not b[attempt]:difference=0
            elif not a[attempt]:difference=-1
            elif not b[attempt]:difference=1
            else:difference=a[make]*b[attempt]-b[make]*a[attempt]
        else:
            difference=a[j+2]-b[j+2]
            if j==8:difference=-difference
        result.append(1 if difference>0 else -1 if difference<0 else 0)
    return result


class SeasonWorld:
    def __init__(self,data,inputs,calendar,seed,config):
        self.seed=seed;self.data=data;self.inputs=inputs;self.config=config
        start=date.fromisoformat(calendar[0]['start']);end=date.fromisoformat(calendar[-1]['end'])
        self.days=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
        self.health={};self.stats={};self.events=[]
        for pid,p in data.players.items():self.generate_player(pid,p)

    def generate_player(self,pid,p):
        rng=random.Random(f'health:{self.seed}:{pid}')
        burden=max(0,min(.99,(1-p['gp']/82)*self.config['injury_scale']))
        injury_burden=burden*.75*min(1,p['mpg']/24)
        mean=self.config['mean_injury_days']
        onset=injury_burden/max(.01,(1-injury_burden)*mean)
        rest=(burden-injury_burden)/max(.01,1-injury_burden)
        remaining=0;elapsed=0;severity='short'
        if rng.random()<injury_burden:
            remaining=max(1,int(rng.expovariate(1/mean)));elapsed=rng.randrange(max(1,int(mean)))
            severity='long' if remaining>25 else 'medium' if remaining>6 else 'short'
            # Record the episode that is already in progress at season start, so the
            # event log is complete (onset may predate the season window).
            onset_date=(date.fromisoformat(self.days[0])-timedelta(days=elapsed)).isoformat()
            self.events.append({'date':onset_date,'player_id':pid,'type':'injury',
                                'simulated_duration_days':remaining,'ongoing_at_start':True})
        role_rng=random.Random(f'role:{self.seed}:{pid}')
        role=max(.65,min(1.4,role_rng.lognormvariate(-.005,.1)))
        weekly=1.;last_week=None
        health=[];stats=[];previous_game=False
        for day in self.days:
            d=date.fromisoformat(day);week=d.isocalendar()[:2]
            if week!=last_week:
                weekly=max(.75,min(1.3,role_rng.lognormvariate(-.005,.08)))
                role=max(.6,min(1.5,role*math.exp(role_rng.gauss(0,.018))))
                last_week=week
            if remaining<=0 and rng.random()<onset:
                duration=max(1,int(rng.expovariate(1/mean)))
                remaining=duration;elapsed=0
                severity='long' if duration>25 else 'medium' if duration>6 else 'short'
                self.events.append({'date':day,'player_id':pid,'type':'injury','simulated_duration_days':duration})
            injured=remaining>0
            game=p['team'] in self.inputs.games_by_day.get(day,set())
            resting=not injured and game and rng.random()<min(.8,rest*(1.4 if previous_game else 1))
            eligible=injured and severity!='short' and elapsed>=self.config['il_delay_days']
            health.append({'injured':injured,'rest':resting,'il_eligible':eligible,'diagnosis':severity if injured else None})
            box=None
            if game and not injured and not resting:
                perf=random.Random(f'box:{self.seed}:{pid}:{day}')
                minutes=max(.45,min(1.65,perf.lognormvariate(-.01,.14)))*role*weekly
                s=p['stats'];fga=poisson(perf,s[1]*minutes);fgm=binomial(perf,fga,s[0]/s[1] if s[1] else 0)
                fta=poisson(perf,s[3]*minutes);ftm=binomial(perf,fta,s[2]/s[3] if s[3] else 0)
                threes=binomial(perf,fgm,s[4]/s[0] if s[0] else 0)
                box=[fgm,fga,ftm,fta,threes,2*fgm+threes+ftm]+[poisson(perf,v*minutes) for v in s[6:]]
            stats.append(box)
            if injured:remaining-=1;elapsed+=1
            previous_game=game
        self.health[pid]=health;self.stats[pid]=stats

    def status(self,pid,day_index):return self.health[pid][day_index]
    def box(self,pid,day_index):return self.stats[pid][day_index]
