"""Local review application; one isolated pipeline job at a time."""
from __future__ import annotations
import argparse
import copy
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .cli import validate_config
from .sec import SecClient,RetrievalError
from .fund_browser import FundBrowser

FILES={'benchmark-evidence.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','index.html':'text/html','benchmark.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','benchmark.pdf':'application/pdf','benchmark.csv':'text/csv','audit.json':'application/json','judgments.json':'application/json','nport.json':'application/json','nport-holdings.csv':'text/csv'}


class Workspace:
    def __init__(self,root,config,report):
        self.root=Path(root).resolve();self.config_path=Path(config).resolve();self.report=Path(report).resolve()
        self.lock=threading.RLock();self.sec_lock=threading.Lock();self.token=secrets.token_urlsafe(32)
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True,exist_ok=True)
            self.config_path.write_text((self.root/'config/engagement.json').read_text())
        self.config=json.loads(self.config_path.read_text());validate_config(self.config)
        self.browser=FundBrowser(SecClient(os.environ.get('SEC_USER_AGENT','local-cache-only'),self.root/'.cache/sec'))
        self.job=None

    def save(self,config):
        validate_config(config)
        if not 1<=len(config['funds'])<=20:raise ValueError('This local prototype supports 1 to 20 comparison funds per run.')
        tmp=self.config_path.with_suffix('.tmp');tmp.write_text(json.dumps(config,indent=2)+'\n');tmp.replace(self.config_path)
        self.config=config

    def add_fund(self,data):
        with self.sec_lock:detail=self.browser.detail(str(data['cik']))
        ticker=data.get('ticker','').strip().upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,23}',ticker):raise ValueError('Provide a short ticker or comparison label, using letters, numbers, dots, dashes or underscores.')
        if data.get('structure') not in {'interval','bdc','mortgage_reit','other'}:raise ValueError('Select the fund structure')
        if data.get('return_basis') not in {'shareholder','net_nav'}:raise ValueError('Select the return basis')
        if not data.get('share_class','').strip() or len(data['share_class'])>100:raise ValueError('Specify the share class')
        fund={k:data[k] for k in ('structure','return_basis','share_class')}
        fund.update(cik=detail['cik'],name=detail['name'],ticker=ticker)
        for field,pattern in [('series_id',r'S\d+'),('class_id',r'C\d+')]:
            if data.get(field):
                if not re.fullmatch(pattern,data[field]):raise ValueError(f'Invalid {field}')
                fund[field]=data[field]
        with self.lock:
            config=copy.deepcopy(self.config)
            if any(f['ticker']==ticker for f in config['funds']):raise ValueError('This comparison label is already in the set.')
            config['funds'].append(fund);self.save(config)
        return fund

    def start(self,mode):
        if mode not in {'on','off','cached'}:raise ValueError('Unknown judgment mode')
        if mode=='on' and not os.environ.get('OPENAI_API_KEY'):raise ValueError('Configure OPENAI_API_KEY locally before running OpenAI judgment.')
        with self.lock:
            if self.job and self.job['status']=='running':raise ValueError('A run is already in progress')
            uid=uuid.uuid4().hex[:12];folder=self.root/'output/runs'/uid;folder.mkdir(parents=True)
            config_path=folder/'config.json';config_path.write_text(json.dumps(self.config,indent=2))
            result=folder/'report';log=folder/'run.log'
            args=[sys.executable,'-m','apex_benchmark.cli','--config',str(config_path),'--output',str(result),'--llm',mode]
            audit=self.report/'audit.json'
            if audit.exists():
                prior=json.loads(audit.read_text())['config']
                if {k:v for k,v in prior.items() if k!='custom_metrics'}=={k:v for k,v in self.config.items() if k!='custom_metrics'}:
                    args+=['--from-audit',str(audit)]
            if mode=='cached':args+=['--offline']
            self.job={'id':uid,'status':'running','mode':mode,'output':str(result),'log_path':str(log),'config':copy.deepcopy(self.config)}
            job=self.job
            def work():
                try:
                    with log.open('w') as stream:
                        code=subprocess.run(args,cwd=self.root,stdout=stream,stderr=subprocess.STDOUT).returncode
                    with self.lock:
                        job['exit_code']=code;job['status']='complete' if code==0 else 'review_required' if (result/'index.html').exists() else 'failed'
                        if (result/'index.html').exists():self.report=result
                except Exception:
                    with self.lock:job['status']='failed'
            threading.Thread(target=work,daemon=True).start()
            return {'id':uid,'status':'running'}

    def state(self):
        with self.lock:
            job={k:v for k,v in (self.job or {}).items() if k not in {'log_path','config'}}
            if self.job:
                p=Path(self.job['log_path']);job['log']=p.read_text()[-8000:] if p.exists() else ''
            return {'config':self.config,'job':job,'csrf':self.token,'has_report':(self.report/'index.html').exists(),
                    'has_word':(self.report/'benchmark.docx').exists(),'has_evidence_word':(self.report/'benchmark-evidence.docx').exists(),'openai_configured':bool(os.environ.get('OPENAI_API_KEY'))}


def handler(workspace):
    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            return self.headers.get('Host') in allowed and (not self.headers.get('Origin') or self.headers['Origin'] in {'http://'+h for h in allowed})
        def send(self,body,status=200,mime='application/json'):
            raw=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self.allowed():return self.send({'error':'Local same-origin access required'},403)
            path=urlparse(self.path)
            try:
                if path.path=='/':return self.send(Path(__file__).with_name('workspace.html').read_bytes(),mime='text/html; charset=utf-8')
                if path.path=='/api/state':return self.send(workspace.state())
                if path.path=='/api/search':
                    with workspace.sec_lock:result=workspace.browser.search(parse_qs(path.query).get('q',[''])[0])
                    return self.send(result)
                if path.path=='/api/fund':
                    with workspace.sec_lock:result=workspace.browser.detail(parse_qs(path.query).get('cik',[''])[0])
                    return self.send(result)
                if path.path.startswith('/report/'):
                    name=path.path[len('/report/'):] or 'index.html'
                    if name not in FILES:return self.send({'error':'Not found'},404)
                    p=workspace.report/name
                    if not p.exists():return self.send({'error':'Run the comparison to generate this output'},404)
                    return self.send(p.read_bytes(),mime=FILES[name])
                return self.send({'error':'Not found'},404)
            except (ValueError,KeyError,RetrievalError) as exc:self.send({'error':str(exc)},400)
        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),workspace.token):return self.send({'error':'Local workspace token required'},403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=100000:raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(size))
                if self.path=='/api/funds':return self.send(workspace.add_fund(data))
                if self.path=='/api/remove-fund':
                    with workspace.lock:
                        config=copy.deepcopy(workspace.config);config['funds']=[f for f in config['funds'] if f['ticker']!=data['ticker']];workspace.save(config)
                    return self.send({'saved':True})
                if self.path=='/api/metrics':
                    with workspace.lock:
                        config=copy.deepcopy(workspace.config);config['custom_metrics']=data['metrics'];workspace.save(config)
                    return self.send({'saved':True})
                if self.path=='/api/period':
                    with workspace.lock:
                        config=copy.deepcopy(workspace.config)
                        for k in ('target_period','filing_cutoff'):config[k]=data[k]
                        workspace.save(config)
                    return self.send({'saved':True})
                if self.path=='/api/run':return self.send(workspace.start(data.get('mode','on')))
                return self.send({'error':'Not found'},404)
            except (ValueError,KeyError,TypeError,RetrievalError) as exc:self.send({'error':str(exc)},400)
        def log_message(self,*args):pass
    return Handler


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv('.env')
    parser=argparse.ArgumentParser(description='Local Apex Ridge workspace')
    parser.add_argument('--port',type=int,default=8766);parser.add_argument('--config',default='config/workspace.json');parser.add_argument('--report',default='output/llm')
    args=parser.parse_args(argv);w=Workspace(Path.cwd(),args.config,args.report)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(w))
    print(f'Workspace: http://127.0.0.1:{args.port}/',flush=True)
    server.serve_forever()

if __name__=='__main__':main()
