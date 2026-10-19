"""Benchmark draft policies; never commits picks to a live draft database."""
import copy
import math
import random
from .data import CATEGORIES
from .market import market_key
from .history import phase
from .draft_model import uncertainty_barrier


class SeasonDraft:
    def __init__(self,engine):
        self.engine=engine;self.data=engine.data

    def effective_punts(self,roster,strategy):
        if strategy['policy']!='auto_punt':return list(strategy['punts'])
        values=[sum(self.engine.z[p['id']][j] for p in roster) for j in range(9)]
        weakest=sorted(range(9),key=lambda j:values[j])
        # An explicit adaptive heuristic, not an inferred optimal punt. Only
        # sacrifice a genuinely weak category, and never silently punt three.
        chosen=[CATEGORIES[j] for j in weakest[:2] if values[j]<-.75]
        return chosen

    def pick(self,pool,roster,strategy):
        ordered=sorted(pool,key=market_key)
        if strategy['policy']=='adp':return ordered[0]
        punts=self.effective_punts(roster,strategy)
        sums=[sum(self.engine.z[p['id']][i] for p in roster) for i in range(9)]
        # Saturated categories receive diminishing marginal weight. We don't
        # require an early big man or lock a TO punt by narrative.
        weights=[0 if CATEGORIES[i] in punts else max(.25,math.exp(-.08*max(-3,min(6,sums[i])))) for i in range(9)]
        window=ordered[:10 if len(roster)<7 else 16]
        def score(p):
            availability=p['gp']/82
            health=1-strategy['risk']*(1-availability)
            z=self.engine.z[p['id']]
            category=sum(w*v for w,v in zip(weights,z))/max(1,sum(weights))
            games=sum(self.data.weekly[p['team']])/10.5
            playoff_factor=1+strategy['playoff_weight']*(games-1) if strategy['policy']!='fit' else 1
            production=(category+2)*health*playoff_factor-2
            need=self.engine.need_bonus(roster,p)
            market_cost=.025*math.log1p(ordered.index(p))
            return production+need-market_cost
        return max(window,key=score)

    def model_pick(self,pool,roster,team,round_number,policy,settings,uniform,drawn,seed):
        """Draft exactly as the shared conditional-choice model would for `team`.

        Used for the pooled ADP baseline (whether as our own strategy or as a
        manager override) so it is the same distribution opponents are drawn from,
        rather than a zero-variance 'always best ADP' bot.
        """
        local=dict(settings)
        if policy=='adp_stochastic':local['manager_overrides']={}
        requested='adp' if policy=='adp_stochastic' else 'fit'
        local['draft_model']='persona' if policy=='persona_experimental' else 'auto'
        if policy=='fit':local['draft_model']='baseline'
        key=(team,phase(int(round_number)),policy)
        if key not in drawn:
            drawn[key]=self.engine.draft_model.parameters(team,int(round_number),local,requested,
                random.Random(f'profile:{seed}:{team}:{key[1]}'))
        return self.engine.draft_model.choose(pool,roster,team,int(round_number),local,uniform,
            requested,drawn[key])

    def pick_live(self,live_state):
        """Production-engine pick for our turn (SHARED logic — no re-implementation).

        Calls engine.recommend() on the current partial board and returns
        (player, punt_set). Falls back to the transparent ADP+category-fit policy
        ONLY when the engine offers no recommendation (e.g. an incomplete valuation).
        It never invents ownership or keeper assignments; unresolved assets are
        refused before a draft starts.
        """
        result=self.engine.recommend(live_state)
        recs=result.get('recommendations') or []
        if recs:
            row=recs[0]
            return row['player'],(row.get('punt') or [])
        me=self.data.config['team_name']
        available=[p for p in self.data.players.values() if not p['keeper'] and p['id'] not in live_state['drafted']]
        fit={'name':'live-fallback','policy':'fit','punts':[],'streaming':'aggressive','playoff_weight':.8,'risk':.5}
        return self.pick(available,self.engine.rosters(live_state)[me],fit),[]

    def _own_select(self,live,live_state,strategy,settings,pool,roster_team,team,s,uniform,drawn,seed):
        """Our selection for one slot. Returns (player, punt_or_None)."""
        if live:
            return self.pick_live(live_state)
        if strategy['policy']=='adp_stochastic':
            return self.model_pick(pool,roster_team,team,s['round'],'adp_stochastic',settings,uniform,drawn,seed),None
        return self.pick(pool,roster_team,strategy),None

    def complete(self,state,strategy,opponent_mode,seed,manager_policies=None,first_pick=None):
        barrier=uncertainty_barrier(state,self.data)
        if barrier:raise ValueError('Cannot complete a draft: '+barrier[1])
        roster=self.engine.rosters(state)
        if any(p['id'] not in self.data.players for r in roster.values() for p in r):
            raise ValueError('Draft contains unprojected selections; season simulation cannot invent their stats.')
        manager_policies=manager_policies or {}
        pool=[p for p in self.data.players.values() if not p['keeper'] and p['id'] not in state['drafted']]
        trace=[];drawn={}
        settings=copy.deepcopy(state['settings'])
        # The `live` policy drafts from a working copy of the board via the production
        # engine, so benchmark and live recommendations share ONE implementation and
        # cannot drift. Unresolved assets were already refused by uncertainty_barrier.
        live=strategy['policy']=='live'
        live_state=copy.deepcopy(state) if live else None
        live_punt=[];forced=first_pick
        if live:
            live_state['settings']=dict(live_state.get('settings') or {})
            live_state['settings'].pop('draft_scenarios',None)   # scenario already baked into the state
        for s in state['slots']:
            if s['keeper'] or s['player_id']:continue
            team=s['current_team']
            if len(roster[team])>=13:raise ValueError('Extra owned live asset for '+team+'; reconcile draft setup.')
            uniform=random.Random(f'draft:{seed}:{s["slot"]}').random()
            policy=manager_policies.get(team,opponent_mode)
            routed=policy['policy'] if isinstance(policy,dict) else policy
            chosen_punt=None
            if team==self.data.config['team_name']:
                # A decision-level counterfactual may force our first owned pick. If the
                # forced candidate is not actually available we REFUSE rather than
                # silently substituting a different player under the requested label.
                if forced is not None:
                    forced_pick=next((p for p in pool if p['id']==forced),None)
                    if forced_pick is None:
                        raise ValueError(f'Forced candidate {forced} is not available at slot #{s["slot"]}; refusing to silently substitute.')
                    selected=forced_pick;forced=None
                else:
                    selected,chosen_punt=self._own_select(live,live_state,strategy,settings,pool,roster[team],team,s,uniform,drawn,seed)
                if live and chosen_punt is not None:live_punt=list(chosen_punt)
            elif routed=='adp_stochastic':
                selected=self.model_pick(pool,roster[team],team,s['round'],'adp_stochastic',settings,uniform,drawn,seed)
            elif isinstance(policy,dict):
                selected=self.pick(pool,roster[team],policy)
            elif policy=='adp_deterministic':
                selected=min(pool,key=market_key)
            else:
                selected=self.model_pick(pool,roster[team],team,s['round'],policy,settings,uniform,drawn,seed)
            roster[team].append(selected);pool.remove(selected)
            if live:
                slot=live_state['slots'][s['slot']-1]
                slot['player_id']=selected['id'];slot['player_name']=selected['name']
                live_state['drafted'].append(selected['id'])
                live_state['current_slot']=next((x['slot'] for x in live_state['slots'] if not x['keeper'] and not x['player_id']),None)
            trace.append({'slot':s['slot'],'team':team,'player_id':selected['id'],'name':selected['name']})
        if forced is not None:
            raise ValueError(f'Forced candidate {forced} was never applied; no owned pick remained to force it at.')
        if any(len(r)!=13 for r in roster.values()):raise ValueError('Completed draft did not allocate 13 players per team.')
        flat=[p['id'] for r in roster.values() for p in r]
        if len(set(flat))!=156:raise ValueError('Completed draft contains duplicate identities.')
        punts={team:[] for team in self.data.teams}
        if live:
            # Report the punt build the engine actually chose, not an invented one.
            punts[self.data.config['team_name']]=list(live_punt)
        else:
            punts[self.data.config['team_name']]=self.effective_punts(roster[self.data.config['team_name']],strategy)
        for team,policy in manager_policies.items():
            if team!='Oscar' and isinstance(policy,dict):punts[team]=self.effective_punts(roster[team],policy)
        return {'rosters':{t:[p['id'] for p in r] for t,r in roster.items()},'punts':punts,'trace':trace,
                'seed':seed,'own_strategy':strategy,'opponent_mode':opponent_mode,'manager_policies':manager_policies}
