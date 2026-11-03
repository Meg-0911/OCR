"""Crop only a selected quadrilateral; region OCR is a preview until explicit save."""
import math
from PIL import Image, ImageDraw


def crop_selection(image, points, logical_width, logical_height):
    image=image.convert('RGB')
    sx,sy=image.width/logical_width,image.height/logical_height
    polygon=[(x*sx,y*sy) for x,y in points]
    left=max(0,math.floor(min(x for x,y in polygon)))
    top=max(0,math.floor(min(y for x,y in polygon)))
    right=min(image.width,math.ceil(max(x for x,y in polygon)))
    bottom=min(image.height,math.ceil(max(y for x,y in polygon)))
    crop=image.crop((left,top,right,bottom))
    mask=Image.new('L',crop.size,0)
    ImageDraw.Draw(mask).polygon([(x-left,y-top) for x,y in polygon],fill=255)
    masked=Image.new('RGB',crop.size,'white');masked.paste(crop,(0,0),mask)
    padding=max(12,round(min(crop.size)*.15))
    padded=Image.new('RGB',(crop.width+2*padding,crop.height+2*padding),'white')
    padded.paste(masked,(padding,padding))
    scale=max(1,min(128/min(padded.size),3))
    if scale>1:
        padded=padded.resize((round(padded.width*scale),round(padded.height*scale)),Image.Resampling.LANCZOS)
    return padded
