from __future__ import annotations
from pathlib import Path
import pandas as pd
from backtester.data_loader import load_daily_feature_store_folder, load_weekly_feature_store
from scripts.validation.run_strict_execution_validation import detect_data

class PaperDataProvider:
    def __init__(self, repo_root: Path, project_config: dict):
        self.repo_root=Path(repo_root); self.project_config=project_config
        self.weekly_path,self.daily_path=detect_data(self.repo_root, project_config)
        self.weekly=load_weekly_feature_store(str(self.weekly_path)); self.daily=load_daily_feature_store_folder(str(self.daily_path))
        self.weekly['date']=pd.to_datetime(self.weekly['date']); self.daily['date']=pd.to_datetime(self.daily['date'])
    def warmup_start(self, start, market_days: int=252):
        start=pd.to_datetime(start)
        dates=sorted(pd.to_datetime(self.daily.loc[self.daily['date']<start,'date']).dropna().unique())
        if len(dates)>=market_days: return pd.to_datetime(dates[-market_days])
        return pd.to_datetime(dates[0]) if dates else start
    def weekly_until(self, date): return self.weekly[self.weekly['date']<=pd.to_datetime(date)].copy()
    def weekly_between(self, start, end):
        s=pd.to_datetime(start); e=pd.to_datetime(end)
        return self.weekly[(self.weekly['date']>=s)&(self.weekly['date']<=e)].copy()
    def daily_until(self, date): return self.daily[self.daily['date']<=pd.to_datetime(date)].copy()
    def daily_between(self,start,end):
        s=pd.to_datetime(start); e=pd.to_datetime(end)
        return self.daily[(self.daily['date']>=s)&(self.daily['date']<=e)].copy()
    def next_open(self, ticker: str, after_date):
        d=self.daily[(self.daily['ticker'].eq(ticker)) & (self.daily['date']>pd.to_datetime(after_date))].sort_values('date')
        if d.empty: return None
        r=d.iloc[0]; px=r.get('open', None)
        if pd.isna(px): px=r.get('close', None)
        if pd.isna(px): return None
        return {'date':str(pd.to_datetime(r['date']).date()), 'price':float(px), 'open_available':not pd.isna(r.get('open', None))}
