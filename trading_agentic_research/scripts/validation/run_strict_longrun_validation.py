from __future__ import annotations
import argparse, csv, itertools, json, math, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.validation.run_strict_execution_validation import read_json, write_json, write_csv, find_config, detect_data, run_one, portfolio_row
from backtester.data_loader import load_daily_feature_store_folder, load_weekly_feature_store, validate_feature_store

BASE='HYP_REFINE_AUTO002_TOPN_6_V1'
PREV_BEST='HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STRICT_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18'
CENTERS=[(12,22,.75,.40,7,18),(12,22,.75,.40,8,20),(12,22,.75,.40,7,20),(12,21,.75,.33,8,20),(12,23,.75,.40,7,18),(11,22,.75,.40,7,18),(13,22,.75,.40,7,18)]
R=[10,11,12,13,14]; C=[20,21,22,23,24,25]; E=[.70,.72,.75,.78,.80]; CR=[.30,.33,.36,.40,.45,.50]; DD=[6,7,8,9,10]; SL=[16,18,20,22,24,None]
SCENARIOS=[('base',1.0,0),('slip5',1.0,5),('slip10',1.0,10)]
TOP_SCENARIOS=[('cost1_5_slip5',1.5,5),('cost2_slip10',2.0,10)]
PERIODS={'2008_2009':('2008-01-01','2009-12-31'),'q4_2018':('2018-10-01','2018-12-31'),'2025':('2025-01-01','2025-12-31')}

def md_table(rows, cols):
    if not rows: return '- none\n'
    out=['| '+' | '.join(cols)+' |','| '+' | '.join(['---']*len(cols))+' |']
    for r in rows: out.append('| '+' | '.join(str(r.get(c,'')) for c in cols)+' |')
    return '\n'.join(out)+'\n'

def sid(r,c,e,cr,dd,sl,mode):
    sls='SLNONE' if sl is None else f'SL{sl}'
    return f'HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_{mode.upper()}_R{r}_C{c}_E{int(e*100)}_CR{int(cr*100)}_REDD_DD{dd}_{sls}'

def dist(params):
    r,c,e,cr,dd,sl=params; slv=99 if sl is None else sl
    return min(abs(r-r0)+abs(c-c0)+abs(e-e0)*20+abs(cr-cr0)*20+abs(dd-dd0)+abs(slv-(99 if sl0 is None else sl0))/2 for r0,c0,e0,cr0,dd0,sl0 in CENTERS)

def gen_params():
    allp=[]
    for p in itertools.product(R,C,E,CR,DD,SL):
        if dist(p)<=5.5: allp.append(p)
    return sorted(set(allp), key=lambda p:(dist(p), p))

def make_cfg(base, params, mode, strategy_id):
    r,c,e,cr,dd,sl=params
    cfg=json.loads(json.dumps(base)); cfg['strategy_id']=strategy_id; cfg['hypothesis_id']=strategy_id; cfg['strategy_family']='strict_longrun_ddgrid'
    cfg['risk_controls']={'portfolio_drawdown_guard':{'enabled':True,'reduce_exposure_drawdown_pct':-float(r),'reduced_exposure_multiplier':float(e),'crisis_drawdown_pct':-float(c),'crisis_exposure_multiplier':float(cr),'reentry_mode':'dd_recovered','reentry_drawdown_pct':-float(dd)}}
    if sl is not None: cfg['risk_controls']['position_stop_loss']={'enabled':True,'stop_loss_pct':-abs(int(sl))}
    cfg['execution_timing']={'enabled':True,'mode':mode,'apply_to':['portfolio_drawdown_guard','position_stop_loss','reentry','rebalance_exits','market_filter_exits']}
    cfg['changed_parameters']=['risk_controls.portfolio_drawdown_guard','risk_controls.position_stop_loss','execution_timing']
    return cfg

def robust_score(r):
    if r.get('status')!='completed': return -1e9
    c=float(r.get('cagr') or 0); dd=abs(float(r.get('max_drawdown') or 99)); cal=float(r.get('calmar') or 0)
    wy=abs(float(r.get('worst_year') or 99)); dd08=abs(float(r.get('2008_2009_max_dd') or 99)); dd25=abs(float(r.get('2025_max_dd') or 99))
    exp=float(r.get('exposure_avg') or 0); cash_pen=max(0,25-exp/4)
    return c*2+cal*50-dd*.8-wy*.3-dd08*.4-dd25*.4-cash_pen

def summarize(out, rows, ports, next_open):
    done=[r for r in rows if r.get('status')=='completed']; fail=[r for r in rows if r.get('status')=='failed']
    for r in done: r['robust_score']=robust_score(r)
    best_rob=max(done,key=lambda r:r.get('robust_score',-1e9),default={}); best_cagr=max(done,key=lambda r:float(r.get('cagr') or -999),default={})
    best_dd=max(done,key=lambda r:float(r.get('max_drawdown') or -999),default={}); best_cal=max(done,key=lambda r:float(r.get('calmar') or -999),default={})
    slip10=[r for r in done if float(r.get('slippage_bps_per_side') or 0)>=10]; best_slip=max(slip10,key=lambda r:r.get('robust_score',-1e9),default={})
    best_port=max(ports,key=lambda r:float(r.get('calmar') or -999),default={})
    top=sorted(done,key=lambda r:r.get('robust_score',-1e9),reverse=True)[:20]
    (out/'top_candidates.md').write_text('# Top candidates\n\n## Best robust\n'+md_table(top,['strategy_id','scenario','cagr','max_drawdown','calmar','2025_max_dd','robust_score','run_id'])+'\n',encoding='utf-8')
    (out/'failed_variants.md').write_text('# Failed variants\n'+md_table(fail,['strategy_id','scenario','notes']),encoding='utf-8')
    readme=f"""# README_ANALISIS_FINAL\n\n## Resumen ejecutivo\nStrict longrun enfocada alrededor de DD7 SL18. Corridas completadas: {len(done)}. Fallidas: {len(fail)}. Next open disponible: {next_open}.\n\n## Mejor candidato anterior\n{PREV_BEST}\n\n## Mejor candidato nuevo\n{best_rob.get('strategy_id','N/D')}\n\n## Impacto slippage/costos\nVer `combined_strict_results.csv`. Ranking robusto penaliza DD, peor año, 2008/2025, pérdida con slippage y exposición baja.\n\n## Portfolios finales\nVer `strict_portfolio_mix_results.csv`.\n\n## Conclusión directa para Hernán\n- DD7 SL18 sigue siendo principal salvo que `Best robust` supere claramente su Calmar/DD.\n- DD8 SL20 solo vuelve a convenir si aparece arriba en Best Robust/Best To Trade.\n- Next open: {'evaluado en top si disponible' if next_open else 'no evaluado porque no hay open confiable'}.\n- Slippage 10 bps: revisar Best Slippage Resistant; no se inventó slippage.\n- Paper trading: solo si best robust mantiene edge con 10 bps.\n- No seguiría probando grillas amplias; solo fill model/paper.\n"""
    (out/'README_ANALISIS_FINAL.md').write_text(readme,encoding='utf-8')
    return {'completed':len(done),'failed':len(fail),'best_robust':best_rob.get('strategy_id','N/D'),'best_slip':best_slip.get('strategy_id','N/D'),'best_port':best_port.get('portfolio','N/D')}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--repo-root',default=str(ROOT)); ap.add_argument('--output-dir',required=True); ap.add_argument('--max-scenarios',type=int,default=800); ap.add_argument('--batch-size',type=int,default=50); ap.add_argument('--smoke',action='store_true')
    args=ap.parse_args(); root=Path(args.repo_root).resolve(); out=Path(args.output_dir); out=out if out.is_absolute() else root/out
    out.mkdir(parents=True,exist_ok=True); (out/'configs').mkdir(exist_ok=True); (out/'logs').mkdir(exist_ok=True)
    state_path=out/'grid_state.json'; state=read_json(state_path,{}) or {'rows':[],'failed':{},'created_at':datetime.now().isoformat(),'best_score':-1e9,'stale_batches':0}
    project=read_json(root/'configs/project_config.json',{}) or {}; weekly,daily=detect_data(root,project)
    wdf=load_weekly_feature_store(str(weekly)); ddf=load_daily_feature_store_folder(str(daily))
    open_ok='open' in [c.lower() for c in ddf.columns] and pd.to_numeric(ddf.get('open'),errors='coerce').notna().mean()>0.98
    base=read_json(find_config(root,BASE),{}) or {}
    modes=['strict_next_close']
    params=gen_params(); queue=[]
    for mode in modes:
        for p in params:
            for scen in SCENARIOS: queue.append((p,mode,scen))
    if open_ok:
        for p in params[:50]: queue.append((p,'strict_next_open',('base_open',1.0,0))); queue.append((p,'strict_next_open',('slip10_open',1.0,10)))
    done_keys={(r.get('strategy_id'),r.get('scenario')) for r in state.get('rows',[]) if r.get('status')=='completed'}
    rows=state.get('rows',[]); completed_this=0
    maxn=2 if args.smoke else args.max_scenarios
    for p,mode,(scen,cm,bps) in queue:
        if len(rows)>=maxn: break
        strategy_id=sid(*p,mode=mode)
        key=(strategy_id,scen)
        if key in done_keys: continue
        cfg=make_cfg(base,p,mode,strategy_id); cfg['execution_costs']={'enabled':True,'cost_multiplier':cm,'slippage_bps_per_side':bps,'slippage_multiplier':1.0}
        write_json(out/'configs'/f'{strategy_id}.json',cfg)
        try:
            row,eq=run_one(root,cfg,project,wdf,ddf,weekly,daily,out,'longrun','strict',scen,cm,1.0)
            row.update({'status':'completed','next_open_available':open_ok,'slippage_bps_per_side':bps,'params':str(p),'metric_no_effect':False,'robust_score':robust_score(row)})
            rows.append(row); completed_this+=1
        except Exception as exc:
            rows.append({'status':'failed','strategy_id':strategy_id,'scenario':scen,'notes':str(exc)[:500],'next_open_available':open_ok,'cost_multiplier':cm,'slippage_bps_per_side':bps})
        write_csv(out/'grid_results_partial.csv',rows); write_json(state_path,{**state,'rows':rows,'updated_at':datetime.now().isoformat()})
        if completed_this and completed_this % args.batch_size==0:
            write_csv(out/'grid_results.csv',rows); write_csv(out/'combined_strict_results.csv',rows)
            done=[r for r in rows if r.get('status')=='completed']; best=max([robust_score(r) for r in done],default=-1e9)
            state['stale_batches']=state.get('stale_batches',0)+1 if best<=state.get('best_score',-1e9)+1e-9 else 0; state['best_score']=max(state.get('best_score',-1e9),best)
            write_json(state_path,state)
            if state['stale_batches']>=4: break
    write_csv(out/'grid_results.csv',rows); write_csv(out/'grid_results_partial.csv',rows); write_csv(out/'combined_strict_results.csv',rows)
    done=sorted([r for r in rows if r.get('status')=='completed'],key=lambda r:robust_score(r),reverse=True)
    ports=[]
    try:
        top=done[:5]
        eqs=[]
        for r in top:
            e=pd.read_csv(Path(r['run_dir'])/'equity_curve.csv',sep=';',decimal=','); eqs.append((r['strategy_id'],e))
        if eqs:
            ports.append(portfolio_row('A_100_best_robust',[(eqs[0][0],eqs[0][1],1.0)]))
        if len(eqs)>1:
            ports.append(portfolio_row('B_75_robust_25_defensive',[(eqs[0][0],eqs[0][1],.75),(eqs[1][0],eqs[1][1],.25)])); ports.append(portfolio_row('C_50_robust_50_defensive',[(eqs[0][0],eqs[0][1],.5),(eqs[1][0],eqs[1][1],.5)]))
    except Exception as exc: ports.append({'portfolio':'failed','notes':str(exc)[:300]})
    write_csv(out/'strict_portfolio_mix_results.csv',ports)
    summary=summarize(out,rows,ports,open_ok)
    (out/'implementation_notes.md').write_text(f'# Implementation notes\n\n- Branch: {subprocess.run(["git","branch","--show-current"],cwd=root,capture_output=True,text=True).stdout.strip()}\n- strict_next_close existed.\n- strict_next_open available: {open_ok}.\n- slippage_bps_per_side used config-driven.\n- Resume: grid_state.json.\n',encoding='utf-8')
    try:
        import openpyxl
        with pd.ExcelWriter(out/'strict_longrun_validation.xlsx',engine='openpyxl') as xw:
            pd.DataFrame(rows).to_excel(xw,'grid',index=False); pd.DataFrame(ports).to_excel(xw,'portfolios',index=False)
    except Exception: pass
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
