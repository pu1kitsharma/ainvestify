"""Tool-free HTTP transport: no document reads or echoed provider error bodies."""
import json
import os
import sys

import requests


def main():
    body = json.load(sys.stdin)
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post('https://api.deepseek.com/chat/completions', json=body,
            headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']},
            timeout=(10, 115), allow_redirects=False)
        if response.status_code != 200:
            print(json.dumps({'error':'provider_error','status':response.status_code}))
            return 1
        data = response.json()
        # Retain final content and billing, not hidden reasoning or headers.
        choice = data['choices'][0]
        print(json.dumps({'model':data.get('model'),'id':data.get('id'),
            'usage':data.get('usage',{}),'finish_reason':choice.get('finish_reason'),
            'content':choice.get('message',{}).get('content'),
            'tool_calls':bool(choice.get('message',{}).get('tool_calls'))}))
        return 0
    except (requests.RequestException, ValueError, KeyError, IndexError):
        print(json.dumps({'error':'transport_error'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
