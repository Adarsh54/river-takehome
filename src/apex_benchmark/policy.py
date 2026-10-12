"""Versioned comparison rules, scoped by metric independently of source parsing."""
DEFAULT = {'version':'conflicts-v1','instructions':
    'Compare the same measure, period, basis and share class. A newer filing alone does not resolve a contradiction. '
    'Look for an explicit correction, amendment or reconciliation in the supplied evidence. '
    'Contractual management fees are primary; show effective fees separately and preserve waiver expiration if disclosed. '
    'Different fee arrangements are not an unresolved conflict. If the same measure remains contradictory, '
    'withhold the accepted value, record every material competing figure with its citation, and escalate to the PM.'}


def policy_for(config,metric):
    import copy
    policies=copy.deepcopy(config.get('comparison_policies',{}))
    return {'base':dict(DEFAULT),'shared':policies.get('*',{}),'metric':policies.get(metric,{})}


def snapshot(config):
    from .metrics import metric_labels
    return {m:policy_for(config,m) for m in metric_labels(config)}


def validate_policies(config):
    from .metrics import metric_labels
    policies=config.get('comparison_policies',{})
    if not isinstance(policies,dict):raise ValueError('comparison_policies must be an object')
    for metric,rule in policies.items():
        if metric!='*' and metric not in metric_labels(config):raise ValueError('Unknown comparison policy metric: '+metric)
        if not isinstance(rule,dict) or set(rule)!={'version','instructions'} or any(not isinstance(v,str) or not v.strip() for v in rule.values()):
            raise ValueError('Each comparison policy needs nonempty version and instructions strings')
