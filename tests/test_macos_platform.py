"""launchd definitions and ownership checks without operating real agents."""
from pathlib import Path
import plistlib
import subprocess
import pytest
from terminus import platform_macos as mac


def test_launch_agents_keep_native_processes_and_use_actual_checkout():
    root=Path('/Users/test/a project/Terminus')
    for role in ('core','desktop','presence'):
        value=plistlib.loads(plistlib.dumps(mac.definition(role,root)))
        assert value['WorkingDirectory']==str(root)
        assert value['ProgramArguments'][0]==str(root/'.venv/bin/python')
        assert value['LimitLoadToSessionType']=='Aqua'
        assert value['Umask']==0o077
        assert value['EnvironmentVariables']['TERMINUS_SERVICE']==role
        assert 'token' not in value['EnvironmentVariables']
        for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS'):
            assert value['EnvironmentVariables'][name]=='1'
        if role in {'core','desktop'}:assert value['KeepAlive'] is True
        else:assert value['StartInterval']==30 and 'KeepAlive' not in value
    assert mac.definition('desktop',root)['ProgramArguments'][2:4]==['--renderer','auto']


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


@pytest.mark.parametrize('mismatch',[None,'path','working directory','program','label'])
def test_bootstrap_guardian_race_is_accepted_only_for_the_exact_owned_job(tmp_path,monkeypatch,mismatch):
    path=tmp_path/'org.terminus.desktop.plist'
    expected=mac.definition('desktop',tmp_path/'Terminus')
    path.write_bytes(plistlib.dumps(expected))
    monkeypatch.setattr(mac,'paths',lambda role:path)
    calls=[];prints=[]
    def call(*arguments,**kwargs):
        calls.append(arguments)
        if arguments[0]=='bootstrap':
            raise subprocess.CalledProcessError(5,arguments,stderr='Bootstrap failed: 5')
        if arguments[0]=='print':
            prints.append(True)
            if len(prints)==1:return subprocess.CompletedProcess(arguments,113,'','missing')
            fields={'path':str(path),'working directory':expected['WorkingDirectory'],
                    'program':expected['ProgramArguments'][0]}
            label=mac.domain()+'/org.terminus.desktop'
            if mismatch=='label':label='gui/501/unrelated'
            elif mismatch:fields[mismatch]='unrelated'
            report=label+' = {\n'+''.join('\t'+key+' = '+value+'\n' for key,value in fields.items())+'}\n'
            return subprocess.CompletedProcess(arguments,0,report,'')
        return subprocess.CompletedProcess(arguments,0,'','')
    monkeypatch.setattr(mac,'call',call)
    if mismatch:
        with pytest.raises(subprocess.CalledProcessError):mac.start('desktop')
        assert not any(command[0]=='kickstart' for command in calls)
    else:
        mac.start('desktop')
        assert calls[-1]==('kickstart',mac.domain()+'/org.terminus.desktop')


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
