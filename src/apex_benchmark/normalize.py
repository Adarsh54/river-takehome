"""Narrow disclosure rules, calibrated on the downloaded filings.

Numbers are captured from exact contract language, never supplied as fund defaults.
Unmatched passages remain in the original review queue.
"""
from __future__ import annotations
import hashlib
import json
import re
from decimal import Decimal

RATE = r'(\d+(?:\.\d+)?)\s*%'


def qualify_disclosures(candidates, filings, config):
    selected = {}
    for fund in config['funds']:
        reports = [f for f in filings if f['ticker']==fund['ticker']
                   and f['form'].removesuffix('/A') in {'10-K','10-Q','N-CSR','N-CSRS'}
                   and f.get('reportDate') and f['reportDate'] <= config['target_period']]
        if reports:
            chosen = max(reports,key=lambda f:(f['reportDate'],f['filingDate']))
            selected[fund['ticker']] = chosen
    output = []
    seen = set()
    for source in candidates:
        if source.get('method') == 'ocr_evidence':
            continue  # Never auto-promote machine-transcribed text to a qualified fact.
        report = selected.get(source['ticker'])
        if not report or source['accession'] != report['accessionNumber']:
            continue
        key = (source['ticker'],source['source_url'],source['locator'],source['quote'])
        if key in seen:
            continue
        seen.add(key)
        text = source['quote']
        ticker = source['ticker']

        def add(metric, value, basis, rule, note, calculation=None, share_class=None):
            record = dict(source, metric=metric, value=float(value), unit='x' if metric=='leverage' else '%',
                period=report['reportDate'], basis=basis, method='qualified_disclosure', eligible=True,
                reasons=[note], rule=rule)
            if share_class:
                record['share_class']=share_class
            if calculation:
                record['calculation']=calculation
            record['id']=hashlib.sha256(json.dumps([source['id'],rule,metric,value,basis],sort_keys=True).encode()).hexdigest()[:20]
            output.append(record)

        if ticker=='CCLFX':
            m=re.search(r'Investment Management Fee equal to '+RATE+r' accrued daily, on an annualized basis of the Fund.{1,2}s Net Assets',text,re.I)
            if m:
                add('management_fee',m[1],'contractual:net_assets','cclfx_contract_fee',
                    'Annual contractual management fee on net assets. Historical expense-limit waivers in the same passage are not substituted for this rate.')
        if ticker in {'TAKIX','GBDC'}:
            m=re.search(r'base management fee is calculated at an annual rate (?:of|equal to) '+RATE,text,re.I)
            if m:
                if ticker=='TAKIX' and 'month-end Managed Assets' in text:
                    add('management_fee',m[1],'contractual:month_end_managed_assets','takix_contract_fee',
                        'Annual fee on managed assets; the source also caps the fee relative to net assets. Preserve both bases in review.')
                elif ticker=='GBDC' and 'average adjusted gross assets' in text:
                    add('management_fee',m[1],'contractual:average_adjusted_gross_assets','gbdc_contract_fee',
                        'Current annual rate precedes the parenthetical historical rate. Gross assets are adjusted as stated in the source, including exclusion of cash.')
        if ticker=='TAKIX':
            m=re.search(r'incentive fee of '+RATE+r' on all of the Fund.{1,2}s pre.incentive fee net investment income',text,re.I)
            if m:
                add('incentive_fee',m[1],'income:pre_incentive_net_income_after_hurdle_and_catchup','takix_income_fee',
                    'Base incentive participation after the disclosed hurdle and catch-up. The catch-up segment is not itself the base incentive rate.')
            m=re.search(r'annualized hurdle rate of '+RATE,text,re.I)
            if m:
                add('hurdle',m[1],'annual:net_assets','takix_annual_hurdle','Annualized hurdle explicitly disclosed alongside its quarterly equivalent.')
            if 'annualized distribution rates' in text.lower():
                m=re.search(r'Class I\s+'+RATE,text)
                if m:
                    add('distribution_yield',m[1],'annualized:reported_class_I_distribution_rate','takix_class_i_distribution',
                        'Disclosed Class I annualized distribution rate; not portfolio yield, another class, or a total-return measure. Review the referenced distribution footnote.',share_class='Class I')
        if ticker=='GBDC':
            m=re.search(r'incentive fee rates were reduced from '+RATE+r' to '+RATE,text,re.I)
            if m and 'effective as of June 3, 2024' in text:
                add('incentive_fee',m[2],'income_and_capital_gains:separate_bases_with_cap','gbdc_current_incentive',
                    'New agreement effective June 3, 2024 lowers both incentive rates. Old agreement percentages are not the current rate; separate bases/cap still apply.')
            m=re.search(r'fixed [“\"]hurdle rate[”\"] of '+RATE+r' quarterly',text,re.I)
            if m:
                value=float(Decimal(m[1])*4)
                add('hurdle',value,'annualized:quarterly_net_assets_hurdle','gbdc_annualized_hurdle',
                    'Simple annual equivalent of the disclosed quarterly hurdle; the quarterly contract and catch-up control.',
                    {'expression':'quarterly_hurdle_pct * 4','inputs':{'quarterly_hurdle_pct':float(m[1])},'output':value,'note':'Not a compounded investment return.'})
            m=re.search(r'GAAP debt.to.equity ratio was\s*[\d.]+\s*%\s*and\s*([\d.]+)x,?\s*respectively',text,re.I)
            if m:
                add('leverage',m[1],'debt_to_equity:GAAP_as_reported','gbdc_reported_debt_equity',
                    'Actual period-end GAAP debt/equity, not the target range or regulatory asset-coverage percentage in the same passage.')
        if ticker=='KREF':
            m=re.search(r'quarterly management fee equal to the greater of \$\s*62,500 or '+RATE+r' of weighted average adjusted equity',text,re.I)
            if m:
                value=float(Decimal(m[1])*4)
                add('management_fee',value,'contractual:annualized_quarterly_adjusted_equity_with_minimum','kref_management_annualized',
                    'Annual equivalent of the percentage component only. Each quarterly payment is the greater of $62,500 or the quarterly percentage of weighted average adjusted equity.',
                    {'expression':'quarterly_management_fee_pct * 4','inputs':{'quarterly_management_fee_pct':float(m[1])},'output':value,'note':'Quarterly dollar minimum still applies; this is not a flat effective expense rate.'})
            m=re.search(r'quarterly incentive compensation equal to '+RATE+r' of the excess',text,re.I)
            if m:
                add('incentive_fee',m[1],'income:trailing_12_month_distributable_earnings_over_adjusted_equity_hurdle','kref_incentive',
                    'Participation on trailing distributable earnings above the hurdle, less prior payments; paid with the disclosed lag.')
            m=re.search(r'over \(b\)\s*'+RATE+r' of the trailing 12\s*.?month weighted average adjusted equity',text,re.I)
            if m:
                add('hurdle',m[1],'annual:trailing_12_month_adjusted_equity','kref_hurdle',
                    'Trailing twelve-month hurdle on adjusted equity, as defined in the management agreement.')
    return list({c['id']:c for c in output}.values())
