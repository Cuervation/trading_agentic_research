from __future__ import annotations
from pathlib import Path
import json

class PaperStateStore:
    def __init__(self, run_dir: Path): self.run_dir=Path(run_dir); self.path=self.run_dir/'paper_state.json'; self.run_dir.mkdir(parents=True,exist_ok=True)
    def initial(self, cash: float, config_hash: str):
        return {'cash':float(cash),'positions':{},'equity':float(cash),'peak_equity':float(cash),'drawdown_pct':0.0,'orders_pending':[],'last_day_processed':None,'config_hash':config_hash}
    def load(self):
        if not self.path.exists(): return None
        return json.loads(self.path.read_text(encoding='utf-8'))
    def save(self, state: dict): self.path.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8')
