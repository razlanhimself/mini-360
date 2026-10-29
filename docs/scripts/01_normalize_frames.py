from PIL import Image
import numpy as np
src='/mnt/user-data/uploads/'
angles=[0,30,45,90,135,150,180,210,225,270,315,330]
# cropped frames: scale 0.8, center x, bottom y (on 2560x1536 canvas)
crop={30:(1190,1122),90:(1277,1040),150:(1320,1110),210:(1240,1118)}
S=0.8
X0,Y0,X1,Y1=380,330,2180,1170   # common crop window
OUTW=1600
for a in angles:
    im=Image.open(f'{src}CR_{a}.png').convert('RGBA')
    if a in crop:
        cx,by=crop[a]
        w,h=im.size
        im2=im.resize((round(w*S),round(h*S)),Image.LANCZOS)
        al=np.array(im2)[...,3]; ys,xs=np.where(al>20)
        canvas=Image.new('RGBA',(2560,1536),(0,0,0,0))
        bx=(xs.min()+xs.max())/2
        canvas.alpha_composite(im2,(int(round(cx-bx)),int(round(by-ys.max()))))
        im=canvas
    im=im.crop((X0,Y0,X1,Y1))
    im=im.resize((OUTW,round(OUTW*(Y1-Y0)/(X1-X0))),Image.LANCZOS)
    im.save(f'f_{a}.png')
print(im.size)
