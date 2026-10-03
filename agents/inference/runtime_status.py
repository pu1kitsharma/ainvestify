"""Configuration checks only: no model calls, network requests or secret output."""
import os
from pathlib import Path


def public_runtime_status():
    provider = os.environ.get('PREPARATION_PROVIDER','local')
    missing = [] if provider == 'local' else ['PREPARATION_PROVIDER=local']
    return {'provider':provider,'configured':not missing,'missing':missing,
            'connectivity_verified':False,'private_inference':'local',
            'message':('Hosted model routes are retired; set PREPARATION_PROVIDER=local.') if missing else 'Local inference is selected; service connectivity has not been checked.'}
