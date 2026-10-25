"""R22：程序產生、比較像真實照片的雪景（雪松、滑雪痕、落雪、人）與無雪山景對照。"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def make(out):
    rng=np.random.default_rng(1); W,H=640,360
    def noise(a,s=8):
        return np.clip(a+rng.normal(0,s,a.shape),0,255)
    def snowfield(i):
        a=np.zeros((H,W,3));sky=np.linspace(170,230,H)[:,None]
        a[...]=np.stack([sky-20,sky-5,sky+10],-1)[:,:,0:3] if False else 0
        for y in range(H):
            a[y]=(150+y*0.2,175+y*0.2,215) if y<H*0.45 else (235,240,250)
        im=Image.fromarray(noise(a,6).astype(np.uint8));d=ImageDraw.Draw(im)
        for k in range(9):  # snowy pines
            x=rng.integers(0,W);b=int(H*0.45)+rng.integers(-10,30);h=rng.integers(60,140)
            d.polygon([(x,b-h),(x-h//3,b),(x+h//3,b)],fill=(40,70,50))
            for t in range(3):
                yy=b-h+int(h*(t+1)/4);w=int(h/3*(t+1)/4)
                d.polygon([(x-w,yy),(x+w,yy),(x,yy-12)],fill=(245,248,252))
        if i%2:  # ski tracks
            for k in range(3): d.line([(W//2+k*15,H),(W//2+80+k*5,int(H*0.5))],fill=(205,212,228),width=3)
        if i>=2:  # falling snow
            for k in range(600):
                x,y=rng.integers(0,W),rng.integers(0,H);r=rng.integers(1,4);d.ellipse([x,y,x+r,y+r],fill=(255,255,255))
        if i==3:
            d.rectangle([300,200,316,250],fill=(200,30,30));d.ellipse([300,185,316,201],fill=(230,190,160))
        return im.filter(ImageFilter.GaussianBlur(0.8))
    for i in range(4): snowfield(i).save(os.path.join(out,f"s{i}.jpg"),quality=88)
    # 山（無雪）對照
    for i in range(2):
        im=Image.new("RGB",(W,H),(150,190,230));d=ImageDraw.Draw(im)
        d.polygon([(0,H),(200,90+i*20),(380,H)],fill=(80,110,70));d.polygon([(250,H),(470,70),(640,H)],fill=(95,120,80))
        d.rectangle([0,300,W,H],fill=(70,120,50))
        Image.fromarray(noise(np.array(im,float),8).astype(np.uint8)).save(os.path.join(out,f"m{i}.jpg"))
    return sorted(os.path.join(out,f) for f in os.listdir(out) if f.endswith(".jpg"))
