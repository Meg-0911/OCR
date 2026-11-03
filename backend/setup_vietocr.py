"""Download pinned ONNX files for local Vietnamese handwriting OCR. No book upload."""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'vudang449/vietocr-vietnamese-handwriting'
REVISION = 'f1973b930f907c378f6e3152ce9d8658724b228a'
FILES = {
    'encoder_fp16.onnx': '76d0f32db0b8e2e9fe511fc8f2fabc4714279056446f71e019889252a33cc585',
    'decoder_fp16.onnx': '9074104e8bf7f78da53f5fc003cae1ef4c54b4c811069fa893c41980d13531c1',
    'vocab.txt': '17f72cc46a4c2ac47bde547964df342d5b110eb325b3018940df173f43438da1',
    'README.md': 'f3331917df742020f19d5ef4d6006a949c8c66d4ba81f595b5d84e0dc358fb51',
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    folder = ROOT / 'backend/.tools/vietocr'
    folder.mkdir(parents=True, exist_ok=True)
    sources = []
    for filename, expected in FILES.items():
        destination = folder / filename
        if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{filename}?download=true'
            request = urllib.request.Request(url, headers={'User-Agent': 'NomWorkspace/model-setup'})
            temporary = destination.with_suffix(destination.suffix + '.tmp')
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
                raise ValueError(f'Checksum mismatch: {filename}')
            temporary.replace(destination)
        sources.append({'file': filename, 'sha256': expected, 'bytes': destination.stat().st_size})
        print(f'Ready: {filename} ({destination.stat().st_size:,} bytes)', flush=True)
    license_path = folder / 'APACHE-2.0.txt'
    if not license_path.exists():
        request = urllib.request.Request('https://raw.githubusercontent.com/pbcquoc/vietocr/master/LICENSE',
                                         headers={'User-Agent': 'NomWorkspace/model-setup'})
        with urllib.request.urlopen(request, timeout=60) as response:
            license_path.write_bytes(response.read())
    (folder / 'source.json').write_text(json.dumps({
        'model': MODEL, 'revision': REVISION, 'license': 'apache-2.0 (model card)',
        'runtime': 'ONNX Runtime CPUExecutionProvider', 'files': sources,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('VietOCR CPU ready. Restart the backend after setup. No API key required.')


if __name__ == '__main__':
    main()
