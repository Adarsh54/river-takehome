import json
import threading
from http.server import ThreadingHTTPServer
import pytest
import requests
from apex_benchmark import approval
from apex_benchmark.workspace import Workspace, handler


def package(path):
    path.mkdir(exist_ok=True)
    for name in approval.PACKAGE_FILES:
        (path/name).write_text('draft')
    run={'pm_narrative':'PM-written test summary.','results':[{'ticker':'TEST','metric':'fee','value':1.2,'sources':[{'source_url':'https://www.sec.gov/example', 'locator':'page 1', 'quote':'1.2', 'source_sha256':'abc'}]}], 'nav_history':[]}
    (path/'audit.json').write_text(json.dumps(run))
    return run


def test_approval_requires_both_distinct_reviewers_and_exact_version(tmp_path):
    package(tmp_path)
    version=approval.status(tmp_path)['version']
    assert not approval.status(tmp_path)['released']
    with pytest.raises(ValueError):approval.approve(tmp_path,'pm','Pat',version,False)
    assert not approval.approve(tmp_path,'pm','Pat',version,True)['released']
    with pytest.raises(ValueError):approval.approve(tmp_path,'compliance','PAT',version,True)
    assert approval.approve(tmp_path,'compliance','Chris',version,True)['released']
    (tmp_path/'benchmark.docx').write_text('changed')
    assert not approval.status(tmp_path)['released']
    with pytest.raises(ValueError):approval.approve(tmp_path,'pm','Pat',version,True)


def test_missing_source_blocks_approval(tmp_path):
    run=package(tmp_path);run['results'][0]['sources']=[]
    (tmp_path/'audit.json').write_text(json.dumps(run))
    with pytest.raises(ValueError,match='missing citations'):
        approval.approve(tmp_path,'compliance','Chris',approval.status(tmp_path)['version'],True)


def test_exclusion_removes_value_and_retains_audit(tmp_path, monkeypatch):
    package(tmp_path)
    def export(run, folder):
        assert run['results'][0]['value'] is None
        assert not run['results'][0]['sources']
        assert not run['results'][0]['calculation']
        (folder/'audit.json').write_text(json.dumps(run))
    monkeypatch.setattr('apex_benchmark.report.export',export)
    version=approval.status(tmp_path)['version']
    approval.approve(tmp_path,'pm','Pat',version,True)
    approval.approve(tmp_path,'compliance','Chris',version,True)
    assert not approval.exclude(tmp_path,'results',0,'Not located in original filing',version)['released']
    assert json.loads((tmp_path/'publication-exclusions.json').read_text())[0]['original']['value']==1.2


def test_direct_download_cannot_bypass_gate(tmp_path):
    from pathlib import Path
    report=tmp_path/'report';package(report)
    config=Path('config/engagement.json').resolve()
    workspace=Workspace(tmp_path,config,report)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(workspace))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        for name in approval.DOWNLOADS:
            assert requests.get(url+'/report/'+name).status_code==403
        state=requests.get(url+'/api/state').json()
        headers={'X-CSRF-Token':state['csrf']}
        data={'version':state['publication']['version'],'confirmed':True}
        assert requests.post(url+'/api/approve',json=dict(data,role='pm',reviewer='Pat'),headers=headers).status_code==200
        assert requests.get(url+'/report/benchmark.docx').status_code==403
        assert requests.post(url+'/api/approve',json=dict(data,role='compliance',reviewer='Chris'),headers=headers).status_code==200
        assert requests.get(url+'/report/benchmark.docx').status_code==200
        (report/'benchmark.csv').write_text('changed')
        assert requests.get(url+'/report/benchmark.docx').status_code==403
    finally:
        server.shutdown();server.server_close()
