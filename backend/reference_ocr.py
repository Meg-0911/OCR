"""Draft page allocation from companion TXT, using detected Nôm lines, never translation."""
import hashlib
import json
import re
from statistics import median

from .dictionary import is_han
from .ocr import OCRError


def sections(path):
    text=path.read_text(encoding='utf-8-sig')
    blocks=[]; current={'anchor':1,'lines':[]}
    for number,line in enumerate(text.splitlines(),1):
        marker=re.match(r'^\s*\*+\s*Page\s+(\d+)\s*\*+\s*$',line,re.IGNORECASE)
        if marker:
            if current['lines']:
                blocks.append(current)
            current={'anchor':int(marker[1]),'lines':[]}
        elif line.strip():
            current['lines'].append((number,line.strip()))
    if current['lines']:
        blocks.append(current)
    return blocks,hashlib.sha256(text.encode('utf-8')).hexdigest()


def nom_line_count(boxes,texts,direction):
    bounds=[]
    for box in boxes:
        if not any(is_han(char) for char in box['transcription']):
            continue
        axis=0 if direction==1 else 1
        coordinates=[p[axis] for p in box['points']]
        bounds.append((sum((min(coordinates),max(coordinates)))/2,max(coordinates)-min(coordinates)))
    if not bounds:
        return len([text for text in texts if any(is_han(c) for c in text)])
    tolerance=max(2,median(size for _,size in bounds)*.6)
    centers=[]
    for center,size in sorted(bounds):
        if not centers or abs(center-centers[-1])>tolerance:
            centers.append(center)
    return len(centers)


class ReferenceOCR:
    from_reference=True

    def __init__(self,store,page,path):
        self.store,self.page,self.path=store,page,path
        self.blocks,self.digest=sections(path)

    def status(self):
        return {'ready':True,'engine':'Quốc ngữ trực tiếp từ TXT · ghép nháp',
                'cache_key':'txt-draft-v1:'+self.digest,'setup':''}

    def recognize(self,image,*,han_boxes=None,han_text_lines=None,reading_direction=2,**unused):
        count=nom_line_count(han_boxes or [],han_text_lines or [],reading_direction)
        if not count:
            raise OCRError('Chưa xác định được số dòng Nôm để ghép TXT. Kiểm tra kết quả Nôm hoặc chọn đoạn TXT thủ công; dữ liệu đã có vẫn được giữ.',422)
        candidates=[block for block in self.blocks if block['anchor']<=self.page['number']]
        if not candidates:
            raise OCRError('Trang này nằm trước mốc nội dung đầu tiên trong TXT. Bỏ qua trang đặc biệt hoặc nhập Quốc ngữ thủ công.',422)
        block=candidates[-1]
        with self.store.lock,self.store.db() as db:
            previous=db.execute('SELECT allocation FROM reference_allocations WHERE page_id=?',(self.page['id'],)).fetchone()
            allocation=json.loads(previous['allocation']) if previous else None
            if not allocation or allocation['sha256']!=self.digest:
                allocated=[json.loads(row['allocation']) for row in db.execute(
                    'SELECT r.allocation FROM reference_allocations r JOIN pages p ON p.id=r.page_id WHERE p.book_id=? AND p.number<?',
                    (self.page['book_id'],self.page['number']))]
                start=max((a['end'] for a in allocated if a['sha256']==self.digest and a['anchor']==block['anchor']),default=0)
                end=min(len(block['lines']),start+count)
                if start>=end:
                    raise OCRError('Đã dùng hết đoạn TXT của mốc này. Duyệt lại ghép nháp/số dòng hoặc nhập đoạn đối chiếu thủ công; không tự lấy nội dung ở mốc khác.',422)
                chosen=block['lines'][start:end]
                allocation={'filename':self.path.name,'sha256':self.digest,'anchor':block['anchor'],'start':start,'end':end,
                            'line_start':chosen[0][0],'line_end':chosen[-1][0],'nom_lines':count,'text':'\n'.join(line for _,line in chosen)}
                db.execute('INSERT INTO reference_allocations VALUES (?,?) ON CONFLICT(page_id) DO UPDATE SET allocation=excluded.allocation',
                           (self.page['id'],json.dumps(allocation,ensure_ascii=False)))
        return {'boxes':[],'text_lines':allocation['text'].splitlines(),
                'reference_draft':allocation,'target_origin':f"txt-draft:{self.path.name}:{allocation['line_start']}-{allocation['line_end']}",
                'warnings':['Quốc ngữ lấy trực tiếp từ TXT, ghép NHÁP theo số dòng Nôm. Kiểm tra chỗ thiếu/thừa, trang bỏ qua và dấu phân trang khi căn chỉnh.']}
