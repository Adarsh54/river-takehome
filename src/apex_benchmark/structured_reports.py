"""Date-aligned financial tables and transparent total-return calculations."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import math
import re
from bs4 import BeautifulSoup
from .extract import candidate, clean, number


def cells_with_positions(row):
    cells=[];pos=0
    for cell in row.find_all(['td','th'],recursive=False):
        span=int(cell.get('colspan',1))
        cells.append((pos,pos+span,clean(cell.get_text(' ',strip=True))))
        pos+=span
    return cells


def numeric_columns(row, headers, include_text=False):
    """A date heading governs its column group up to the next date heading."""
    ordered=sorted(headers)
    cells=cells_with_positions(row)
    values={}
    for i,(start,label) in enumerate(ordered):
        end=ordered[i+1][0] if i+1<len(ordered) else max((b for _,b,_ in cells),default=start)
        text=''.join(t for a,b,t in cells if start<=a<end)
        value=number(re.sub(r'[xX]$','',re.sub(r'\s+','',text)))
        if value is not None:
            values[label]={'value':value,'raw':text} if include_text else value
    return values


def table_headers(table, report_period, annual):
    """Use explicit dates first; annual year columns use the report's fiscal end."""
    exact=[];years=[]
    for row_index,row in enumerate(table.find_all('tr')):
        row_years=[]
        for start,end,text in cells_with_positions(row):
            for fmt in ['%m/%d/%Y','%B %d, %Y']:
                try:
                    parsed=datetime.strptime(text,fmt).date().isoformat()
                except ValueError:
                    continue
                exact.append((start,parsed));break
            if row_index<6 and len(text)<150 and re.match(r'(?:For the |Six |Year |Period)',text,re.I):
                embedded=re.findall(r'[A-Z][a-z]+ \d{1,2}, \d{4}',text)
                if embedded:
                    exact.append((start,datetime.strptime(embedded[-1],'%B %d, %Y').date().isoformat()))
            if re.fullmatch(r'20\d{2}',text):
                row_years.append((start,text))
        if len(row_years)>len(years):years=row_years
    if len(exact)>=2:
        return list(dict.fromkeys(exact))
    if annual and len(years)>=2 and len({y for _,y in years})==len(years):
        return [(start,year+report_period[4:]) for start,year in years]
    return []


def annualized_return(returns):
    if not returns or any(r<=-100 for r in returns):
        raise ValueError('Return series must have positive growth factors')
    return (math.prod(1+r/100 for r in returns)**(1/len(returns))-1)*100


def parse_financial_report(body,fund,filing,source):
    soup=BeautifulSoup(body,'lxml')
    full=clean(soup.get_text(' ',strip=True))
    period=filing.get('reportDate','')
    if not period:return []
    annual=filing['form'].removesuffix('/A') in {'10-K','N-CSR'}
    results=[]
    for index,table in enumerate(soup.find_all('table'),1):
        if table.find('table'):continue
        text=clean(table.get_text(' ',strip=True))
        if len(text)>25000:continue
        if not re.search(r'total return|book value|debt.to.equity|net asset value|KKR Real Estate Finance Trust',text,re.I):continue
        headers=table_headers(table,period,annual)
        if len(headers)<2:continue
        position=full.find(text)
        before=full[max(0,position-2500):position] if position>=0 else ''
        after=full[position+len(text):position+len(text)+3500] if position>=0 else ''
        # Explicit Class I is required in multi-class interval-fund tables.
        classes=re.findall(r'\bCLASS\s+([A-Z])\b',text)
        interval=fund['structure']=='interval'
        if interval and not classes:
            heading_classes=re.findall(r'Financial Highlights(?: \(Continued\))?\s+Class ([A-Z])',before,re.I)
            if heading_classes:classes=[heading_classes[-1].upper()]
        if interval and classes != ['I']:
            continue
        rows=table.find_all('tr')
        market=None;nav_return=None;nav=None;market_raw={};nav_raw={}
        for row in rows:
            cells=cells_with_positions(row)
            if not cells:continue
            label=cells[0][2].lower()
            values=numeric_columns(row,headers)
            if label.startswith('total return based on market value'):
                market=values
                market_raw=numeric_columns(row,headers,include_text=True)
            elif label.startswith('total return, at net asset value') or label.startswith('total return based on average net asset value'):
                nav_return=values
                nav_raw=numeric_columns(row,headers,include_text=True)
            elif re.match(r'net asset value,? (?:at )?end of period',label):
                nav=values
            if fund['ticker']=='KREF' and label.startswith('debt-to-equity ratio'):
                for end,value in values.items():
                    if end==period:
                        results.append(candidate(fund,filing,source,'leverage',value,f'HTML table {index}; dated debt/equity row',text+' '+after[:1800],
                            'dated_financial_table',period=end,basis='debt_to_equity:reported_corporate_ratio',share_class='Common',eligible=True,
                            reasons=['Reported debt/equity, distinct from the separately reported total leverage ratio. See source footnote A.']).dict())
        if interval and nav:
            for end,value in nav.items():
                if value>0:
                    results.append(candidate(fund,filing,source,'nav',value,f'HTML table {index}; Class I NAV at end of period',text,
                        'dated_financial_table',period=end,basis='nav',share_class=fund['share_class'],eligible=True,
                        reasons=['Class I financial highlights; institutional class label follows the engagement mapping.']).dict())
        annual_returns=nav_return if interval else market
        return_basis='net_nav' if interval else 'shareholder'
        if annual and annual_returns and fund['ticker'] in {'GBDC','TAKIX'} and re.search(r'reinvest',after,re.I):
            # Scope to complete annual financial highlights, never semiannual or inception periods.
            partial_earliest=bool(re.search(r'period from|since inception|commencement',text,re.I))
            for years in [1,3,5]:
                ends=[str(int(period[:4])-y)+period[4:] for y in range(years)]
                if not all(end in annual_returns for end in ends):continue
                if partial_earliest and min(annual_returns) in ends:continue
                sequence=[annual_returns[end] for end in ends]
                if any(v<=-100 for v in sequence):continue
                value=annualized_return(sequence)
                c=candidate(fund,filing,source,f'return_{years}y',value,f'HTML table {index}; annual return row and subsequent reinvestment footnote',
                    text+' '+after,'annual_return_chain',period=period,basis=return_basis,share_class=fund['share_class'],eligible=True,
                    reasons=['Annualized from consecutive disclosed annual total returns, using the stated reinvestment basis. Input percentages are rounded in the filing.']).dict()
                c['calculation']={'expression':'(product(1 + annual_return_pct / 100) ** (1 / years) - 1) * 100',
                    'inputs':dict(zip(ends,sequence)),'years':years,'output':value,'note':'Derived from rounded annual percentages; no market-data substitution.'}
                if years==1:
                    raw=(nav_raw if interval else market_raw)[period]['raw']
                    decimal=re.search(r'\.(\d+)',raw)
                    c['reported_precision_pct']=10**(-len(decimal[1])) if decimal else 1
                if not interval and years==1 and nav_return and period in nav_return:
                    c['nav_return_comparison']={'period':period,'nav_return_1y_pct':nav_return[period],
                        'shareholder_return_1y_pct':annual_returns.get(period),
                        'difference_percentage_points':annual_returns[period]-nav_return[period],
                        'note':'NAV return in this filing uses average NAV; definitions are retained, no client materiality threshold is assumed.'}
                results.append(c)
        # KREF publishes an investor-return index with distributions reinvested.
        if fund['ticker']=='KREF' and re.search(r'cumulative total stockholder return',before,re.I) and 'reinvest' in before.lower():
            for row in rows:
                cells=cells_with_positions(row)
                if not cells or cells[0][2] != 'KKR Real Estate Finance Trust, Inc.':continue
                indices=numeric_columns(row,headers)
                if period not in indices or indices[period]<=0:continue
                for years in [1,3,5]:
                    start=str(int(period[:4])-years)+period[4:]
                    if start not in indices or indices[start]<=0:continue
                    value=((indices[period]/indices[start])**(1/years)-1)*100
                    c=candidate(fund,filing,source,f'return_{years}y',value,f'HTML table {index}; KREF total-return index row',before+' '+text,
                        'return_index_ratio',period=period,basis='shareholder',share_class='Common',eligible=True,
                        reasons=['Annualized from the disclosed cumulative shareholder-return index. Dividends are reinvested; source indices are rounded.']).dict()
                    c['calculation']={'expression':'((end_index / start_index) ** (1 / years) - 1) * 100',
                        'inputs':{'start_date':start,'start_index':indices[start],'end_date':period,'end_index':indices[period],'years':years},
                        'output':value,'note':'Approximate due to rounded source index levels; not a directly reported percentage.'}
                    results.append(c)
    return results


def derive_report_metrics(documents,filings,config,cache):
    """Derive only from primary financial reports, caching this adapter separately."""
    reports={(f['ticker'],f['accessionNumber']):f for f in filings
             if f['form'].removesuffix('/A') in {'10-K','10-Q','N-CSR','N-CSRS'}
             and f.get('reportDate') and f['reportDate']<=config['target_period']}
    funds={f['ticker']:f for f in config['funds']}
    out=[]
    version=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    directory=Path(cache)/'derived';directory.mkdir(exist_ok=True)
    for doc in documents:
        filing=reports.get((doc['ticker'],doc['accession']))
        if not filing or not doc['url'].endswith('/'+filing['primaryDocument'].rsplit('/',1)[-1]):continue
        # Listed return tables live in annuals; KREF debt ratios and interval NAV can be interim.
        if doc['ticker']=='GBDC' and filing['form'].removesuffix('/A')!='10-K':continue
        source={k:doc[k] for k in ['url','sha256','submission_sha256','retrieved_at','submission_url']}
        fund=funds[doc['ticker']]
        key=hashlib.sha256(json.dumps([{'url':source['url'],'sha256':source['sha256']},filing,fund,version],sort_keys=True).encode()).hexdigest()
        path=directory/(key+'.json')
        if path.exists():found=json.loads(path.read_text())
        else:
            found=parse_financial_report((Path(cache)/doc['sha256']).read_bytes(),fund,filing,source)
            path.write_text(json.dumps(found))
        out.extend(found)
    return out
