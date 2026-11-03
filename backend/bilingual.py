"""Language-level OCR checkpoints for mixed Nôm / Quốc ngữ pages."""
import io
from uuid import uuid4
from PIL import Image

from .ocr import normalize_result, OCRError
from .vietnamese_ocr import image_regions

HAN_KEYS=('ocr_id','lang_type','reading_direction','epitaph','tag')


def signature(settings,language):
    if language=='han':
        return {**{key:settings.get(key) for key in HAN_KEYS},'source_regions':settings.get('source_regions') or []}
    return {'vi_psm':settings.get('vi_psm',11),'target_regions':settings.get('target_regions') or [],
            'vi_engine':settings.get('vi_engine'),
            'han_mask':signature(settings,'han') if settings.get('mode')=='bilingual' else None}


def part_ready(result,language,settings):
    if not result:
        return False
    completed=result.get('completed_languages',['han'] if 'text_lines' in result else [])
    saved=result.get('language_settings',{}).get(language)
    if saved is None and language=='han':
        saved=signature(result.get('settings',{}),'han')
    return language in completed and saved==signature(settings,language)


def desired_languages(settings):
    return ('han','vi') if settings.get('mode')=='bilingual' else ('vi',) if settings.get('mode')=='vi' else ('han',)


def has_edits(page,language):
    if ('source_text' if language=='han' else 'target_text') in page.get('edited_fields',[]):
        return True
    if language=='han':
        return bool(page.get('source_text','').strip() or (page['category']!='vi' and any(b['transcription'].strip() for b in page['boxes'])))
    return bool(page.get('target_text','').strip() or page.get('vi_boxes') or (page['category']=='vi' and any(b['transcription'].strip() for b in page['boxes'])))


def needs_ocr(page,settings,cached):
    if page['status']=='done' and not (page.get('source_text') or page.get('target_text') or page['boxes'] or page.get('vi_boxes')):
        return False
    return any(not has_edits(page,language) and not part_ready(cached,language,settings) for language in desired_languages(settings))


def recognize(page,settings,force,*,cached,image_bytes,han_provider,vi_provider,save):
    languages=desired_languages(settings)
    if not force and all(part_ready(cached,language,settings) for language in languages):
        return cached | {'cached':True}
    result={**(cached or {}),'page_id':page['id'],'version':page['version'],'result_id':uuid4().hex,
            'reading_direction':settings['reading_direction'],'settings':settings,'cached':False}
    result['completed_languages']=list(cached.get('completed_languages',['han']) if cached else [])
    result['language_settings']=dict(cached.get('language_settings',{}) if cached else {})
    if cached and 'han' not in result['language_settings']:
        result['language_settings']['han']=signature(cached.get('settings',{}),'han')
    result.setdefault('boxes',[]); result.setdefault('text_lines',[])
    result.setdefault('vi_boxes',[]); result.setdefault('vi_text_lines',[])
    warnings=list(cached.get('warnings',[]) if cached else [])
    responses={}
    image=None
    for language in languages:
        if not force and part_ready(cached,language,settings):
            continue
        if not force and has_edits(page,language):
            if language=='han':
                result['boxes']=page['boxes']
                result['text_lines']=(page.get('source_text') or '\n'.join(b['transcription'] for b in page['boxes'])).splitlines()
            else:
                result['vi_boxes']=page.get('vi_boxes',[])
                result['vi_text_lines']=(page.get('target_text') or '\n'.join(b['transcription'] for b in page['boxes'] if page['category']=='vi')).splitlines()
        else:
            if image is None:
                image=image_bytes()
            if language=='han':
                picture=Image.open(io.BytesIO(image)).convert('RGB')
                boxes,texts,han_warnings=[],[],[]
                for crop,x,y in image_regions(picture,settings.get('source_regions')):
                    if not settings.get('source_regions'):
                        content=image
                    else:
                        stream=io.BytesIO(); crop.save(stream,format='JPEG',quality=94); content=stream.getvalue()
                    raw=han_provider.recognize(content,**{key:settings[key] for key in HAN_KEYS})
                    responses.setdefault('han',[]).append(raw)
                    # Preserve raw output even if the response format cannot be normalized.
                    save(None,responses,result['result_id'])
                    normalized=normalize_result(raw,crop.width,crop.height)
                    for box in normalized['boxes']:
                        box['points']=[[a+x,b+y] for a,b in box['points']]
                    boxes.extend(normalized['boxes']); texts.extend(normalized['text_lines']); han_warnings.extend(normalized['warnings'])
                result['boxes']=boxes; result['text_lines']=texts
                warnings.extend(han_warnings)
            else:
                extra={'han_text_lines':result['text_lines'],'reading_direction':settings['reading_direction']} if getattr(vi_provider,'from_reference',False) else {}
                target=vi_provider.recognize(image,regions=settings.get('target_regions'),
                    han_boxes=result['boxes'] if settings.get('mode')=='bilingual' else page['boxes'],psm=settings.get('vi_psm',11),**extra)
                responses['vi']=target
                result['vi_boxes']=target['boxes']; result['vi_text_lines']=target['text_lines']
                if target.get('reference_draft'):
                    result['reference_draft']=target['reference_draft']
                    result['target_origin']=target['target_origin']
                warnings.extend(target.get('warnings',[]))
                if not any(text.strip() for text in target['text_lines']):
                    result['warnings']=warnings
                    save(result,responses,result['result_id'])
                    raise OCRError('Chưa đọc được nội dung Quốc ngữ. Chọn vùng mẫu Quốc ngữ hoặc hiệu đính thủ công. Phần Nôm đã lưu, tiếp tục sẽ không gọi lại phần đó.',502)
        if language not in result['completed_languages']:
            result['completed_languages'].append(language)
        result['language_settings'][language]=signature(settings,language)
        result['warnings']=warnings
        # A completed language survives a later language failing, or a process restart.
        save(result,responses,result['result_id'])
    return result
