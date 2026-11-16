import json,struct,io,pathlib
import numpy as np
from PIL import Image,ImageFilter
src=pathlib.Path('/Users/jacobmatthews/Documents/mari/marina necklace refined.vrm')
b=src.read_bytes(); n=struct.unpack_from('<I',b,12)[0]; j=json.loads(b[20:20+n]); binary=b[28+n:]
def acc(i):
 q=j['accessors'][i];v=j['bufferViews'][q['bufferView']];return np.frombuffer(binary,dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[q['componentType']],count=q['count']*{'VEC3':3,'VEC2':2,'SCALAR':1,'VEC4':4}[q['type']],offset=v.get('byteOffset',0)+q.get('byteOffset',0)).reshape(q['count'],-1)
old=Image.open('output/shirt/texture_12.png').convert('RGBA'); size=old.width
# Soft fabric shading retains the garment folds without the old decorations.
gray=np.asarray(old.convert('L').filter(ImageFilter.GaussianBlur(8)),dtype=float); white=np.clip(238+(gray-25)*.16,225,250).astype('uint8'); tex=np.stack([white,white,white,np.full_like(white,255)],axis=2)
logo=Image.open('/Users/jacobmatthews/Documents/HACKCLUB/exec-b31f1f1d-b1c9-40ff-94d2-bad472687840.png').convert('RGB').crop((30,225,1225,1018)); ar=np.asarray(logo); # Make the warm white background match the shirt.
alpha=np.clip((245-ar.min(2).astype(float))/70,0,1); alpha[ar.min(2)>215]=0
p=j['meshes'][1]['primitives'][1]; positions=acc(p['attributes']['POSITION']); uvs=acc(p['attributes']['TEXCOORD_0']); faces=acc(p['indices']).reshape(-1,3)
for f in faces:
 xyz=positions[f];
 if xyz[:,2].mean()<.06:continue
 uv=uvs[f]*size; lo=np.maximum(np.floor(uv.min(0)).astype(int)-3,0); hi=np.minimum(np.ceil(uv.max(0)).astype(int)+3,size-1)
 if np.any(hi<lo):continue
 xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1)); mat=np.vstack([uv.T,np.ones(3)])
 if abs(np.linalg.det(mat))<1e-8:continue
 weights=np.linalg.solve(mat,np.stack([xx.ravel()+.5,yy.ravel()+.5,np.ones(xx.size)])); inside=(weights>=-.02).all(0); world=xyz.T@weights
 lx=(world[0]/.27+.5)*(logo.width-1); ly=(1.215-world[1])/.18*(logo.height-1); use=inside&(lx>=0)&(lx<logo.width)&(ly>=0)&(ly<logo.height)
 if not use.any():continue
 px=xx.ravel()[use];py=yy.ravel()[use];sx=lx[use].astype(int);sy=ly[use].astype(int);a=alpha[sy,sx,None];tex[py,px,:3]=(ar[sy,sx]*a+tex[py,px,:3]*(1-a)).astype('uint8')
result=Image.fromarray(tex);result.save('output/shirt/white-shirt-texture.png'); stream=io.BytesIO(); result.save(stream,format='PNG');new=stream.getvalue();pad=(-len(binary))%4;offset=len(binary)+pad;binary+=b'\0'*pad+new
j['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(new)});j['images'][12]['bufferView']=len(j['bufferViews'])-1;j['images'][12]['mimeType']='image/png'
j['materials'][8]['extensions']['VRMC_materials_mtoon']['shadeColorFactor']=[.84,.84,.86]
j['buffers'][0]['byteLength']=len(binary);binary+=b'\0'*((-len(binary))%4);js=json.dumps(j,separators=(',',':')).encode();js+=b' '*((-len(js))%4)
out=src.with_name('marina white Hack Club shirt.vrm');out.write_bytes(struct.pack('<III',0x46546c67,2,28+len(js)+len(binary))+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(binary),0x004e4942)+binary);print(out)
