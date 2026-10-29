from PIL import Image, ImageFilter
import numpy as np, colorsys
from scipy import ndimage as ndi
angles=[0,30,45,90,135,150,180,210,225,270,315,330]
def hsv(rgb):
    r,g,b=[rgb[...,i]/255. for i in range(3)]
    mx=np.max(rgb,-1)/255.; mn=np.min(rgb,-1)/255.; d=mx-mn
    h=np.zeros_like(mx)
    m=d>1e-6
    rr=(mx==r)&m; gg=(mx==g)&m&~rr; bb=m&~rr&~gg
    h[rr]=((g-b)[rr]/d[rr])%6; h[gg]=((b-r)[gg]/d[gg])+2; h[bb]=((r-g)[bb]/d[bb])+4
    h*=60; s=np.where(mx>0,d/np.maximum(mx,1e-6),0)
    return h,s,mx
res={}
for a in angles:
    im=np.array(Image.open(f'f_{a}.png')).astype(np.float32)
    rgb=im[...,:3]; al=im[...,3]
    h,s,v=hsv(rgb)
    solid=al>200
    L=(0.2126*rgb[...,0]+0.7152*rgb[...,1]+0.0722*rgb[...,2])/255.
    red=solid&((h<16)|(h>340))&(s>0.5)&(v>0.18)
    # exclude LED/tail-lights: high local variance
    lum=L
    mu=ndi.uniform_filter(lum,7); var=ndi.uniform_filter(lum**2,7)-mu**2
    red_clean=red&(var<0.004)
    red_clean=ndi.binary_opening(red_clean,iterations=1)
    # keep large components only
    lab,n=ndi.label(red_clean); sizes=ndi.sum(red_clean,lab,range(1,n+1))
    keep=np.isin(lab,1+np.where(sizes>800)[0])
    body=ndi.binary_closing(keep,iterations=2)&red
    beige=solid&(h>25)&(h<60)&(s>0.08)&(s<0.5)&(v>0.45)
    lab,n=ndi.label(beige); sizes=ndi.sum(beige,lab,range(1,n+1))
    trim=np.isin(lab,1+np.where(sizes>60)[0])
    res[a]=dict(body=body,trim=trim,L=L,al=al,v=v,s=s)
    np.save(f'm_{a}.npy',np.stack([body,trim]))
    print(a,body.sum(),trim.sum())
