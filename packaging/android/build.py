"""Android build: every cache/tool/intermediate belongs to the chosen work folder.

Requires a tools.json mapping java/gradle/sdk/python inside --work. The APK
and private preview signing key are retained outside disposable intermediates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--task',default='assembleRelease');args=p.parse_args()
    work=args.work.resolve();out=args.output.resolve();out.mkdir(exist_ok=True)
    tools=json.loads((work/'tools.json').read_text('utf-8-sig'))
    env=os.environ.copy()
    env.update(JAVA_HOME=tools['java'],ANDROID_HOME=tools['sdk'],ANDROID_SDK_ROOT=tools['sdk'],
        ANDROID_USER_HOME=str(work/'android-user'),GRADLE_USER_HOME=str(work/'gradle-home'),
        CASHMINER_ANDROID_BUILD=str(work/'build'),CASHMINER_ANDROID_ASSETS=str(work/'generated-assets'),
        CASHMINER_ANDROID_RES=str(work/'generated-res'),CASHMINER_BUILD_PYTHON=tools['python'],
        PIP_CACHE_DIR=str(work/'pip-cache'),
        TEMP=str(work/'tmp'),TMP=str(work/'tmp'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
    for name in ('android-user','gradle-home','generated-assets','generated-res','tmp','build'):(work/name).mkdir(exist_ok=True)
    signing=out/'Signing';signing.mkdir(exist_ok=True)
    key=signing/'cashminer-preview.jks';password=signing/'password.txt'
    if not key.exists():
        if password.exists():raise RuntimeError('Password exists without signing key; inspect before replacing')
        password.write_text(secrets.token_urlsafe(32),encoding='ascii')
    env['CASHMINER_STORE_PASSWORD']=password.read_text('ascii').strip()
    env['CASHMINER_KEYSTORE']=str(key)
    if not key.exists():
        subprocess.run([str(Path(tools['java'])/'bin/keytool.exe'),'-genkeypair','-noprompt',
            '-keystore',str(key),'-alias','cashminer-preview','-keyalg','RSA','-keysize','3072',
            '-validity','3650','-dname','CN=CashMiner Preview',
            '-storepass:env','CASHMINER_STORE_PASSWORD','-keypass:env','CASHMINER_STORE_PASSWORD'],
            check=True,env=env)
    icon=work/'generated-res/mipmap/ic_launcher.png';icon.parent.mkdir(exist_ok=True)
    shutil.copy2(SOURCE/'assets/icon_128.png',icon)
    payload=work/'generated-assets/cashminer_payload.zip'
    with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED) as z:
        for directory in ('src','ui','assets','mining_engine'):
            for path in sorted((SOURCE/directory).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                    if directory=='ui' and path.suffix in ('.html','.js'):
                        # The APK uses Android Keystore, never Windows DPAPI.
                        text=path.read_text('utf-8').replace('Windows DPAPI','Android Keystore').replace('cifrado DPAPI','cifrado Android Keystore')
                        if path.name=='index.html':
                            text=text.replace('max="100" step="1" value="${esc(cpuValue)}" data-cpu-percent',
                                              'max="50" step="1" value="${esc(cpuValue)}" data-cpu-percent')
                            text=text.replace('gpu_percent:25,gpu_overrides:{}','gpu_percent:0,gpu_overrides:{}')
                        z.writestr(str(path.relative_to(SOURCE)).replace('\\','/'),text)
                    else:z.write(path,path.relative_to(SOURCE))
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):z.write(SOURCE/name,name)
        z.write(HERE/'ANDROID_NOTICES.md','ANDROID_NOTICES.md')
        for path in sorted((HERE/'licenses').glob('*.txt')):z.write(path,'licenses/'+path.name)
    # No local.properties or generated assets/build trees in the source checkout.
    command=[str(Path(tools['gradle'])/'bin/gradle.bat'),'--no-daemon','--console=plain',
        '--project-cache-dir',str(work/'project-cache'),'-p',str(HERE),args.task]
    print('Gradle '+args.task+'; tools/cache/output isolated under '+str(work),flush=True)
    subprocess.run(command,check=True,env=env)
    if args.task=='assembleRelease':
        built=work/'build/app/outputs/apk/release/app-release.apk'
        target=out/'CashMiner-Android-preview.apk';shutil.copy2(built,target)
        value=hashlib.sha256(target.read_bytes()).hexdigest()
        (out/'SHA256SUMS.txt').write_text(value+'  '+target.name+'\n',encoding='ascii')
        print(json.dumps({'apk':str(target),'bytes':target.stat().st_size,'sha256':value}),flush=True)

if __name__=='__main__':main()
