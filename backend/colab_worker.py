"""GPU worker for exported workspace bundles. Never opens the local database."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

from PIL import Image
from .colab_exchange import SCHEMA
from .vietocr import VietOCR, CACHE_KEY


def run(bundle, output, root, limit=0):
    os.environ['VI_OCR_DEVICE'] = 'cuda'
    provider = VietOCR(root)
    # Disable Tesseract fallback: a GPU job must not silently change OCR engines.
    provider.fallback.status = lambda: {'ready': False}
    provider.model = provider.create_model()
    output.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest['schema'] != SCHEMA:
            raise ValueError('Unsupported bundle schema')
        entries = manifest['pages'][:limit] if limit else manifest['pages']
        for i, entry in enumerate(entries, 1):
            cache = output / (manifest['bundle_id'] + '-' + entry['page_id'] + '.json')
            try:
                content = archive.read(entry['image'])
                if hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise ValueError('Image checksum mismatch')
                if cache.exists():
                    record = json.loads(cache.read_text(encoding='utf-8'))
                else:
                    result = provider.recognize(
                        content, regions=entry['target_regions'], han_boxes=entry['han_boxes'],
                        ink_profile=entry.get('settings', {}).get('ink_profile', 'red_qn'),
                    )
                    if not result['boxes']:
                        raise ValueError('Không tìm thấy dòng; chỉnh vùng Quốc ngữ ở ứng dụng và xuất lại.')
                    record = {'page_id': entry['page_id'], 'sha256': entry['sha256'], 'boxes': result['boxes']}
                    temporary = cache.with_suffix('.tmp')
                    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
                    temporary.replace(cache)
                records.append(record)
                print(f"{i}/{len(entries)} {entry['page_id']}: {len(record['boxes'])} box", flush=True)
            except Exception as exc:
                errors.append({'page_id': entry['page_id'], 'error': str(exc)})
                print('ERROR', entry['page_id'], str(exc), flush=True)
    import onnxruntime as ort
    payload = {'schema': SCHEMA, 'bundle_id': manifest['bundle_id'], 'pages': records,
               'engine': CACHE_KEY, 'runtime': ort.__version__, 'device': 'cuda',
               'encoder_providers': provider.model.encoder.get_providers(),
               'decoder_providers': provider.model.decoder.get_providers()}
    destination = output / (manifest['bundle_id'] + '-results.zip')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('results.json', json.dumps(payload, ensure_ascii=False))
        archive.writestr('errors.json', json.dumps(errors, ensure_ascii=False, indent=2))
        for entry in entries[:3]:
            record = next((r for r in records if r['page_id'] == entry['page_id']), None)
            if record:
                from PIL import ImageDraw
                with zipfile.ZipFile(bundle) as source:
                    image = Image.open(io.BytesIO(source.read(entry['image']))).convert('RGB')
                draw = ImageDraw.Draw(image)
                for b in record['boxes']:
                    points = [tuple(p) for p in b['points']]
                    draw.line(points + [points[0]], fill='red', width=2)
                preview = io.BytesIO()
                image.save(preview, format='JPEG')
                archive.writestr('previews/' + entry['page_id'] + '.jpg', preview.getvalue())
    print(f'Success: {len(records)}; errors: {len(errors)}; selected: {len(entries)}/{len(manifest["pages"])}')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    print(run(args.bundle, args.output, Path(__file__).resolve().parents[1], args.limit))
