from skimage.morphology import convex_hull_image
from PIL import Image
import numpy as np, json
from scipy import ndimage as ndi
exec(open('mask.py').read().split('res={}')[0])  # reuse hsv()
angles=[0,30,45,90,135,150,180,210,225,270,315,330]
mir={0:[(450,190,510,236),(1056,190,1124,236)],30:[(432,200,482,236),(925,196,1020,247)],
45:[(436,186,490,222),(860,186,960,242)],90:[(566,183,636,230)],135:[(424,184,484,260)],
150:[(372,180,438,250)],180:[(474,186,524,226),(1034,186,1090,226)],210:[(1126,186,1172,256)],
225:[(1090,180,1150,260)],270:[(946,185,1033,245)],315:[(671,187,773,243),(1080,186,1120,222)],
330:[(550,180,660,236),(1102,176,1152,222)]}
stats={}
rects={150:[(885,222,958,360),(1356,228,1398,345)],135:[(1196,238,1276,370)],180:[(489,236,546,373),(1046,236,1105,373)],225:[(446,236,532,370)]}
lamps={90:[(1430,220,1500,340)],135:[(1170,225,1285,372),(1455,225,1495,330)],
150:[(868,224,948,356),(1322,220,1362,340)],180:[(476,236,536,366),(1030,236,1090,366)],
210:[(632,236,702,366),(212,236,242,356)],225:[(450,236,524,360),(110,230,150,340)],270:[(88,230,128,340)]}
for a in angles:
    im=np.array(Image.open(f'f_{a}.png')).astype(np.float32)
    rgb=im[...,:3]; al=im[...,3]; solid=al>200
    h,s,v=hsv(rgb)
    L=(0.2126*rgb[...,0]+0.7152*rgb[...,1]+0.0722*rgb[...,2])/255.
    ys,xs=np.where(solid); top=ys.min()
    # car height: ignore shadow -> use rows with solid
    bot=ys.max(); H=bot-top
    # BODY: red core incl. highlights
    redish=solid&((h<18)|(h>335))&(s>0.22)&(v>0.15)
    mu=ndi.uniform_filter(L,7); var=ndi.uniform_filter(L**2,7)-mu**2
    core=redish&(s>0.5)&(var<0.004)
    lab,n=ndi.label(ndi.binary_opening(core)); sz=ndi.sum(core,lab,range(1,n+1))
    core=np.isin(lab,1+np.where(sz>3000)[0])
    for (x0,y0,x1,y1) in lamps.get(a,[]): core[y0-6:y1+6,x0-6:x1+6]=False
    allow=(al>60)&((h<20)|(h>330))&(((s>0.2)&(v>0.15))|((s>0.4)&(v>0.07))|((s>0.06)&(v>0.55)))&(var<0.03)
    body=ndi.binary_propagation(core,mask=allow)|core
    body=ndi.binary_closing(body,iterations=3)&(al>60)
    # DARK
    dark=solid&(v<0.32)&(s<0.45)
    # ROOF: dark pixels in top band, connected
    band=np.zeros_like(solid); band[top:top+int(0.10*H)]=True
    roof=dark&band
    lab,n=ndi.label(roof); sz=ndi.sum(roof,lab,range(1,n+1))
    roof=np.isin(lab,1+np.where(sz>300)[0])
    roof=ndi.binary_closing(roof,iterations=2)&dark
    # MIRRORS
    mirror=np.zeros_like(solid)
    for (x0,y0,x1,y1) in mir[a]:
        box=np.zeros_like(solid); box[y0:y1,x0:x1]=True
        cand=box&solid&(v<0.2)&~roof
        lab_,n_=ndi.label(cand)
        if n_:
            sz_=ndi.sum(cand,lab_,range(1,n_+1)); big=np.isin(lab_,1+np.where(sz_>=0.25*sz_.max())[0])
            hull=convex_hull_image(big)
            mirror|=hull&box&solid&(v<0.7)
    # TRIM / WHEELS
    beige=solid&(h>22)&(h<62)&(s>0.07)&(s<0.5)&(v>0.42)
    lab,n=ndi.label(beige); sz=ndi.sum(beige,lab,range(1,n+1))
    trimall=np.isin(lab,1+np.where(sz>60)[0])
    lab,n=ndi.label(ndi.binary_dilation(trimall,iterations=8))
    wheels=np.zeros_like(solid)
    for i,sl in enumerate(ndi.find_objects(lab)):
        yy,xx=sl; hh=yy.stop-yy.start; ww=xx.stop-xx.start
        cy=(yy.start+yy.stop)/2
        if hh>0.18*H and 0.25<ww/hh<1.3 and (cy-top)/H>0.62:
            wheels|=(lab==i+1)
    wheels&=trimall; trim=trimall&~wheels
    for (x0,y0,x1,y1) in lamps.get(a,[]):
        dk=ndi.binary_closing(v[y0:y1,x0:x1]<0.22,iterations=2)
        filled=ndi.binary_fill_holes(dk)
        body[y0:y1,x0:x1]&=~filled
    for (x0,y0,x1,y1) in rects.get(a,[]):
        sub=v[y0:y1,x0:x1]; hh,ww=sub.shape
        best=None
        for th in (0.22,0.28,0.34):
          for it in (2,3,4,5):
            rim=ndi.binary_closing(sub<th,iterations=it)
            seed=np.zeros_like(rim); seed[0,:]=seed[-1,:]=seed[:,0]=seed[:,-1]=True
            outside=ndi.binary_propagation(seed&~rim,mask=~rim)
            lamp=~outside&~rim
            frac=lamp.mean()
            if 0.25<frac<0.85: best=ndi.binary_dilation(lamp|(rim&~outside),iterations=1); break
          if best is not None: break
        if best is None or a in (180,150): best=np.ones_like(sub,bool)
        body[y0:y1,x0:x1]&=~best
    body&=~trim&~wheels&~mirror&~roof
    lab=np.zeros(solid.shape,np.uint8)
    lab[body]=1; lab[roof]=2; lab[mirror]=3; lab[trim]=4; lab[wheels]=5
    np.save(f'lab_{a}.npy',lab)
    st={}
    for k,m in [('body',body),('roof',roof),('mirror',mirror),('trim',trim),('wheels',wheels)]:
        st[k]=float(np.median(L[m])) if m.sum() else 0.5
    stats[a]=st
    print(a,{k:int((lab==i).sum()) for i,k in enumerate(['-','body','roof','mirror','trim','wheels'])})
json.dump(stats,open('stats.json','w'))
