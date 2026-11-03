"""Install a workspace-local Windows Tesseract and Vietnamese models. No book upload."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
if sys.prefix == sys.base_prefix and (root/'backend/.tools/python').exists():
    sys.path.insert(0,str(root/'backend/.tools/python'))
import httpx

VERSION='5.5.3'
ASSET='tesseract-ocr-w64-setup-5.5.3.20260724.exe'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if os.name!='nt':
        raise SystemExit('Install tesseract-ocr and tesseract-ocr-vie with your OS package manager; see README.')
    seven_zip=shutil.which('7z') or shutil.which('7zz')
    if not seven_zip:
        raise SystemExit('7-Zip is required to extract the official Windows package without running its installer.')
    folder=root/'backend/.tools/tesseract'
    folder.mkdir(parents=True,exist_ok=True)
    executable=folder/'tesseract.exe'
    metadata={}
    with httpx.Client(timeout=120,follow_redirects=True,headers={'User-Agent':'NomWorkspace/setup'}) as client:
        if not executable.exists():
            release=client.get(f'https://api.github.com/repos/tesseract-ocr/tesseract/releases/tags/{VERSION}').raise_for_status().json()
            asset=next(item for item in release['assets'] if item['name']==ASSET)
            url=asset['browser_download_url']+'?download=1'
            package=root/'backend/.tools'/ASSET
            content=client.get(url).raise_for_status().content
            digest=hashlib.sha256(content).hexdigest()
            expected=asset.get('digest')
            if expected and expected!='sha256:'+digest:
                raise ValueError('Tesseract download checksum mismatch.')
            package.write_bytes(content)
            print('Extracting Tesseract package inside backend/.tools/tesseract/',flush=True)
            subprocess.run([seven_zip,'x','-y',f'-o{folder}',str(package)],check=True,stdout=subprocess.DEVNULL)
            if not executable.is_file():
                raise RuntimeError('Package layout changed; tesseract.exe was not found after extraction.')
            metadata={'binary_version':VERSION,'binary_url':asset['browser_download_url'],'binary_sha256':digest}
        tessdata=folder/'tessdata'
        tessdata.mkdir(exist_ok=True)
        for language in ('vie','eng'):
            destination=tessdata/f'{language}.traineddata'
            marker=tessdata/f'{language}.best-4.1.0.sha256'
            if marker.exists() and destination.exists():
                continue
            url=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/4.1.0/{language}.traineddata'
            content=client.get(url).raise_for_status().content
            destination.write_bytes(content)
            marker.write_text(hashlib.sha256(content).hexdigest(),encoding='ascii')
            print(f'Installed {language} model (tessdata_best 4.1.0)',flush=True)
        license_text=client.get('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/4.1.0/LICENSE').raise_for_status().text
        (folder/'MODEL-LICENSE.txt').write_text(license_text,encoding='utf-8')
    if metadata:
        (folder/'source.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    subprocess.run([str(executable),'--version'],check=True)
    subprocess.run([str(executable),'--tessdata-dir',str(tessdata),'--list-langs'],check=True)
    print('Vietnamese OCR ready. No API key required.')


if __name__=='__main__':
    main()
