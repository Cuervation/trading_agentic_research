from __future__ import annotations
from pathlib import Path
import csv,json

class PaperReporter:
    def __init__(self, run_dir: Path):
        self.run_dir=Path(run_dir); self.run_dir.mkdir(parents=True,exist_ok=True)
    def write_json(self,name,obj): (self.run_dir/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    def write_csv(self,name,rows):
        rows=list(rows); keys=sorted({k for r in rows for k in r}) if rows else []
        with (self.run_dir/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,keys); w.writeheader(); w.writerows(rows)
    def append_warning(self,msg):
        with (self.run_dir/'warnings.log').open('a',encoding='utf-8') as f: f.write(str(msg)+'\n')
