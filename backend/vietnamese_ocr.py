"""Local Vietnamese OCR, with optional page regions and real OCR coordinates."""
import csv
import io
import math
import os
import shutil
import subprocess
import tempfile
import unicodedata
import re
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from PIL import Image, ImageDraw

from .ocr import OCRError
from .dictionary import is_han


def image_regions(image, regions):
    """Yield crops and their original-image offsets. Empty regions means the full page."""
    width,height=image.size
    for region in regions or [[0,0,1,1]]:
        left,top,right,bottom=region
        box=(max(0,math.floor(left*width)),max(0,math.floor(top*height)),min(width,math.ceil(right*width)),min(height,math.ceil(bottom*height)))
        yield image.crop(box),box[0],box[1]


def parse_tsv(tsv, offset=(0,0), scale=1):
    words=[]
    for row in csv.DictReader(io.StringIO(tsv),delimiter='\t'):
        text=(row.get('text') or '').strip()
        if row.get('level')!='5' or not text:
            continue
        try:
            confidence=float(row['conf'])
            x,y,w,h=(float(row[key])/scale for key in ('left','top','width','height'))
        except (KeyError,ValueError):
            continue
        if not all(math.isfinite(value) for value in (confidence,x,y,w,h)):
            continue
        latin=sum('LATIN' in unicodedata.name(c,'') for c in text)
        letters=sum(c.isalpha() for c in text)
        if confidence<10 or not latin or latin<letters/2 or w<=0 or h<=0:
            continue
        words.append({'text':text,'confidence':confidence,'x':x+offset[0],'y':y+offset[1],'w':w,'h':h})
    # Sparse-text mode often produces individual words; merge words sharing a baseline.
    rows=[]
    for word in sorted(words,key=lambda item:(item['y']+item['h']/2,item['x'])):
        cy=word['y']+word['h']/2
        match=next((line for line in rows if abs(line['cy']-cy)<=max(line['height'],word['h'])*.45),None)
        if match is None:
            rows.append({'cy':cy,'height':word['h'],'words':[word]})
        else:
            match['words'].append(word)
    boxes=[]
    for line in sorted(rows,key=lambda row:row['cy']):
        parts=sorted(line['words'],key=lambda item:item['x'])
        x=min(w['x'] for w in parts); y=min(w['y'] for w in parts)
        right=max(w['x']+w['w'] for w in parts); bottom=max(w['y']+w['h'] for w in parts)
        boxes.append({'id':'vi-'+uuid4().hex,'transcription':' '.join(w['text'] for w in parts),
                      'points':[[x,y],[right,y],[right,bottom],[x,bottom]],
                      'confidence':round(sum(w['confidence'] for w in parts)/len(parts),2)})
    return boxes


def clean_boxes(boxes,width,height):
    cleaned=[]
    for box in boxes:
        if re.match(r'^(?:part\b.*page\b|image\s*id\b)',box['transcription'],re.IGNORECASE):
            continue
        box['points']=[[max(0,min(width,x)),max(0,min(height,y))] for x,y in box['points']]
        cleaned.append(box)
    return cleaned


class VietnameseOCR:
    def __init__(self,root):
        values={**dotenv_values(root/'backend/.env'),**os.environ}
        folder=root/'backend/.tools/tesseract'
        default=folder/'tesseract.exe' if os.name=='nt' else Path(shutil.which('tesseract') or '/usr/bin/tesseract')
        self.command=str(values.get('TESSERACT_CMD') or default)
        self.tessdata=Path(values.get('TESSDATA_DIR') or (folder/'tessdata' if os.name=='nt' else '/usr/share/tesseract-ocr/5/tessdata'))
        self.temporary=root/'backend/.tools/ocr-temp'

    def status(self):
        return {'ready':bool((Path(self.command).is_file() or shutil.which(self.command)) and (self.tessdata/'vie.traineddata').is_file()),
                'engine':'Tesseract vie+eng tại máy','setup':'py backend/setup_vietnamese_ocr.py'}

    def recognize(self,image,*,regions=None,han_boxes=None,psm=11):
        if not self.status()['ready']:
            raise OCRError('Chưa cài OCR Quốc ngữ. Chạy py backend/setup_vietnamese_ocr.py rồi khởi động lại backend.',503)
        original=Image.open(io.BytesIO(image)).convert('RGB')
        prepared=original.copy()
        painter=ImageDraw.Draw(prepared)
        for box in han_boxes or []:
            if not any(is_han(char) for char in box['transcription']):
                continue
            points=box['points']
            painter.rectangle((min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)),fill='white')
        boxes=[]
        self.temporary.mkdir(parents=True,exist_ok=True)
        for crop,x,y in image_regions(prepared,regions):
            scale=min(3,max(1,1600/crop.width))
            scaled=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.LANCZOS)
            # Use the effective pixel ratio rather than a rounded target-size assumption.
            scale=scaled.width/crop.width
            with tempfile.TemporaryDirectory(dir=self.temporary) as folder:
                path=Path(folder)/'page.png'
                scaled.save(path)
                try:
                    completed=subprocess.run([self.command,str(path),'stdout','--tessdata-dir',str(self.tessdata),'-l','vie+eng','--oem','1','--psm',str(psm),'tsv'],
                        capture_output=True,encoding='utf-8',errors='replace',timeout=180,check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                except subprocess.TimeoutExpired:
                    raise OCRError('OCR Quốc ngữ quá thời gian; phần Nôm đã có checkpoint được giữ lại.',504) from None
                except OSError:
                    raise OCRError('Không chạy được Tesseract. Kiểm tra TESSERACT_CMD hoặc cài lại OCR Quốc ngữ.',503) from None
                if completed.returncode:
                    raise OCRError('Tesseract không xử lý được ảnh Quốc ngữ. Kiểm tra mô hình vie+eng và đường dẫn cấu hình.')
                boxes.extend(parse_tsv(completed.stdout,(x,y),scale))
        warnings=[]
        boxes=clean_boxes(boxes,original.width,original.height)
        if not boxes:
            warnings.append('Không nhận được dòng Quốc ngữ đủ tin cậy. Chữ viết tay/ảnh mờ có thể cần hiệu đính hoặc engine khác; vẫn lưu được văn bản không cần box.')
        if any(box['confidence']<60 for box in boxes):
            warnings.append('Có dòng Quốc ngữ độ tin cậy thấp; đọc lại trước khi hoàn thành.')
        return {'boxes':boxes,'text_lines':[box['transcription'] for box in boxes],'warnings':warnings}




def create_vietnamese_ocr(root):
    values={**dotenv_values(root/'backend/.env'),**os.environ}
    provider=(values.get('VI_OCR_PROVIDER') or 'vietocr').strip().lower()
    if provider=='vietocr':
        from .vietocr import VietOCR
        return VietOCR(root)
    if provider not in ('tesseract','google_vision'):
        raise ValueError('VI_OCR_PROVIDER must be vietocr or tesseract.')
    # Legacy google_vision settings deliberately fall back to local OCR; no cloud calls.
    return VietnameseOCR(root)
