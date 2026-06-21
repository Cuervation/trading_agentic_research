from __future__ import annotations
import argparse, hashlib, json, sys, warnings
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backtester.signal_builder import build_momentum_trend_signals
from scripts.paper_trading.paper_data_provider import PaperDataProvider
from scripts.paper_trading.paper_broker import PaperBroker
from scripts.paper_trading.paper_state_store import PaperStateStore
from scripts.paper_trading.paper_reporter import PaperReporter

REQUIRED_FILES=['paper_manifest.json','paper_config_snapshot.json','paper_state.json','daily_monitoring.csv','signals.csv','orders.csv','fills.csv','positions.csv','equity_curve.csv','warnings.log','summary.md']

def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def canonical_hash(cfg):
    c=json.loads(json.dumps(cfg,sort_keys=True)); c.pop('config_hash',None)
    return hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def assert_safe(cfg, lock):
    if cfg.get('paper_mode') is not True: raise SystemExit('paper_mode must be true')
    if cfg.get('allow_live_orders') is not False: raise SystemExit('allow_live_orders must be false')
    h=canonical_hash(cfg)
    if h != lock.get('config_hash') or h != cfg.get('config_hash'): raise SystemExit('config hash mismatch')
    text=json.dumps(cfg).lower()
    for bad in ['api_key','secret','token','live_broker','alpaca','interactivebrokers','binance']:
        if bad in text: raise SystemExit(f'forbidden live/credential marker: {bad}')
    return h

def price_positions(provider, positions, date):
    d=provider.daily_until(date).sort_values('date').groupby('ticker').tail(1)
    px={r.ticker:float(r.close) for r in d.itertuples() if pd.notna(r.close)}
    return sum(float(pos['shares'])*px.get(t,0.0) for t,pos in positions.items())

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--repo-root',default=str(ROOT)); ap.add_argument('--config',required=True); ap.add_argument('--lock',required=True); ap.add_argument('--paper-run-id',default=''); ap.add_argument('--start',required=True); ap.add_argument('--end',required=True); ap.add_argument('--resume',action='store_true'); ap.add_argument('--warmup-market-days',type=int,default=None)
    a=ap.parse_args(); root=Path(a.repo_root).resolve(); cfg=read_json(a.config); lock=read_json(a.lock); ch=assert_safe(cfg,lock)
    run_id=a.paper_run_id or f"PAPER_{cfg['strategy_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; run_dir=root/'paper_runs'/run_id
    reporter=PaperReporter(run_dir); store=PaperStateStore(run_dir)
    if a.resume:
        state=store.load();
        if not state: raise SystemExit('resume requested but state missing')
        if state.get('config_hash')!=ch: raise SystemExit('state config hash mismatch')
    else:
        state=store.initial(float(cfg.get('initial_capital',100000)), ch)
    project=read_json(root/'configs/project_config.json'); provider=PaperDataProvider(root,project); broker=PaperBroker(float(cfg['execution_costs']['slippage_bps_per_side']))
    requested_start=pd.to_datetime(a.start); requested_end=pd.to_datetime(a.end)
    warmup_days=int(a.warmup_market_days or cfg.get('paper_warmup_market_days') or 252)
    warmup_start=provider.warmup_start(requested_start, warmup_days)
    weekly=provider.weekly_between(warmup_start, requested_end)
    warmup_rows=int((pd.to_datetime(weekly['date']) < requested_start).sum()) if not weekly.empty else 0
    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter('always')
        signals=build_momentum_trend_signals(weekly,cfg)
    raw_warning_messages=[str(w.message) for w in captured_warnings]
    warning_counts={}
    for msg in raw_warning_messages: warning_counts[msg]=warning_counts.get(msg,0)+1
    signals=signals[(pd.to_datetime(signals.signal_date)>=requested_start) & (pd.to_datetime(signals.signal_date)<=requested_end)].copy()
    eligible=weekly[pd.to_datetime(weekly['date'])<=requested_start].copy()
    latest_snapshot=eligible[eligible['date'].eq(eligible['date'].max())] if not eligible.empty else eligible
    spy_rows=latest_snapshot[latest_snapshot['ticker'].astype(str).eq('SPY')].sort_values('date')
    spy_metrics_available_on_start=False; spy_metric_cause='no_weekly_snapshot_before_or_on_start'
    tried=['spy_close_vs_sma50_pct','close_vs_sma50_pct','close_vs_sma52w_pct']
    if not latest_snapshot.empty:
        ctx=spy_rows.iloc[0] if not spy_rows.empty else latest_snapshot.iloc[0]
        vals={c:(ctx[c] if c in ctx.index else None) for c in tried}
        spy_metrics_available_on_start=any(pd.notna(v) for v in vals.values())
        if spy_metrics_available_on_start:
            spy_metric_cause='available_from_spy_prefixed_context' if spy_rows.empty else 'available_from_spy_row'
        else:
            spy_metric_cause='all_spy_trend_metrics_missing_or_nan_on_latest_weekly_snapshot'

    orders=[]; fills=[]; daily=[]; positions_rows=[]; equity_rows=[]
    cash=float(state['cash']); positions=dict(state.get('positions',{})); peak=float(state.get('peak_equity',cash)); order_id=0
    for sd,grp in signals.groupby('signal_date'):
        sd=pd.to_datetime(sd); target=set(grp.loc[grp['selected_top_n'].astype(bool),'ticker'].astype(str))
        held=set(positions); exits=held-target; entries=target-held
        submitted=filled=rejected=0; spy_fb=bool(grp['spy_filter_fallback_used'].max()) if 'spy_filter_fallback_used' in grp else False
        policy_blocked=int((grp.get('spy_filter_missing_or_nan',pd.Series(False,index=grp.index)).astype(bool) & ~grp['selected_top_n'].astype(bool)).sum()) if 'selected_top_n' in grp else 0
        for t in sorted(exits):
            order_id+=1; m=provider.next_open(t,sd); order={'order_id':order_id,'date':str(sd.date()),'ticker':t,'side':'SELL','shares':positions[t]['shares'],'PAPER':True,'reason':'left_target_or_filter'}; o,f=broker.submit(order,m); orders.append(o); submitted+=1
            if f: fills.append(f); cash+=f['shares']*f['simulated_fill_price']; positions.pop(t,None); filled+=1
            else: rejected+=1
        equity_now=cash+price_positions(provider,positions,sd); slot=max(1,len(entries)); budget=max(0.0,equity_now*0.95-cash*0)/slot if entries else 0
        for t in sorted(entries):
            m=provider.next_open(t,sd); px=(m or {}).get('price') or 0; shares=int((budget/px)) if px else 0
            if shares<=0: continue
            order_id+=1; order={'order_id':order_id,'date':str(sd.date()),'ticker':t,'side':'BUY','shares':shares,'PAPER':True,'reason':'selected_top_n'}; o,f=broker.submit(order,m); orders.append(o); submitted+=1
            if f and cash>=f['shares']*f['simulated_fill_price']:
                fills.append(f); cash-=f['shares']*f['simulated_fill_price']; positions[t]={'shares':f['shares'],'entry_price':f['simulated_fill_price'],'entry_date':f['fill_date']}; filled+=1
            else: rejected+=1
        equity=cash+price_positions(provider,positions,sd); peak=max(peak,equity); dd=(equity/peak-1)*100 if peak else 0
        row={'date':str(sd.date()),'paper_run_id':run_id,'config_hash':ch,'strategy_id':cfg['strategy_id'],'cash':cash,'equity':equity,'peak_equity':peak,'drawdown_pct':dd,'exposure_pct':((equity-cash)/equity*100 if equity else 0),'open_positions':len(positions),'pending_orders':0,'signals_generated':len(grp),'orders_submitted':submitted,'orders_filled':filled,'orders_rejected':rejected,'theoretical_price':'','simulated_fill_price':'','realized_slippage_bps':cfg['execution_costs']['slippage_bps_per_side'],'commissions':0,'spy_filter_available':not spy_fb,'spy_filter_fallback':spy_fb,'spy_policy_blocked_entries':policy_blocked,'drawdown_guard_state':'normal','crisis_mode':False,'position_stop_count':0,'reentry_count':0,'warnings':''}
        daily.append(row); equity_rows.append({'date':row['date'],'equity':equity,'cash':cash,'drawdown_pct':dd});
        for t,pos in positions.items(): positions_rows.append({'date':row['date'],'ticker':t,**pos,'PAPER':True})
    state.update({'cash':cash,'positions':positions,'equity':equity_rows[-1]['equity'] if equity_rows else cash,'peak_equity':peak,'drawdown_pct':equity_rows[-1]['drawdown_pct'] if equity_rows else 0,'last_day_processed':a.end,'config_hash':ch}); store.save(state)
    reporter.write_json('paper_manifest.json',{'paper_run_id':run_id,'PAPER':True,'strategy_id':cfg['strategy_id'],'config_hash':ch,'start':a.start,'end':a.end,'requested_start':a.start,'requested_end':a.end,'warmup_start':str(warmup_start.date()),'warmup_market_days':warmup_days,'warmup_rows':warmup_rows,'spy_metrics_available_on_start':spy_metrics_available_on_start,'spy_metric_cause':spy_metric_cause,'no_live_orders':True})
    reporter.write_json('paper_config_snapshot.json',cfg); reporter.write_csv('daily_monitoring.csv',daily); reporter.write_csv('signals.csv',signals.to_dict('records')); reporter.write_csv('orders.csv',orders); reporter.write_csv('fills.csv',fills); reporter.write_csv('positions.csv',positions_rows); reporter.write_csv('equity_curve.csv',equity_rows)
    warn_lines=[f'{cnt}x {msg}' for msg,cnt in sorted(warning_counts.items())]
    (run_dir/'warnings.log').write_text('\n'.join(warn_lines)+('\n' if warn_lines else ''),encoding='utf-8')
    (run_dir/'summary.md').write_text(f"# Paper run {run_id}\n\nPAPER only. Orders: {len(orders)}. Fills: {len(fills)}. Config hash: {ch}.\n\nrequested_start: {a.start}\nrequested_end: {a.end}\nwarmup_start: {warmup_start.date()}\nwarmup_rows: {warmup_rows}\nspy_metrics_available_on_start: {spy_metrics_available_on_start}\nspy_metric_cause: {spy_metric_cause}\n",encoding='utf-8')
    missing=[x for x in REQUIRED_FILES if not (run_dir/x).exists()]
    print(json.dumps({'paper_run_id':run_id,'run_dir':str(run_dir),'orders':len(orders),'fills':len(fills),'missing':missing,'warmup_start':str(warmup_start.date()),'warmup_rows':warmup_rows,'spy_metrics_available_on_start':spy_metrics_available_on_start,'warnings':len(warning_counts)},ensure_ascii=False))
if __name__=='__main__': main()

