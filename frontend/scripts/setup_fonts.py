"""Download pinned Nôm/CJK fonts and build complete, self-hosted WOFF2 assets."""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.tools/font-build'))
from fontTools.ttLib import TTFont

NOM_TAG='v5.19'
HAN_COMMIT='801aa43acbf9f5411f1131ec22dc3f75fda899e8'
NOM_SHA256='e017314d467498886f838c9dc442e87368760ab697c0c9df1246323e3471b2a3'


def download(url,path,expected=None):
    if not path.exists() or (expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected):
        request=urllib.request.Request(url,headers={'User-Agent':'NomWorkspace/font-setup'})
        with urllib.request.urlopen(request,timeout=120) as response:
            content=response.read()
        digest=hashlib.sha256(content).hexdigest()
        if expected and digest!=expected:
            raise ValueError(f'Checksum mismatch: {path.name}')
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_bytes(content)
        os.replace(temporary,path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rename_fallback(font,family):
    # Format conversion is a modification under OFL; use new names for the fallback faces.
    values={1:family,2:'Regular',3:family.replace(' ','')+'-Regular-Web',4:family+' Regular',
            6:family.replace(' ','')+'-Regular',16:family,17:'Regular'}
    for record in list(font['name'].names):
        if record.nameID in values:
            font['name'].setName(values[record.nameID],record.nameID,record.platformID,record.platEncID,record.langID)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cache=ROOT/'.tools/font-sources'; cache.mkdir(parents=True,exist_ok=True)
    output=ROOT/'frontend/public/fonts'; output.mkdir(parents=True,exist_ok=True)
    licenses=ROOT/'frontend/public/licenses'; licenses.mkdir(parents=True,exist_ok=True)
    specs=[
        ('NomNaTong-Regular.ttf',f'https://github.com/nomfoundation/font/releases/download/{NOM_TAG}/NomNaTong-Regular.ttf?download=1',NOM_SHA256,'nom-na-tong.woff2',None),
        ('HanaMinA.ttf',f'https://raw.githubusercontent.com/googlefonts/chinese/{HAN_COMMIT}/fonts/HanaMin/HanaMinA.ttf',None,'han-fallback-a.woff2','Nom Workspace Han A'),
        ('HanaMinB.ttf',f'https://raw.githubusercontent.com/googlefonts/chinese/{HAN_COMMIT}/fonts/HanaMin/HanaMinB.ttf',None,'han-fallback-b.woff2','Nom Workspace Han B'),
    ]
    manifest={'nom_release':NOM_TAG,'hanamin_mirror_commit':HAN_COMMIT,'format':'woff2',
              'subsetting':False,'notes':'Complete glyph coverage retained. HanaMin fallback internal names changed for OFL compliance.', 'fonts':[]}
    coverage=set()
    for filename,url,expected,target,family in specs:
        source=cache/filename
        digest=download(url,source,expected)
        with TTFont(source) as font:
            codepoints=set(font.getBestCmap())
            coverage.update(codepoints)
            if family:
                rename_fallback(font,family)
            font.flavor='woff2'
            font.save(output/target)
        manifest['fonts'].append({'file':target,'source_url':url,'source_sha256':digest,
            'woff2_sha256':hashlib.sha256((output/target).read_bytes()).hexdigest(),
            'bytes':(output/target).stat().st_size,'codepoints':len(codepoints),
            'supplementary_codepoints':sum(code>0xFFFF for code in codepoints)})
        print(f'{target}: {len(codepoints)} characters, {(output/target).stat().st_size:,} bytes',flush=True)
    download(f'https://raw.githubusercontent.com/nomfoundation/font/{NOM_TAG}/LICENSE',licenses/'nom-na-tong-MIT.txt')
    download(f'https://raw.githubusercontent.com/googlefonts/chinese/{HAN_COMMIT}/fonts/HanaMin/LICENSE.txt',licenses/'hanamin-license.txt')
    probes='天地玄黃漢字喃𠊛𡗶𠬠𡗺'
    missing=[f'{char} U+{ord(char):04X}' for char in probes if ord(char) not in coverage]
    if missing:
        raise ValueError('Font coverage check failed: '+', '.join(missing))
    manifest['combined_codepoints']=len(coverage)
    manifest['probe_characters']=probes
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Font coverage verified: {len(coverage)} distinct codepoints; Nôm supplementary probes all present.')


if __name__=='__main__':
    main()
