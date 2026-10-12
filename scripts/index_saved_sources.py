"""One-time migration of legacy audits to the metric-independent passage index."""
import argparse,json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from apex_benchmark.passages import document_passages


def index_one(item):
    cache,digest=item
    stats={};document_passages(cache,digest,stats)
    return stats.get('documents_parsed',0)


def main():
    p=argparse.ArgumentParser();p.add_argument('audit',type=Path);p.add_argument('--cache',default='.cache/sec');p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();r=json.loads(args.audit.read_text())
    digests=sorted({d['sha256'] for d in r['documents'] if not d['url'].lower().endswith('.xml')})
    start=time.perf_counter();parsed=0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i,count in enumerate(pool.map(index_one,((args.cache,d) for d in digests)),1):
            parsed+=count
            if i%200==0:print(f'{i}/{len(digests)} documents; {parsed} newly indexed; {time.perf_counter()-start:.1f}s',flush=True)
    print(f'Finished: {parsed} new; {len(digests)-parsed} reused; {time.perf_counter()-start:.3f}s',flush=True)

if __name__=='__main__':main()
