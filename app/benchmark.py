"""Nested, paired draft/season strategy experiments; resumable persisted results."""
import copy
import hashlib
import json
import math
import random
import statistics
import threading
from pathlib import Path
from .data import Data,ROOT
from .engine import Engine
from . import seeds
from .season_inputs import SeasonInputs
from .season_draft import SeasonDraft
from .season_world import SeasonWorld
from .season_sim import SeasonSimulator,Cancelled
from .draft_model import wilson


def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False));temp.replace(path)


def distribution(values):
    ordered=sorted(values)
    return {'mean':statistics.mean(values),'median':statistics.median(values),
            'p10':ordered[int((len(ordered)-1)*.1)],'p90':ordered[int((len(ordered)-1)*.9)]}


# Preference order used only to pick a HEADLINE model for the recommendation.
# The others become robustness checks rather than being blended in.
OPPONENT_PREFERENCE = ('adp_stochastic','validated','fit','persona_experimental','adp_deterministic')

# A championship lead is only treated as firm when it is carried by at least this
# many decisive draft clusters, not by one or two lucky simulated titles.
MIN_DECISIVE_CLUSTERS = 3
# If the winner's paired championship interval lies entirely inside this band, the
# top strategies are statistically indistinguishable and we say so rather than
# implying precision.
EQUIVALENCE_MARGIN = 0.05


def advancement(outcome):
    """Playoff-first graded outcome: 0 missed, 1 QF, 2 SF, 3 final, 4 champion.

    A smoother, less noise-dominated target than the binary title flag, and still
    strictly playoff-focused rather than regular-season production.
    """
    return (int(bool(outcome['qualified'])) + int(bool(outcome['semifinal']))
            + int(bool(outcome['final'])) + int(bool(outcome['champion'])))


def cluster_interval(drafts,key,seed,extract=None):
    # A draft produces several dependent seasons; resample entire draft clusters.
    pick=extract or (lambda s:int(bool(s['teams']['Oscar'][key])))
    blocks=[[pick(s) for s in d['seasons']] for d in drafts if d['seasons']]
    if len(blocks)<3:return {'low':0.,'high':1.,'warning':'Fewer than three draft clusters; interval intentionally uninformative.'}
    rng=random.Random(seed);values=[]
    for _ in range(1000):
        selected=rng.choices(blocks,k=len(blocks));values.append(statistics.mean(x for block in selected for x in block))
    values.sort()
    low,high=values[24],values[974]
    warning=None
    if low==high:
        flat=[x for block in blocks for x in block]
        if all(x in (0,1) for x in flat):
            rate=statistics.mean(flat)
            guard=wilson(rate*len(blocks),len(blocks));low=min(low,guard[0]);high=max(high,guard[1])
            warning='Degenerate bootstrap widened with an effective-draft Wilson guard; heuristic, not proof of zero/one probability.'
        else:
            # Non-binary metric (e.g. 0-4 advancement): widen by the draft-cluster
            # standard error instead, since a Wilson bound does not apply.
            means=[statistics.mean(b) for b in blocks]
            stderr=statistics.stdev(means)/math.sqrt(len(means)) if len(means)>1 else 0
            low,high=low-1.96*stderr,high+1.96*stderr
            warning='Degenerate bootstrap widened by the draft-cluster standard error.'
    return {'low':low,'high':high,'method':'draft-cluster bootstrap; conditional on modeled assumptions','warning':warning}


class BenchmarkRunner:
    def __init__(self,run_directory,data=None):
        self.directory=Path(run_directory)
        self.data=data or Data()
        self.engine=Engine(self.data)
        self.inputs=SeasonInputs(self.data)
        self.drafter=SeasonDraft(self.engine)
        self.simulator=SeasonSimulator(self.engine,self.inputs)

    def cancelled(self):return (self.directory/'cancel.request').exists()

    def run(self):
        request=json.loads((self.directory/'request.json').read_text())
        if 'input_hashes' in request:
            from .benchmark_jobs import input_hashes
            if request['input_hashes']!=input_hashes(self.data.root):raise ValueError('Data or simulation code changed; refusing mixed-input benchmark results.')
        config,states=self.inputs.prepare(request['state'],request['config'])
        result={'format':'draft-lab-season-benchmark-v1','config':config,'source_session':request['source_session'],
                'source_revision':request['state']['revision'],'cases':[],
                'metadata':{'seed_block':config['seed_block'],'holdout':config['holdout'],
                            'inputs':self.inputs.metadata(),'schedule_source':self.data.schedule_metadata,
                            'persona_validation':self.data.history_package['validation']['decision'] if self.data.history_package else 'not available',
                            'source_hashes':self.data.history_package['report']['metadata']['source_sha256'] if self.data.history_package else {},
                            'projections_sha256':hashlib.sha256((self.data.root/'hashtag_basketball_2026_27_projections_430.csv').read_bytes()).hexdigest(),
                            'matchups_sha256':hashlib.sha256((self.data.root/'fantasy_league_2026_27_schedule_with_dates/weekly_matchups.csv').read_bytes()).hexdigest(),
                            'calendar_sha256':hashlib.sha256((self.data.root/'fantasy_league_2026_27_schedule_with_dates/fantasy_week_calendar.csv').read_bytes()).hexdigest(),
                            'calendar_source':self.inputs.metadata()['calendar_source']},
                'notes':['Simulated results, NOT real observed season outcomes or calibrated championship probabilities.',
                         'Same draft-index/season-index health and performance worlds across strategies, opponent models and asset scenarios.',
                         'No arbitrary weighting across opponent-model or asset scenarios. Compare strategies within each case group.',
                         'Own automatic picks use transparent bounded-market category/GP/playoff heuristics, not the live expensive candidate solver.',
                         'Post-draft projected rankings are a no-streaming/no-realized-health category-matchup baseline. Injuries and transactions drive the simulated outcomes.',
                         'Injury durations, role drift, waiver processing clock, scoring dates and lock interpretation are assumptions; sensitivity runs are necessary.',
                         'Multiple seasons per draft are dependent; reported uncertainty resamples whole draft clusters. Small batches cannot determine a robust best strategy.']}
        cases=[(si,mode,strategy) for si in range(len(states)) for mode in config['opponent_modes'] for strategy in config['strategies']]
        for ci,(si,mode,strategy) in enumerate(cases):
            result['cases'].append({'id':ci,'asset_scenario':config['asset_scenarios'][si]['name'],
                                    'opponent_mode':mode,'strategy':strategy,'drafts':[]})
        completed=0
        try:
            # World is generated once per replicate and reused for all policies.
            for draft_index in range(config['drafts']):
                generated={}
                draft_seed=seeds.draft_seed(config['seed'],config['seed_block'],config['holdout'],draft_index)
                for case in result['cases']:
                    ci=case['id'];si,mode,strategy=cases[ci]
                    if self.cancelled():raise Cancelled()
                    draft=self.drafter.complete(states[si],strategy,mode,draft_seed,config['manager_policies'])
                    projected=self.simulator.projected(draft,config['calendar'])
                    d={'index':draft_index,'draft':draft,'projected':projected,'seasons':[]}
                    case['drafts'].append(d);generated[ci]=d
                for season_index in range(config['seasons_per_draft']):
                    if self.cancelled():raise Cancelled()
                    world_seed=seeds.world_seed(config['seed'],config['seed_block'],config['holdout'],draft_index,season_index)
                    world=SeasonWorld(self.data,self.inputs,config['calendar'],world_seed,config)
                    for case in result['cases']:
                        if self.cancelled():raise Cancelled()
                        ci=case['id'];d=generated[ci]
                        detail=self.directory/f'case-{ci}-draft-{draft_index}-season-{season_index}.json'
                        # A resume reuses completed identical replicate files.
                        if detail.exists():outcome=json.loads(detail.read_text())
                        else:
                            outcome=self.simulator.run(d['draft'],world,config,self.cancelled)
                            atomic_json(detail,outcome)
                        d['seasons'].append({'index':season_index,'seed':world_seed,'teams':outcome['teams'],
                                             'detail_file':detail.name,'final_order':outcome['final_order']})
                        completed+=1
                        self.summarize(result)
                        atomic_json(self.directory/'results.json',result)
                        atomic_json(self.directory/'status.json',{'state':'running','completed':completed,'total':config['total_seasons'],
                            'current':{'strategy':case['strategy']['name'],'opponent_mode':case['opponent_mode'],
                                       'draft':draft_index+1,'season':season_index+1},'run_id':self.directory.name})
            self.summarize(result)
            result['paired_comparisons']=self.paired_comparisons(result,config['seed'])
            result['recommendation']=self.recommendation(result,config['seed'])
            atomic_json(self.directory/'results.json',result)
            atomic_json(self.directory/'status.json',{'state':'completed','completed':completed,'total':config['total_seasons'],'run_id':self.directory.name})
        except Cancelled:
            self.summarize(result)
            result['paired_comparisons']=self.paired_comparisons(result,config['seed'])
            result['recommendation']=self.recommendation(result,config['seed'])
            atomic_json(self.directory/'results.json',result)
            atomic_json(self.directory/'status.json',{'state':'cancelled','completed':completed,'total':config['total_seasons'],'run_id':self.directory.name})
        return result

    def summarize(self,result):
        for case in result['cases']:
            seasons=[s for d in case['drafts'] for s in d['seasons']]
            if not seasons:continue
            summary={}
            for team in self.data.teams:
                outcomes=[s['teams'][team] for s in seasons]
                projections=[d['projected'][team]['rank'] for d in case['drafts'] if d['seasons']]
                summary[team]={'projected_rank':statistics.mean(projections),
                    'simulated_regular_rank':distribution([o['regular_rank'] for o in outcomes]),
                    'simulated_finish':distribution([o['finish'] for o in outcomes]),
                    'qualification_rate':statistics.mean(o['qualified'] for o in outcomes),
                    'semifinal_rate':statistics.mean(o['semifinal'] for o in outcomes),
                    'final_rate':statistics.mean(o['final'] for o in outcomes),
                    'title_rate':statistics.mean(o['champion'] for o in outcomes),
                    'conditional_title_rate':(statistics.mean(o['champion'] for o in outcomes)/
                        statistics.mean(o['qualified'] for o in outcomes)) if any(o['qualified'] for o in outcomes) else 0.,
                    'mean_advancement':statistics.mean(advancement(o) for o in outcomes),
                    'advancement_distribution':distribution([advancement(o) for o in outcomes]),
                    'mean_adds':statistics.mean(o['adds'] for o in outcomes),
                    'mean_starts':statistics.mean(o['starts'] for o in outcomes),
                    'mean_blocked_games':statistics.mean(o['blocked_games'] for o in outcomes),
                    'mean_il_player_days':statistics.mean(o['il_player_days'] for o in outcomes),
                    'mean_injured_active_days':statistics.mean(o['injured_active_days'] for o in outcomes),
                    'mean_fab_spent':statistics.mean(o['budget_spent'] for o in outcomes)}
            case['summary']=summary;case['n_seasons']=len(seasons)
            case['distinct_own_rosters']=len({tuple(sorted(d['draft']['rosters']['Oscar'])) for d in case['drafts']})
            case['own_title_interval']=cluster_interval(case['drafts'],'champion',result['config']['seed'])
            case['own_advancement_interval']=cluster_interval(case['drafts'],'advancement',result['config']['seed'],lambda s:advancement(s['teams']['Oscar']))

    @staticmethod
    def _metric_blocks(a,b,extract):
        # Positive = a (the winner) ahead of b (the runner-up) on `extract`.
        blocks=[]
        for da,db in zip(a['drafts'],b['drafts']):
            row=[extract(x['teams']['Oscar'])-extract(y['teams']['Oscar']) for x,y in zip(da['seasons'],db['seasons'])]
            if row:blocks.append(row)
        return blocks

    @staticmethod
    def _advancement_blocks(a,b):
        return BenchmarkRunner._metric_blocks(a,b,advancement)

    @staticmethod
    def _bootstrap(blocks,seed,comparisons=1):
        if len(blocks)<3:return {'low':None,'high':None,'method':'fewer than three draft clusters; no interval'}
        rng=random.Random(seed);boots=[]
        for _ in range(1000):boots.append(statistics.mean(v for b in rng.choices(blocks,k=len(blocks)) for v in b))
        boots.sort()
        # Multiplicity control: widen the percentile band by the number of challengers
        # compared against the winner in this case (family-wise within the case).
        q=0.025/max(1,comparisons)
        low=boots[max(0,int(q*(len(boots)-1)))];high=boots[min(len(boots)-1,int((1-q)*(len(boots)-1)))]
        method='draft-cluster bootstrap' if comparisons<=1 else f'draft-cluster bootstrap, {comparisons}-way multiplicity-adjusted'
        return {'low':low,'high':high,'method':method,'comparisons':comparisons}

    @staticmethod
    def _season_bootstrap(blocks,seed):
        """Monte-Carlo / season-luck sampling interval.

        Resamples individual season outcomes, ignoring draft clustering, so it
        isolates sampling noise from draft-to-draft (model) uncertainty.
        """
        flat=[v for b in blocks for v in b]
        if len(flat)<3:return {'low':None,'high':None,'method':'fewer than three outcomes'}
        rng=random.Random(seed)
        boots=sorted(statistics.mean(rng.choices(flat,k=len(flat))) for _ in range(1000))
        return {'low':boots[24],'high':boots[974],'method':'season-level bootstrap (Monte-Carlo / season luck)'}

    @staticmethod
    def _model_separation(by_mode):
        """How much do the compared opponent models actually differ?

        If two models produce near-identical drafts, 'agreement' between them is weak
        evidence, so we measure it instead of assuming it is informative.
        """
        modes=[m for m in by_mode if by_mode[m]]
        if len(modes)<2:return None
        overlaps=[]
        for i,m in enumerate(modes):
            for n in modes[i+1:]:
                a=by_mode[m][0];b=by_mode[n][0]
                for da,db in zip(a['drafts'],b['drafts']):
                    for team in da['draft']['rosters']:
                        A=set(da['draft']['rosters'][team]);B=set(db['draft']['rosters'][team])
                        overlaps.append(len(A&B)/13)
        if not overlaps:return None
        mean=statistics.mean(overlaps)
        return {'pairs':len(modes)*(len(modes)-1)//2,'shared_roster_share':mean,
                'informative':mean<.85,
                'note':'Models share %.0f%% of a roster on average; agreement is %s evidence.'%(
                    100*mean,'meaningful' if mean<.85 else 'weak (models barely differ)')}

    @staticmethod
    def _variance_split(case):
        """Split outcome variance into draft-to-draft vs season-to-season.

        Personas are ruled out as predictors, so the binding constraint is sampling.
        For a mean over D drafts x S seasons, Var = between/D + within/(D*S): adding a
        draft shrinks BOTH terms while adding a season shrinks only the second, so
        drafts are always at least as efficient. The split is still informative as a
        diagnostic: a high season share means the same roster finishes very
        differently depending on injury/waiver luck, which caps how much draft-day
        tuning can matter.
        """
        per_draft=[]
        for d in case['drafts']:
            values=[advancement(s['teams']['Oscar']) for s in d['seasons']]
            if values:per_draft.append(values)
        if len(per_draft)<2:return None
        means=[statistics.mean(v) for v in per_draft]
        between=statistics.pvariance(means)
        within=statistics.mean([statistics.pvariance(v) for v in per_draft if len(v)>1] or [0.])
        total=between+within
        if total<=0:return None
        return {'between_draft':between,'within_draft':within,'draft_share':between/total,
                'season_share':within/total,
                'reading':'Most of the spread is season luck (injuries/waivers), so draft-day differences are second-order.' if within>between else 'Most of the spread is draft luck, so who you end up with drives the outcome.',
                'advice':'Increase DRAFTS rather than seasons per draft: drafts shrink both variance components, seasons only one.'}

    @staticmethod
    def recommendation(result,seed):
        """One transparent call, chosen on the primary model and stress-tested on the
        others by agreement. Ranked on UNCONDITIONAL championship probability with
        advancement/qualification as supporting metrics. Opponent models are never
        averaged or weighted: their relative realism is unvalidated, so we require
        rank stability instead."""
        config=result['config'];modes=list(config['opponent_modes'])
        primary=next((m for m in OPPONENT_PREFERENCE if m in modes),modes[0] if modes else None)
        scenarios=[s['name'] for s in config['asset_scenarios']]
        def rates(case):
            seasons=[s for d in case['drafts'] for s in d['seasons']]
            if not seasons:return None
            title=statistics.mean(bool(s['teams']['Oscar']['champion']) for s in seasons)
            advance=statistics.mean(advancement(s['teams']['Oscar']) for s in seasons)
            qual=statistics.mean(bool(s['teams']['Oscar']['qualified']) for s in seasons)
            return {'title_rate':title,'advancement':advance,'qualification_rate':qual,
                    'conditional_title_rate':title/qual if qual else 0.}
        # PRIMARY objective: UNCONDITIONAL championship probability. Advancement,
        # conditional title probability and qualification rate are supporting metrics.
        def metric(case):
            r=rates(case)
            if r is None:return (float('-inf'),)*4
            return (r['title_rate'],r['advancement'],r['conditional_title_rate'],r['qualification_rate'])
        per_case=[]
        for scenario in scenarios:
            cases=[c for c in result['cases'] if c['asset_scenario']==scenario and c.get('summary')]
            if not cases:continue
            by_mode={}
            for c in cases:by_mode.setdefault(c['opponent_mode'],[]).append(c)
            if all(len(c['drafts'])<1 for c in cases):continue
            primary_cases=sorted(by_mode.get(primary,[]),key=metric,reverse=True) or sorted(cases,key=metric,reverse=True)
            winner=primary_cases[0];runner=primary_cases[1] if len(primary_cases)>1 else None
            mode_winners={mode:max(cs,key=metric)['strategy']['name'] for mode,cs in by_mode.items()}
            drafts=min(len(c['drafts']) for c in cases)
            separation=BenchmarkRunner._model_separation(by_mode)
            variance=BenchmarkRunner._variance_split(winner)
            wr=rates(winner)
            gap_adv=gap_title=None;adv_interval=title_interval=None
            tie=False;decisive=contested=0;mc_interval=None;equivalence=None
            comparisons=max(1,len(primary_cases)-1)
            if runner is not None:
                # Championship probability is the primary paired comparison; the
                # advancement comparison is retained as a supporting read.
                title_blocks=BenchmarkRunner._metric_blocks(winner,runner,lambda o:float(bool(o['champion'])))
                adv_blocks=BenchmarkRunner._metric_blocks(winner,runner,advancement)
                gap_title=statistics.mean(v for b in title_blocks for v in b)
                gap_adv=statistics.mean(v for b in adv_blocks for v in b)
                title_interval=BenchmarkRunner._bootstrap(title_blocks,seed,comparisons)
                adv_interval=BenchmarkRunner._bootstrap(adv_blocks,seed,comparisons)
                mc_interval=BenchmarkRunner._season_bootstrap(title_blocks,seed)
                # How many draft clusters actually carry a championship signal? A lead
                # resting on one or two decisive clusters is not a reliable winner.
                contested=sum(1 for b in title_blocks if statistics.mean(b)!=0)
                decisive=sum(1 for b in title_blocks if statistics.mean(b)>0)
                tie=title_interval['low'] is None or title_interval['low']<=0
                margin=EQUIVALENCE_MARGIN
                within=(title_interval['low'] is not None and
                        title_interval['low']>=-margin and title_interval['high']<=margin)
                spans_zero=(title_interval['low'] is None or title_interval['low']<=0<=title_interval['high'])
                # A difference is only UNPROVEN (spans zero) unless the WHOLE interval
                # sits inside the predefined practical margin, which is statistically
                # supported equivalence — not merely a failure to detect a difference.
                equivalence={'margin':margin,'supported':within,
                    'mode':'equivalent' if within else ('unresolved' if spans_zero else 'different'),
                    'note':('Statistically equivalent within the predefined \u00b1%d-point practical margin (the whole paired interval is inside it).'%(int(margin*100))
                            if within else ('No difference established: the paired interval includes zero but is wider than the practical margin.'
                                            if spans_zero else None))}
            distinct_winner=len(set(mode_winners.values()))==1
            per_case.append({'assets':scenario,'primary_model':primary,
                'primary_metric':'unconditional championship probability',
                'tested_models':sorted(by_mode),'n_strategies':len(primary_cases),'drafts':drafts,
                'model_separation':separation,'variance_split':variance,
                'winner':winner['strategy']['name'],
                'winner_title_rate':wr['title_rate'],'winner_advancement':wr['advancement'],
                'winner_conditional_title_rate':wr['conditional_title_rate'],
                'winner_qualification_rate':wr['qualification_rate'],
                'winner_interval':winner.get('own_title_interval'),
                'runner_up':runner['strategy']['name'] if runner else None,
                'gap_title':gap_title,'gap_title_interval':title_interval,
                'gap_title_interval_mc':mc_interval,
                'gap_advancement':gap_adv,'gap_interval':adv_interval,
                'comparisons':comparisons,'equivalence':equivalence,
                'interval_includes_zero':tie,
                'decisive_title_clusters':decisive,'contested_title_clusters':contested,
                'stable_across_models':distinct_winner,'model_winners':mode_winners,
                'ordering':[(c['strategy']['name'],round(metric(c)[0],2)) for c in primary_cases]})
        if not per_case:
            return {'status':'pending','message':'No completed seasons yet. Run or resume a benchmark first.'}
        wins={p['winner'] for p in per_case}
        min_drafts=min(p['drafts'] for p in per_case)
        stable=all(p['stable_across_models'] for p in per_case)
        # Confidence is deliberately conservative. Title-driven samples are noisy;
        # a firm call needs enough independent drafts AND model agreement AND a gap
        # whose interval excludes zero.
        single=all(p['n_strategies']<2 for p in per_case)
        winner_name=next(iter(wins)) if len(wins)==1 else None
        lead=per_case[0]['winner'] if per_case else None
        # Agreement only counts as robustness if the models actually differ.
        informative=all((p['model_separation'] is None or p['model_separation']['informative']) for p in per_case)
        sparse=any(p['decisive_title_clusters']<MIN_DECISIVE_CLUSTERS for p in per_case)
        if single:
            status='baseline';headline='Only one strategy was tested; nothing to compare.'
        elif len(wins)>1:
            status='inconclusive';headline='The best strategy differs by asset scenario, so no single recommendation is justified.'
        elif min_drafts<3:
            status='inconclusive';headline=f'Only {min_drafts} draft(s) per case. Increase drafts to at least 3 for a defensible comparison.'
        elif any(p['equivalence'] and p['equivalence']['supported'] for p in per_case):
            status='equivalent';headline=f'{lead} and the next-best strategy are statistically equivalent within the predefined \u00b1{int(EQUIVALENCE_MARGIN*100)}-point practical margin. Treat them as tied and decide on robustness, roster fit and risk.'
        elif not informative:
            status='lean';headline=f'{lead} leads, but the selected opponent models barely differ, so agreement between them is weak evidence. Add a structurally different model (e.g. strict ADP) as a sensitivity.'
        elif not stable:
            status='lean';headline=f'{lead} leads the primary model on championship rate, but the ranking flips on another opponent model, so it is not robust.'
        elif sparse:
            status='lean';headline=f'{lead} has the highest championship rate, but its lead rests on fewer than {MIN_DECISIVE_CLUSTERS} decisive draft clusters. Increase independent drafts before trusting it.'
        elif any(p['interval_includes_zero'] for p in per_case):
            status='lean';headline=f'{lead} leads on the point estimate, but the paired interval includes zero \u2014 no difference is established at this sample size.'
        else:
            status='strong';headline=f'Use {lead}: leads on unconditional championship probability with a positive paired interval, decisive across drafts, and agrees across opponent models.'
        advice=[p['variance_split']['reading'] for p in per_case if p['variance_split']]
        return {'status':status,'headline':headline,'winner':winner_name,'primary_leader':lead,
                'basis':primary,'primary_metric':'unconditional championship probability',
                'seed_block':config.get('seed_block'),'holdout':config.get('holdout'),
                'equivalence_margin':EQUIVALENCE_MARGIN,
                'case_results':per_case,
                'sampling_advice':advice[0] if advice else None,
                'draft_efficiency':'Increase DRAFTS rather than seasons per draft: drafts shrink both variance components, seasons only one.',
                'caveats':['Simulated comparison under stated assumptions, NOT real-world championship odds.',
                           'Ranked on UNCONDITIONAL championship probability; advancement, conditional title probability and qualification rate are supporting metrics.',
                           'Manager-specific personas failed validation, so opponent behaviour is modelled as ADP-driven rather than personality-driven. The recommendation therefore does not depend on guessing individual manager quirks.',
                           'Opponent models are treated as robustness checks, not averaged: their relative realism is unvalidated, and agreement is only counted when the models genuinely differ.',
                           'Championship samples are noisy; a firm call requires at least '+str(MIN_DECISIVE_CLUSTERS)+' decisive draft clusters and a paired interval that excludes zero.',
                           'Paired intervals are widened for the number of strategies compared (multiplicity control); the season-level (Monte-Carlo) interval is reported separately from the draft-cluster (model) interval.',
                           'An interval that spans zero means no difference is established \u2014 not that the strategies are equivalent. Equivalence is only claimed when the whole paired interval sits inside the predefined \u00b1'+str(int(EQUIVALENCE_MARGIN*100))+'-point practical margin.',
                           'Confidence \u2018strong\u2019 only means the point ranking is stable, the models genuinely differ, and the paired interval excludes zero; it is not a probability the strategy is truly best.']}

    @staticmethod
    def paired_comparisons(result,seed):
        groups={}
        for c in result['cases']:groups.setdefault((c['asset_scenario'],c['opponent_mode']),[]).append(c)
        comparisons=[]
        for (assets,mode),cases in groups.items():
            baseline=cases[0]
            for other in cases[1:]:
                title_blocks=[];adv_blocks=[]
                for a,b in zip(baseline['drafts'],other['drafts']):
                    title_blocks.append([float(y['teams']['Oscar']['champion'])-float(x['teams']['Oscar']['champion']) for x,y in zip(a['seasons'],b['seasons'])])
                    adv_blocks.append([advancement(y['teams']['Oscar'])-advancement(x['teams']['Oscar']) for x,y in zip(a['seasons'],b['seasons'])])
                title_blocks=[b for b in title_blocks if b];adv_blocks=[b for b in adv_blocks if b]
                if not title_blocks:continue
                delta=statistics.mean(v for b in title_blocks for v in b)
                adv_delta=statistics.mean(v for b in adv_blocks for v in b)
                rng=random.Random(seed);boots=[]
                if len(title_blocks)>=3:
                    for _ in range(1000):boots.append(statistics.mean(v for b in rng.choices(title_blocks,k=len(title_blocks)) for v in b))
                    boots.sort();interval=[boots[24],boots[974]]
                else:interval=[-1.,1.]
                adv_interval=BenchmarkRunner._bootstrap(adv_blocks,seed)
                comparisons.append({'assets':assets,'opponent_mode':mode,'reference':baseline['strategy']['name'],
                    'strategy':other['strategy']['name'],'paired_title_rate_difference':delta,
                    'paired_advancement_difference':adv_delta,
                    'advancement_interval':[adv_interval['low'],adv_interval['high']],
                    'draft_cluster_95_interval':interval,
                    'title_supported':interval[0]>0,
                    'advancement_supported':adv_interval['low'] is not None and adv_interval['low']>0,
                    # Primary criterion is UNCONDITIONAL championship probability.
                    'supported_improvement':interval[0]>0,
                    'warning':'Assumption-dependent, few draft clusters; not a calibrated real-world confidence interval.'})
        return comparisons
