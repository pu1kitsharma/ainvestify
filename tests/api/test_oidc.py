import time
from urllib.parse import parse_qs,urlsplit
import pytest
from authlib.jose import JsonWebKey,JsonWebToken
from security.oidc import OIDCConfig,OIDCProvider


@pytest.fixture
def provider(monkeypatch):
    config=OIDCConfig('https://accounts.google.com','synthetic-client','synthetic-secret','https://app.example/api/auth/callback')
    provider=OIDCProvider(config)
    monkeypatch.setattr(provider,'metadata',lambda:{'authorization_endpoint':'https://accounts.google.com/auth','token_endpoint':'https://oauth2.googleapis.com/token','jwks_uri':'https://www.googleapis.com/jwks'})
    return provider


def test_authorization_uses_pkce_state_nonce_and_fixed_redirect(provider):
    url=provider.authorization_url('state','nonce','a'*64)
    q=parse_qs(urlsplit(url).query)
    assert q['code_challenge_method']==['S256']
    assert q['state']==['state'] and q['nonce']==['nonce']
    assert q['redirect_uri']==['https://app.example/api/auth/callback']
    assert set(q['scope'][0].split())=={'openid','email','profile'}


@pytest.mark.parametrize('change',[{}, {'iss':'https://evil.example'}, {'aud':'other-client'}, {'nonce':'wrong'}, {'exp':1}, {'sub':''}])
def test_real_signed_token_verification(provider,monkeypatch,change):
    key=JsonWebKey.generate_key('RSA',2048,is_private=True)
    now=int(time.time())
    claims=dict(iss=provider.config.issuer,sub='synthetic-sub',aud=provider.config.client_id,nonce='nonce',iat=now,exp=now+60)
    claims.update(change)
    raw=JsonWebToken(['RS256']).encode({'alg':'RS256'},claims,key).decode()
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def fetch_token(self,*args,**kwargs):
            assert kwargs['code_verifier']=='verifier'
            return {'id_token':raw}
    monkeypatch.setattr(provider,'client',Client)
    monkeypatch.setattr('security.oidc._json_get',lambda url:{'keys':[key.as_dict(is_private=False)]})
    if change:
        with pytest.raises(Exception):provider.verify_code('code','nonce','verifier')
    else:assert provider.verify_code('code','nonce','verifier')==(provider.config.issuer,'synthetic-sub')
