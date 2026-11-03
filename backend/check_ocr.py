"""Check configuration; --live --pdf NAME --page N recognizes an actual source page."""
import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if sys.prefix == sys.base_prefix and (root / 'backend/.tools/python').exists():
    sys.path.insert(0, str(root / 'backend/.tools/python'))

from backend.ocr import KHNConfig, KimHanNomOCR, OCRError, normalize_result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Recognize one actual PDF page using the API')
    parser.add_argument('--pdf', help='PDF filename in backend/data/raw_data/')
    parser.add_argument('--page', type=int, default=1, help='PDF page number, starting at 1')
    parser.add_argument('--ocr-id', type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument('--reading-direction', type=int, choices=(1, 2), default=1)
    parser.add_argument('--lang-type', type=int, choices=(0, 1, 2), default=2)
    args = parser.parse_args()
    config = KHNConfig.from_env(root / 'backend/.env')
    print('KHN configuration:', 'configured' if config.ready else 'missing token', flush=True)
    if not config.ready:
        return 1
    if not args.live:
        print('Token presence checked only. Use --live --pdf NAME --page N to check actual OCR.')
        return 0
    if not args.pdf or Path(args.pdf).name != args.pdf or Path(args.pdf).suffix.lower() != '.pdf':
        parser.error('--live requires --pdf with a PDF filename in backend/data/raw_data/')
    folder = root / 'backend/data/raw_data'
    source = folder / args.pdf
    if not source.is_file() or source.resolve().parent != folder.resolve():
        parser.error('PDF not found in backend/data/raw_data/')
    import pymupdf
    with pymupdf.open(source) as document:
        if document.needs_pass or not 1 <= args.page <= len(document):
            parser.error('PDF is password-protected or page number is outside the document')
        page = document[args.page - 1]
        scale = min(1.5, 2400 / max(page.rect.width, page.rect.height))
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
        width,height = pixmap.width,pixmap.height
        image = pixmap.tobytes('jpeg', jpg_quality=92)
    print('Recognizing:', source.name, 'page', args.page, flush=True)
    try:
        raw = KimHanNomOCR(config).recognize(image, ocr_id=args.ocr_id, reading_direction=args.reading_direction, lang_type=args.lang_type)
        result = normalize_result(raw, width, height)
    except OCRError as error:
        print('API check failed:', str(error))
        return 1
    print('OCR succeeded:', len(result['text_lines']), 'text lines;', len(result['boxes']), 'valid boxes')
    print('Recognized text:', ' / '.join(result['text_lines']))
    for warning in result['warnings']:
        print('Notice:', warning)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
