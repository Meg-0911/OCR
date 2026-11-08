import io
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from backend.bilingual import recognize
from backend.han_layout import character_regions, prepare_han_image, pack_lines, map_characters
from backend.store import ordered_boxes, nom_export_boxes
from backend.vietocr import line_regions


def mixed_page():
    picture=Image.new('RGB',(600,400),'white')
    draw=ImageDraw.Draw(picture)
    for top in (50,220):
        for left in (60,180,300,420):
            draw.rectangle((left,top,left+35,top+45),fill='black')
            draw.rectangle((left,top+65,left+45,top+80),fill=(180,40,60))
    return picture


def test_ink_coordinates_exclude_interlinear_red_text_and_preserve_reading_order():
    picture,mask,colored=prepare_han_image(mixed_page())
    assert colored
    glyphs=character_regions(mask,2)
    assert [glyph['line'] for glyph in glyphs]==[0]*4+[1]*4
    assert all(glyph['bounds'][3]<110 or 210<glyph['bounds'][1]<230 for glyph in glyphs)
    assert tuple(np.asarray(picture)[120,65])==(255,255,255)
    vertical=character_regions(mask.T,1)
    assert len(vertical)==8
    assert vertical[0]['bounds'][0]>vertical[-1]['bounds'][0]


def test_mapping_never_shifts_characters_when_recognizer_drops_a_glyph():
    picture,mask,_=prepare_han_image(mixed_page())
    glyphs=character_regions(mask,2)
    atlas,placements=pack_lines(picture,glyphs)
    result={'boxes':[
        {'points':[[0,0],[atlas.width,0],[atlas.width,140],[0,140]],'transcription':'天地𠊛人'},
        {'points':[[0,140],[atlas.width,140],[atlas.width,atlas.height],[0,atlas.height]],'transcription':'玄黃宇'},
    ]}
    mapped=map_characters(result,placements)
    assert mapped['text_lines']==['天地𠊛人','□□□□']
    assert len(mapped['boxes'])==8 and mapped['warnings']
    for box,glyph in zip(mapped['boxes'],glyphs):
        assert box['points'][0]==list(glyph['bounds'][:2])


def test_vertical_nom_glyphs_become_column_segments_with_real_gap():
    glyphs=[]
    for i,top in enumerate((10,35,60,140)):
        glyphs.append({'line':0,'bounds':(70,top,90,top+20),'atlas':(i*30,0,i*30+20,20)})
    result={'boxes':[{'points':[[0,0],[120,0],[120,20],[0,20]],'transcription':'天地玄黃'}]}
    mapped=map_characters(result,glyphs,1)
    assert [box['transcription'] for box in mapped['boxes']]==list('天地玄黃')
    exported=nom_export_boxes(mapped['boxes'],1)
    assert [box['transcription'] for box in exported]==['天地玄','黃']
    assert exported[0]['points']==[[70,10],[90,10],[90,80],[70,80]]


def test_empty_drawn_box_does_not_expand_a_neighboring_export_box():
    def box(identifier, text, left, right):
        return {'id':identifier,'transcription':text,
                'points':[[left,10],[right,10],[right,30],[left,30]]}
    exported=nom_export_boxes([
        box('first','天',10,20),
        box('empty','',22,24),
        box('last','地',26,36),
    ],2)
    assert [item['transcription'] for item in exported]==['天','','地']
    assert exported[0]['points']==[[10,10],[20,10],[20,30],[10,30]]


def test_red_nom_ink_is_selected_and_excluded_from_vietnamese_rows():
    image=mixed_page()
    pixels=np.asarray(image).copy()
    black=np.all(pixels==[0,0,0],axis=2)
    red=np.all(pixels==[180,40,60],axis=2)
    pixels[black]=[180,40,60]
    pixels[red]=[0,0,0]
    image=Image.fromarray(pixels)
    prepared,mask,colored=prepare_han_image(image)
    assert colored
    glyphs=character_regions(mask,2)
    assert len(glyphs)==8
    assert all(np.asarray(prepared)[75,70]==[255,255,255])
    han_boxes=[{'points':[[x,y],[x+35,y],[x+35,y+45],[x,y+45]],'transcription':'□'}
               for y in (50,220) for x in (60,180,300,420)]
    rows,_=line_regions(image,han_boxes)
    assert rows and all(100<row[1]<220 or row[1]>270 for row in rows)


def test_character_order_groups_uneven_tops_before_sorting_left_to_right():
    def box(text,left,top):
        return {'transcription':text,'points':[[left,top],[left+30,top],[left+30,top+40],[left,top+40]]}
    boxes=[box('地',70,45),box('玄',10,150),box('天',10,50),box('黃',70,155)]
    assert [box['transcription'] for box in ordered_boxes(boxes,'both',2)]==list('天地玄黃')


def test_two_page_scan_reads_left_page_before_right_page():
    def box(text,left,top):
        return {'transcription':text,'points':[[left,top],[left+20,top],[left+20,top+50],[left,top+50]]}
    boxes=[box('right',450,10),box('left',150,10)]
    assert [b['transcription'] for b in ordered_boxes(boxes,'ch',1,(600,300))]==['left','right']
    assert [b['transcription'] for b in ordered_boxes(boxes,'vi',2,(600,300))]==['left','right']


def test_high_resolution_coordinates_are_normalized_for_both_engines():
    image=io.BytesIO();Image.new('RGB',(400,600),'white').save(image,format='JPEG')
    page={'id':'page','version':0,'width':200,'height':300,'status':'pending','category':'both',
          'boxes':[],'vi_boxes':[],'source_text':'','target_text':'','edited_fields':[]}
    han=SimpleNamespace(recognize=lambda *args,**kwargs:{'result_ocr_text':['天地'],
        'result_bbox':[[[20,40],[100,40],[100,80],[20,80]]]})
    def vietnamese(image,**settings):
        assert settings['han_boxes'][0]['points']==[[20,40],[100,40],[100,80],[20,80]]
        return {'boxes':[{'id':'vi','transcription':'Thiên địa','points':[[40,100],[200,100],[200,150],[40,150]]}],
                'text_lines':['Thiên địa'],'warnings':[]}
    result=recognize(page,{'mode':'bilingual','reading_direction':2},False,cached=None,
        image_bytes=image.getvalue,han_provider=han,vi_provider=SimpleNamespace(recognize=vietnamese),save=lambda *args:None)
    assert result['boxes'][0]['points']==[[10,20],[50,20],[50,40],[10,40]]
    assert result['vi_boxes'][0]['points']==[[20,50],[100,50],[100,75],[20,75]]
