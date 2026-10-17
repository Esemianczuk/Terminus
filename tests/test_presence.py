"""Desktop-button and periodic presence behavior without touching real services."""
import json
from pathlib import Path
import pytest
from scripts import bring_back as button
from scripts import servicectl as installer
from terminus import supervision as control


def fixture(monkeypatch,tmp_path,states=None):
    root=tmp_path.resolve();data=root/'.local';data.mkdir()
    (data/'service-install.json').write_text(json.dumps({'version':1,'root':str(root)}))
    monkeypatch.setattr(button,'ROOT',root)
    properties={r:{'WorkingDirectory':str(root),'UnitFileState':'enabled','ActiveState':'active'} for r in control.UNITS}
    if states:
        for role,changes in states.items():properties[role].update(changes)
    monkeypatch.setattr(control,'properties',lambda role:properties[role])
    calls=[]
    monkeypatch.setattr(button,'run',lambda *args:calls.append(args))
    monkeypatch.setattr(button,'save_session',lambda *args:None)
    return data,properties,calls


def test_shortcut_starts_both_and_guardian_without_restarting_healthy_pet(tmp_path,monkeypatch):
    data,_,calls=fixture(monkeypatch,tmp_path)
    for role in control.UNITS:control.set_paused(role,data,True)
    monkeypatch.setattr(button,'wait_ready',lambda seconds:True)
    button.bring_back()
    assert calls==[('enable','terminus-core.service','terminus-desktop.service','terminus-presence.timer'),
                   ('start','terminus-core.service','terminus-desktop.service','terminus-presence.timer')]
    assert all(not control.is_paused(role,data) for role in control.UNITS)


def test_shortcut_repairs_a_stalled_pet_and_requires_real_readiness(tmp_path,monkeypatch):
    _,_,calls=fixture(monkeypatch,tmp_path)
    outcomes=iter([False,True])
    monkeypatch.setattr(button,'wait_ready',lambda seconds:next(outcomes))
    monkeypatch.setattr(control,'health',lambda:False)
    button.bring_back()
    assert calls[-2:]==[('restart','terminus-core.service'),('restart','terminus-desktop.service')]
    monkeypatch.setattr(button,'wait_ready',lambda seconds:False)
    with pytest.raises(RuntimeError,match='not yet confirmed'):button.bring_back()


def test_guardian_restores_stopped_services_and_never_bounces_healthy_ones(tmp_path,monkeypatch):
    _,properties,calls=fixture(monkeypatch,tmp_path,{'desktop':{'ActiveState':'inactive'}})
    button.guardian()
    assert calls==[('start','terminus-desktop.service')]
    calls.clear();properties['desktop']['ActiveState']='active'
    button.guardian()
    assert calls==[]
    properties['core']['ActiveState']='failed';properties['desktop']['ActiveState']='inactive'
    button.guardian()
    assert calls==[('start','terminus-core.service','terminus-desktop.service')]


def test_guardian_respects_explicit_quit_stop_and_disable(tmp_path,monkeypatch):
    data,properties,calls=fixture(monkeypatch,tmp_path,{'desktop':{'ActiveState':'inactive'}})
    control.set_paused('desktop',data,True)
    assert (data/'desktop-paused').stat().st_mode&0o777==0o600
    button.guardian();assert calls==[]
    control.set_paused('desktop',data,False)
    properties['desktop']['UnitFileState']='disabled'
    button.guardian();assert calls==[]
    control.set_paused('core',data,True)
    properties['desktop']['UnitFileState']='enabled'
    button.guardian();assert calls==[]


def test_guardian_never_controls_another_checkout(tmp_path,monkeypatch):
    _,properties,calls=fixture(monkeypatch,tmp_path)
    properties['desktop']['WorkingDirectory']='/someone-else'
    with pytest.raises(RuntimeError,match='another checkout'):button.guardian()
    assert calls==[]


def test_launcher_and_timer_are_visible_bounded_and_use_approved_icon():
    root=Path('/example/Terminus')
    text=installer.shortcut_text(root)
    assert 'Name=Bring Back Terminus' in text
    assert 'bring_back.py' in text and 'Terminal=false' in text
    assert 'Icon=/example/Terminus/web/assets/terminus-refined.png' in text
    units=installer.presence_units(root)
    assert '--guardian' in units['terminus-presence.service']
    assert 'TimeoutStartSec=30' in units['terminus-presence.service']
    assert 'OnUnitInactiveSec=30' in units['terminus-presence.timer']
    assert 'WantedBy=timers.target' in units['terminus-presence.timer']
