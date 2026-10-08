from pathlib import Path
from PIL import Image, ImageDraw

root=Path(r'C:\Users\xiemo\Desktop\ShardForge\tmp\closeout_documents_20261007\handover_render')
files=sorted(root.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[1]))
thumb_w=440; gap=24; label_h=28; cols=2; rows=3
thumb_h=round(thumb_w*2002/1547)
for start in range(0,len(files),cols*rows):
    chunk=files[start:start+cols*rows]
    canvas=Image.new('RGB',(gap+cols*(thumb_w+gap),gap+rows*(thumb_h+label_h+gap)),(238,241,245))
    draw=ImageDraw.Draw(canvas)
    for i,path in enumerate(chunk):
        im=Image.open(path).convert('RGB'); im.thumbnail((thumb_w,thumb_h))
        col=i%cols; row=i//cols
        x=gap+col*(thumb_w+gap); y=gap+row*(thumb_h+label_h+gap)
        draw.text((x,y),path.name,fill=(20,30,40))
        canvas.paste(im,(x,y+label_h))
    out=root/f'contact-{start+1:02d}-{start+len(chunk):02d}.png'
    canvas.save(out)
    print(out,canvas.size)
