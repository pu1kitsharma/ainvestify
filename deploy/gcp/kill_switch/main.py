"""Cloud Function (Pub/Sub trigger): stop the GPU VM when spend reaches the threshold.

Receives GCP Budget notifications (JSON: costAmount, budgetAmount, ...). At >= 95%
of budget it stops every instance named in GPU_INSTANCES. Pure decision logic is
in `decide`; the compute call is injected so it is testable offline.
Env: GCP_PROJECT, GPU_ZONE, GPU_INSTANCES (comma list), KILL_THRESHOLD (default 0.95),
DRY_RUN (default "true": log the stop but do not call the API).
"""
import base64
import json
import logging
import os

THRESHOLD = 0.95


def parse_message(event):
    """Accepts a CloudEvent-style dict or legacy dict with `data` base64 JSON."""
    data = event.get('data', event)
    if isinstance(data, dict) and 'message' in data:
        data = data['message'].get('data', '')
    if isinstance(data, (str, bytes)):
        data = json.loads(base64.b64decode(data).decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Unsupported budget notification')
    return data


def decide(notification, threshold=THRESHOLD):
    """Return (should_stop, ratio). Malformed or zero budgets fail SAFE (stop)."""
    try:
        cost, budget = float(notification['costAmount']), float(notification['budgetAmount'])
        if budget <= 0 or cost != cost or budget != budget:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return True, None
    ratio = cost / budget
    return ratio >= threshold, ratio


def _stop_via_api(project, zone, name):
    from googleapiclient import discovery  # provided in the Cloud Function runtime
    discovery.build('compute', 'v1', cache_discovery=False).instances().stop(project=project, zone=zone, instance=name).execute()


def handle(event, *, stop=_stop_via_api, env=os.environ, log=logging.getLogger(__name__)):
    note = parse_message(event)
    stop_now, ratio = decide(note, float(env.get('KILL_THRESHOLD', THRESHOLD)))
    if not stop_now:
        log.info('budget ratio %.3f below threshold; no action', ratio)
        return {'action': 'none', 'ratio': ratio}
    names = [n.strip() for n in env.get('GPU_INSTANCES', '').split(',') if n.strip()]
    if not names:
        raise RuntimeError('GPU_INSTANCES is not configured; kill switch cannot act')
    dry = env.get('DRY_RUN', 'true').lower() != 'false'
    stopped = []
    for name in names:
        if dry:
            log.warning('[dry-run] would stop %s (ratio=%s)', name, ratio)
        else:
            stop(env['GCP_PROJECT'], env['GPU_ZONE'], name)
        stopped.append(name)
    return {'action': 'dry_run_stop' if dry else 'stopped', 'ratio': ratio, 'instances': stopped}


def stop_gpu_vm(event, context=None):  # Cloud Functions entry point (Pub/Sub trigger)
    return handle(event)
