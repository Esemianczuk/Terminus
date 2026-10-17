"""launchd definitions and ownership checks without operating real agents."""
from pathlib import Path
import plistlib
import pytest
from terminus import platform_macos as mac


def test_launch_agents_keep_native_processes_and_use_actual_checkout():
    root=Path('/Users/test/a project/Terminus')
    for role in ('core','desktop','presence','collective'):
        value=plistlib.loads(plistlib.dumps(mac.definition(role,root)))
        assert value['WorkingDirectory']==str(root)
        assert value['ProgramArguments'][0]==str(root/'.venv/bin/python')
        assert value['LimitLoadToSessionType']=='Aqua'
        assert value['Umask']==0o077
        assert value['EnvironmentVariables']['TERMINUS_SERVICE']==role
        assert 'token' not in value['EnvironmentVariables']
        if role in {'core','desktop'}:assert value['KeepAlive'] is True
        else:assert value['StartInterval'] in (30,600) and 'KeepAlive' not in value
    assert '--allow-network' not in mac.definition('core',root)['ProgramArguments']


def test_launchd_properties_use_our_plist_and_parse_only_the_main_pid(tmp_path,monkeypatch):
    path=tmp_path/'agent.plist';path.write_bytes(plistlib.dumps({'WorkingDirectory':'/expected'}))
    monkeypatch.setattr(mac,'paths',lambda role:path)
    monkeypatch.setattr(mac,'call',lambda *a,**k:type('Result',(),{'returncode':0,'stdout':'state = running\n pid = 1234\n last exit code = 0\n'})())
    info=mac.properties('desktop')
    assert info['WorkingDirectory']=='/expected'
    assert info['MainPID']=='1234' and info['ActiveState']=='active'


def test_start_bootstraps_once_and_does_not_force_restart_an_existing_app(monkeypatch):
    calls=[]
    def call(*args,**kwargs):
        calls.append(args)
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(mac,'call',call)
    mac.start('desktop')
    assert calls[-1]==('kickstart',mac.domain()+'/org.terminus.desktop')
    assert not any('-k' in args or 'bootstrap' in args for args in calls)


def test_recovery_shortcut_restarts_unresponsive_owned_components(tmp_path,monkeypatch):
    from terminus import supervision
    calls=[]
    monkeypatch.setattr(mac,'properties',lambda role:{'WorkingDirectory':str(tmp_path),'MainPID':'123'})
    monkeypatch.setattr(mac,'start',lambda role:None)
    monkeypatch.setattr(mac,'call',lambda *args,**kwargs:calls.append(args))
    monkeypatch.setattr(mac,'action',lambda *args:0)
    monkeypatch.setattr(supervision,'health',lambda:False)
    monkeypatch.setattr(supervision,'desktop_status',lambda *args:None)
    assert mac.bring_back(tmp_path)==0
    assert ('kickstart','-k',mac.domain()+'/org.terminus.core') in calls
    assert ('kickstart','-k',mac.domain()+'/org.terminus.desktop') in calls
    calls.clear()
    monkeypatch.setattr(mac,'properties',lambda role:{'WorkingDirectory':'/someone-else'})
    with pytest.raises(ValueError):mac.bring_back(tmp_path)
    assert not calls
