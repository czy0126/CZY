import io
import json
import sys
import pytest
import deepseek_run as runner


def test_settings_only_supplies_deepseek_connection_not_other_credentials(tmp_path,monkeypatch):
    settings=tmp_path/'settings.json'
    settings.write_text(json.dumps({'env':{'ANTHROPIC_AUTH_TOKEN':'dummy-token',
        'ANTHROPIC_BASE_URL':'https://api.deepseek.com/anthropic',
        'ANTHROPIC_MODEL':'deepseek-v4-flash','UNRELATED_API_KEY':'do-not-send'}}))
    prompt=tmp_path/'prompt.md';prompt.write_text('Review copper coverage.')
    reply=tmp_path/'reply.md'
    monkeypatch.setattr(sys,'argv',['deepseek_run','--claude-settings',str(settings),'--prompt',str(prompt),'--reply',str(reply)])
    def fake(request,timeout):
        assert request.full_url=='https://api.deepseek.com/anthropic/v1/messages'
        payload=json.loads(request.data)
        assert payload['model']=='deepseek-v4-flash'
        assert payload['thinking']=={'type':'disabled'}
        assert 'dummy-token' not in request.data.decode()
        assert 'do-not-send' not in request.data.decode()
        return io.BytesIO(json.dumps({'model':'deepseek-v4-flash','content':[{'type':'text','text':'Reviewed'}],
                                     'stop_reason':'end_turn','usage':{'output_tokens':1}}).encode())
    monkeypatch.setattr(runner,'urlopen',fake)
    runner.main()
    assert reply.read_text()=='Reviewed'
    assert 'dummy-token' not in reply.with_suffix('.meta.json').read_text()


def test_settings_cannot_redirect_credentials_to_other_host(tmp_path,monkeypatch):
    settings=tmp_path/'settings.json'
    settings.write_text(json.dumps({'env':{'ANTHROPIC_AUTH_TOKEN':'dummy-token',
        'ANTHROPIC_BASE_URL':'https://untrusted.example/anthropic'}}))
    prompt=tmp_path/'prompt.md';prompt.write_text('Review')
    monkeypatch.setattr(sys,'argv',['deepseek_run','--claude-settings',str(settings),'--prompt',str(prompt),'--reply',str(tmp_path/'reply.md')])
    monkeypatch.setattr(runner,'urlopen',lambda *a,**k:pytest.fail('must not send credentials'))
    with pytest.raises(SystemExit):runner.main()
