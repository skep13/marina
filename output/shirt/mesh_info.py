from pathlib import Path
import json,struct
import numpy as np
from PIL import Image,ImageDraw
root=Path('/Users/jacobmatthews/Documents/mari/design-preview');b=(root.parent/'marina necklace refined.vrm').read_bytes();n=struct.unpack_from('<I',b,12)[0];j=json.loads(b[20:20+n]);d=b[28+n:]
def read(i):
 a=j['accessors'][i];v=j['bufferViews'][a['bufferView']];return np.frombuffer(d,dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[a['componentType']],count=a['count']*{'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']],offset=v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(a['count'],-1)
for mesh in j['meshes']:
 for prim in mesh['primitives']:
  if prim['material']!=8:continue
  uv=read(prim['attributes']['TEXCOORD_0']);pos=read(prim['attributes']['POSITION']);tri=read(prim['indices']).reshape(-1,3);parent={int(i):int(i) for i in np.unique(tri)}
  def find(a):
   while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
   return a
  for t in tri:
   for a in t[1:]:parent[find(int(a))]=find(int(t[0]))
  comps={}
  for i in parent:comps.setdefault(find(i),[]).append(i)
  im=Image.new('RGB',(2048,2048),'#202430');draw=ImageDraw.Draw(im)
  for k,ids in enumerate(sorted(comps.values(),key=len,reverse=True)):
   bounds=np.array([uv[ids].min(axis=0),uv[ids].max(axis=0)]);print(k,len(ids),'uv',bounds.tolist(),'xyz mean',pos[ids].mean(axis=0).tolist(),'xyz minmax',pos[ids].min(axis=0).tolist(),pos[ids].max(axis=0).tolist())
   idset=set(ids);color=['#66748d','#7f719c','#59697f','#847a93','#485c77'][k%5]
   for t in tri:
    if int(t[0]) not in idset:continue
    pts=[tuple((uv[i]*2048).tolist()) for i in t];draw.polygon(pts,fill=color);draw.line(pts+[pts[0]],fill='#afb8c9',width=1)
   center=((bounds[0]+bounds[1])*.5*2048).tolist();draw.text(center,str(k),fill='white',stroke_width=2,stroke_fill='black')
  im.save(root/'hoodie-uv-guide.png')
