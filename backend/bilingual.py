"""Language-level OCR checkpoints for mixed Nôm / Quốc ngữ pages."""
import io
from uuid import uuid4
from PIL import Image

from .ocr import normalize_result, OCRError, OCRPaused
from .vietnamese_ocr import image_regions
from .han_layout import prepare_han_image, character_regions, pack_lines, map_characters, jpeg_bytes

HAN_KEYS=('ocr_id','lang_type','reading_direction','epitaph','tag','font_type')


def signature(settings,language):
    if language=='han':
        return {**{key:settings.get(key) for key in HAN_KEYS},'source_regions':settings.get('source_regions') or [],'pipeline_version':settings.get('pipeline_version')}
    return {'vi_psm':settings.get('vi_psm',11),'target_regions':settings.get('target_regions') or [],
            'vi_engine':settings.get('vi_engine'),
            'han_mask':signature(settings,'han') if settings.get('mode')=='bilingual' else None}


def part_ready(result,language,settings):
    if not result:
        return False
    completed=result.get('cached_languages',result.get('completed_languages',['han'] if 'text_lines' in result else []))
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
    if page['status']=='done':
        return False
    return any(not part_ready(cached,language,settings) and not keep_geometry(page,language,cached) for language in desired_languages(settings))


def keep_geometry(page,language,cached):
    key='boxes' if language=='han' else 'vi_boxes'
    return bool(page.get(key)) and (key in page.get('edited_fields',[]) or (not cached and has_edits(page,language)))


def recognize(page,settings,force,*,cached,image_bytes,han_provider,vi_provider,save,should_pause=None):
    languages=desired_languages(settings)
    if not force and all(part_ready(cached,language,settings) for language in languages):
        return cached | {'cached':True,'completed_languages':list(languages),'requested_languages':list(languages)}
    result={**(cached or {}),'page_id':page['id'],'version':page['version'],'result_id':uuid4().hex,
            'reading_direction':settings['reading_direction'],'settings':settings,'cached':False,
            'requested_languages':list(languages)}
    result['cached_languages']=list(cached.get('cached_languages',cached.get('completed_languages',['han'] if cached and 'text_lines' in cached else [])) if cached else [])
    result['completed_languages']=[language for language in languages if part_ready(cached,language,settings)]
    result['language_settings']=dict(cached.get('language_settings',{}) if cached else {})
    if cached and 'han' not in result['language_settings']:
        result['language_settings']['han']=signature(cached.get('settings',{}),'han')
    result.setdefault('boxes',[]); result.setdefault('text_lines',[])
    result.setdefault('vi_boxes',[]); result.setdefault('vi_text_lines',[])
    warnings=list(cached.get('warnings',[]) if cached else [])
    responses={}
    image=None
    for language in languages:
        if should_pause and should_pause():
            raise OCRPaused()
        if not force and part_ready(cached,language,settings):
            continue
        if not force and keep_geometry(page,language,cached):
            if language=='han':
                result['boxes']=page['boxes']
                result['text_lines']=(page.get('source_text') or '\n'.join(b['transcription'] for b in page['boxes'])).splitlines()
            else:
                result['vi_boxes']=page.get('vi_boxes',[])
                result['vi_text_lines']=(page.get('target_text') or '\n'.join(b['transcription'] for b in page['boxes'] if page['category'] in ('vi','both'))).splitlines()
        else:
            if image is None:
                image=image_bytes()
            if language=='han':
                picture=Image.open(io.BytesIO(image)).convert('RGB')
                boxes,texts,han_warnings=[],[],[]
                for crop,x,y in image_regions(picture,settings.get('source_regions')):
                    prepared, mask, colored = prepare_han_image(crop)
                    glyphs = character_regions(mask,settings['reading_direction']) if colored else []
                    packed = colored and 4 <= len(glyphs) <= 300
                    payload = {key:settings[key] for key in HAN_KEYS if key in settings}
                    if packed:
                        atlas, placements = pack_lines(prepared,glyphs)
                        content = jpeg_bytes(atlas)
                        payload['reading_direction']=2
                    else:
                        atlas = prepared
                        content=jpeg_bytes(prepared) if colored or settings.get('source_regions') else image
                    raw=han_provider.recognize(content,**payload)
                    responses.setdefault('han',[]).append(raw)
                    # Preserve raw output even if the response format cannot be normalized.
                    save(None,responses,result['result_id'])
                    normalized=normalize_result(raw,atlas.width,atlas.height)
                    if packed:
                        normalized=map_characters(normalized,placements,settings['reading_direction'])
                    for box in normalized['boxes']:
                        box['points']=[[a+x,b+y] for a,b in box['points']]
                    boxes.extend(normalized['boxes']); texts.extend(normalized['text_lines']); han_warnings.extend(normalized['warnings'])
                result['boxes']=boxes; result['text_lines']=texts
                sx=page['width']/picture.width; sy=page['height']/picture.height
                for box in result['boxes']:
                    box['points']=[[a*sx,b*sy] for a,b in box['points']]
                warnings.extend(han_warnings)
            else:
                extra={'han_text_lines':result['text_lines'],'reading_direction':settings['reading_direction']} if getattr(vi_provider,'from_reference',False) else {}
                picture=Image.open(io.BytesIO(image))
                sx=picture.width/page['width']; sy=picture.height/page['height']
                masks=[{**box,'points':[[a*sx,b*sy] for a,b in box['points']]} for box in (result['boxes'] if settings.get('mode')=='bilingual' else page['boxes'])]
                target=vi_provider.recognize(image,regions=settings.get('target_regions'),
                    han_boxes=masks,psm=settings.get('vi_psm',11),**extra)
                for box in target['boxes']:
                    box['points']=[[a/sx,b/sy] for a,b in box['points']]
                responses['vi']=target
                result['vi_boxes']=target['boxes']; result['vi_text_lines']=target['text_lines']
                if target.get('reference_draft'):
                    result['reference_draft']=target['reference_draft']
                    result['target_origin']=target['target_origin']
                warnings.extend(target.get('warnings',[]))
                if not any(text.strip() for text in target['text_lines']):
                    result['warnings']=warnings
                    save(result,responses,result['result_id'])
                    raise OCRError('Chưa đọc được nội dung Quốc ngữ. Chọn vùng mẫu Quốc ngữ hoặc Gán nhãn thủ công. Phần Nôm đã lưu, tiếp tục sẽ không gọi lại phần đó.',502)
        if language not in result['completed_languages']:
            result['completed_languages'].append(language)
        if language not in result['cached_languages']:
            result['cached_languages'].append(language)
        result['language_settings'][language]=signature(settings,language)
        result['warnings']=warnings
        # A completed language survives a later language failing, or a process restart.
        save(result,responses,result['result_id'])
    return result
