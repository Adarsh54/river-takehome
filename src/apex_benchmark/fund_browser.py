"""Search the SEC's real entity and mutual-fund directories."""
import re
from .sec import family

COMPANIES='https://www.sec.gov/files/company_tickers.json'
FUNDS='https://www.sec.gov/files/company_tickers_mf.json'
NAMES='https://www.sec.gov/Archives/edgar/cik-lookup-data.txt'


class FundBrowser:
    def __init__(self,client):
        self.client=client;self.index=None;self.warnings=[]

    def load(self):
        if self.index is not None:return
        by_cik={};self.warnings=[]
        for item in self.client.json(COMPANIES).values():
            cik=f"{int(item['cik_str']):010d}"
            row=by_cik.setdefault(cik,{'cik':cik,'name':item['title'],'aliases':[],'tickers':[],'classes':[]})
            row['tickers'].append(item['ticker'])
        # Registrant name directory includes non-traded funds and historical names.
        from .sec import RetrievalError
        try:
            body,_=self.client.get(NAMES)
            for line in body.decode('utf-8',errors='replace').splitlines():
                match=re.fullmatch(r'(.*):(\d+):',line)
                if not match:continue
                name,cik=match.groups();cik=f'{int(cik):010d}'
                row=by_cik.setdefault(cik,{'cik':cik,'name':name,'aliases':[],'tickers':[],'classes':[]})
                row['aliases'].append(name)
        except RetrievalError:
            self.warnings.append('SEC name directory unavailable; name search is limited to ticker-directory entities. CIK lookup still works.')
        try:
            obj=self.client.json(FUNDS)
            for data in obj['data']:
                item=dict(zip(obj['fields'],data));cik=f"{int(item['cik']):010d}"
                row=by_cik.setdefault(cik,{'cik':cik,'name':'Registered investment company','aliases':[],'tickers':[],'classes':[]})
                row['tickers'].append(item['symbol']);row['classes'].append(item)
        except RetrievalError:
            self.warnings.append('SEC mutual-fund ticker directory unavailable; use registrant name or CIK.')
        self.index=list(by_cik.values())

    def detail(self,cik):
        if not re.fullmatch(r'\d{1,10}',str(cik)):raise ValueError('CIK must contain 1 to 10 digits')
        cik=f'{int(cik):010d}'
        obj=self.client.json(f'https://data.sec.gov/submissions/CIK{cik}.json')
        recent=obj.get('filings',{}).get('recent',{})
        return {'cik':cik,'name':obj.get('name',''),'tickers':obj.get('tickers',[]),
                'forms':sorted(set(recent.get('form',[]))),
                'supported_forms':sorted({f for f in recent.get('form',[]) if family(f)}),
                'sec_url':f'https://www.sec.gov/edgar/browse/?CIK={int(cik)}',
                'note':'Current directory identity. Benchmark filing dates are restricted separately by the engagement cutoff.'}

    def search(self,query):
        query=query.strip()
        if not 2<=len(query)<=100:raise ValueError('Search requires 2 to 100 characters')
        if query.isdigit():return {'results':[self.detail(query)],'warnings':[]}
        self.load();q=query.casefold()
        hits=[x for x in self.index if q in x['name'].casefold() or any(q in a.casefold() for a in x['aliases']) or any(q in t.casefold() for t in x['tickers'])]
        hits.sort(key=lambda x:(not any(q==t.casefold() for t in x['tickers']),not x['name'].casefold().startswith(q),x['name']))
        return {'results':[{k:v for k,v in x.items() if k!='aliases'} for x in hits[:30]],'total':len(hits),'warnings':self.warnings,
                'note':'SEC registrants include non-funds and former filers. Select a result to verify its current identity and filing coverage.'}
