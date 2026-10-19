"""Windowless entry point for owned interactive Windows tasks and recovery."""
from pathlib import Path
import os
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from terminus.platform_windows import identity,guardian,bring_back
    role=sys.argv[1]
    if role not in {'core','desktop','presence','updates','recover'}: raise ValueError('Unknown task')
    data=ROOT/'.local'; data.mkdir(exist_ok=True)
    # pythonw has no standard streams. Supply logs before uvicorn/Qt imports.
    path=data/('windows-'+role+'.log')
    if path.exists() and path.stat().st_size>2*1024*1024:
        path.replace(path.with_suffix('.previous.log'))
    sys.stdout=sys.stderr=path.open('a',encoding='utf-8',buffering=1)
    sys.stdin=open(os.devnull)
    os.chdir(ROOT)
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='1'
    os.environ['TERMINUS_SERVICE']=role
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Starting {role}',flush=True)
    if role in {'core','desktop'}:
        from terminus.runtime import write_private
        from terminus.supervision import is_paused
        if is_paused(role,data): return 0
        (data/('windows-'+role+'.stop')).unlink(missing_ok=True)
        value=identity(os.getpid())
        write_private(data/('windows-'+role+'.json'),dict(value,root=str(ROOT),started=time.time()))
    if role=='core':
        import asyncio
        import secrets
        import uvicorn
        from terminus.api import create_app
        server=uvicorn.Server(uvicorn.Config(create_app(data,seed=secrets.randbits(63)),
                                            host='127.0.0.1',port=8769,access_log=False,ws_max_size=8192))
        async def run():
            async def control():
                while not server.should_exit:
                    if (data/'windows-core.stop').exists(): server.should_exit=True
                    await asyncio.sleep(.25)
            task=asyncio.create_task(control())
            try: await server.serve()
            finally: task.cancel()
        asyncio.run(run())
    elif role=='desktop':
        from desktop.overlay import main as overlay
        return overlay(['--data-dir',str(data),'--status-file',str(data/'desktop-status.json'),
                        '--capture-file',str(data/'desktop-presence.png')])
    elif role=='presence': guardian(ROOT)
    elif role=='recover': return bring_back(ROOT)
    elif role=='updates':
        from scripts.update import main as update
        return update(['--automatic'])
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception:
        traceback.print_exc(); raise SystemExit(1)
