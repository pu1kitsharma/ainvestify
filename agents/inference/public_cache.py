"""Exact public-result cache in operator-controlled, loopback Elasticsearch.

Private payloads must never use this cache. Invalid/stale entries are misses;
an unavailable configured cache stops work rather than silently spending again.
"""
import hashlib
import json
import os
import time
import uuid
from urllib.parse import urlsplit
from pathlib import Path

import requests


def cache_key(model, task, instruction, evidence, schema, settings):
    value = [1, 'public_website_evidence', model, task, instruction,
             json.loads(evidence), schema.model_json_schema(), settings]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PublicResultCache:
    def __init__(self, namespace='results', ttl_seconds=86400):
        if namespace not in {'results','search','sources'}:
            raise ValueError('Unknown public cache namespace.')
        self.index = 'ainvestify-public-' + namespace + '-v1'
        self.ttl_seconds = ttl_seconds
        self.url = os.environ.get('ELASTICSEARCH_URL', '').rstrip('/')
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
                raise ValueError('The public cache currently requires a loopback Elasticsearch URL without embedded credentials.')
        self.session = requests.Session()
        self.session.trust_env = False
        if os.environ.get('ELASTICSEARCH_CA_FILE'):
            self.session.verify = os.environ['ELASTICSEARCH_CA_FILE']
        key = os.environ.get('ELASTICSEARCH_API_KEY')
        if not key and os.environ.get('ELASTICSEARCH_API_KEY_FILE'):
            key = Path(os.environ['ELASTICSEARCH_API_KEY_FILE']).read_text().strip()
        if key:
            self.session.headers['Authorization'] = 'ApiKey ' + key

    def request(self, method, key, body=None):
        try:
            response = self.session.request(method, self.url + '/' + self.index + '/_doc/' + key,
                json=body, timeout=5, allow_redirects=False)
            if method == 'GET' and response.status_code == 404:
                return None
            if response.status_code not in {200, 201}:
                raise ValueError('Configured public cache unavailable; no automatic paid regeneration.')
            return response.json()
        except requests.RequestException:
            raise ValueError('Configured public cache unavailable; no automatic paid regeneration.') from None

    def get(self, key, schema):
        if not self.url:
            return None
        result = self.request('GET', key)
        row = result.get('_source', {}) if result else {}
        if row.get('key') != key or row.get('scope') != 'public_website_evidence' or row.get('expires_at', 0) <= time.time():
            return None
        raw = row.get('raw_response', '')
        if not isinstance(raw, str):
            return None
        if hashlib.sha256(raw.encode()).hexdigest() != row.get('raw_sha256'):
            return None
        try:
            schema.model_validate_json(raw)
        except ValueError:
            return None
        return row

    def claim(self, key):
        """Create-only lease; a timed-out paid request is not blindly repeated."""
        owner = uuid.uuid4().hex
        body = {'owner':owner,'expires_at':time.time()+180}
        base = self.url + '/ainvestify-public-leases-v1'
        try:
            response = self.session.put(base+'/_create/'+key, json=body, timeout=5, allow_redirects=False)
            if response.status_code == 201:
                return owner
            if response.status_code != 409:
                raise ValueError('Public generation lease unavailable; no paid call started.')
            prior = self.session.get(base+'/_doc/'+key, timeout=5, allow_redirects=False)
            if prior.status_code != 200:
                raise ValueError('Public generation lease changed; retry after checking saved work.')
            row = prior.json()
            if row['_source']['expires_at'] > time.time():
                raise ValueError('An identical request is running or recently timed out. Check saved work before retrying.')
            response = self.session.put(base+'/_doc/'+key, json=body,
                params={'if_seq_no':row['_seq_no'],'if_primary_term':row['_primary_term']},
                timeout=5, allow_redirects=False)
            if response.status_code not in {200,201}:
                raise ValueError('Another worker owns this generation; no duplicate paid call started.')
            return owner
        except (requests.RequestException, KeyError, TypeError):
            raise ValueError('Public generation lease unavailable; no paid call started.') from None

    def release(self, key, owner):
        # Best effort after a durable cache write; a remaining lease expires.
        base = self.url + '/ainvestify-public-leases-v1/_doc/' + key
        try:
            response = self.session.get(base, timeout=5, allow_redirects=False)
            if response.status_code != 200:
                return
            row = response.json()
            if row['_source']['owner'] == owner:
                self.session.delete(base, params={'if_seq_no':row['_seq_no'],'if_primary_term':row['_primary_term']},
                    timeout=5, allow_redirects=False)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return

    def put(self, key, raw, model, usage):
        if self.url:
            self.request('PUT', key, {'key':key,'scope':'public_website_evidence','validation':'schema_valid',
                'raw_response':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                'model':model,'usage':usage,'created_at':time.time(),'expires_at':time.time()+self.ttl_seconds})
