exec(open('output/shirt/mesh_info.py').read().split('for mesh')[0].replace("root.parent/'marina necklace refined.vrm'", "Path('/Users/jacobmatthews/marina/output/shirt/base.vrm')"))
data=bytearray(d)
def access(a,typ,component=5126,target=34962):
 a=np.asarray(a,dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[component]);data.extend(b'\0'*((-len(data))%4));off=len(data);data.extend(a.tobytes());j['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':a.nbytes,'target':target});q={'bufferView':len(j['bufferViews'])-1,'componentType':component,'count':len(a),'type':typ}
 if typ=='VEC3':q.update(min=a.min(0).tolist(),max=a.max(0).tolist())
 j['accessors'].append(q);return len(j['accessors'])-1
prims=j['meshes'][1]['primitives'];p=next(p for p in prims if p['material']==8);attrs=p['attributes'];pos=read(attrs['POSITION']).copy();uv=read(attrs['TEXCOORD_0']);joints=read(attrs['JOINTS_0']).copy();weights=read(attrs['WEIGHTS_0']).copy();tri=read(p['indices']).reshape(-1,3);parent={int(i):int(i) for i in np.unique(tri)}
def find(a):
 while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
 return a
for t in tri:
 for a in t[1:]:parent[find(int(a))]=find(int(t[0]))
comps={}
for i in parent:comps.setdefault(find(i),[]).append(i)
comps=sorted(comps.values(),key=len,reverse=True);keep=set(comps[0]);tri=np.array([t for t in tri if int(t[0]) in keep]);torso=np.array(comps[0]);
# A gently fitted, hip-length T-shirt with a clean level hem.
pos[torso,1]=np.maximum(pos[torso,1],.88);y=pos[torso,1].copy();pos[torso,1]=.978+(y-.88)*(1.3526-.978)/(1.3526-.88)
width=np.interp(pos[torso,1],[.978,1.07,1.20,1.3526],[.69,.61,.72,1.0]);pos[torso,0]*=width;pos[torso,2]*=np.interp(pos[torso,1],[.978,1.08,1.3526],[.96,.85,.94])
# Reduce the oversized hoodie armholes without changing the shoulder anchors.
underarm=np.clip((abs(pos[torso,0])-.12)/.07,0,1)*np.exp(-((pos[torso,1]-1.22)/.065)**2);pos[torso,1]+=.032*underarm
body=prims[0];bp=read(body['attributes']['POSITION']);bn=read(body['attributes']['NORMAL']);bj=read(body['attributes']['JOINTS_0']);bw=read(body['attributes']['WEIGHTS_0']);bi=np.unique(read(body['indices']));
def boundaries(vertices,faces):
 keys={};weld={};rev={}
 for i in np.unique(faces):
  key=tuple(np.round(vertices[i],5));k=keys.setdefault(key,len(keys));weld[i]=k;rev.setdefault(k,int(i))
 edges={}
 for f in faces:
  for a,b in zip(f,np.roll(f,-1)):
   key=tuple(sorted([weld[a],weld[b]]));edges[key]=edges.get(key,0)+1
 adj={}
 for (a,b),num in edges.items():
  if num==1:adj.setdefault(a,[]).append(b);adj.setdefault(b,[]).append(a)
 loops=[];seen=set()
 for start in adj:
  if start in seen:continue
  loop=[];prev=None;v=start
  while v not in seen:
   seen.add(v);loop.append(rev[v]);choices=[q for q in adj[v] if q!=prev];nxt=next((q for q in choices if q not in seen),start);prev,v=v,nxt
  loops.append(np.array(loop))
 return loops
clothloops=boundaries(pos,tri);skinloops=boundaries(bp,read(body['indices']).reshape(-1,3))
# Shape a smaller round crew neck, carrying nearby fabric along smoothly.
neckloop=next(ids for ids in clothloops if pos[ids,1].mean()>1.29 and abs(pos[ids,0].mean())<.02 and np.max(abs(pos[ids,0]))<.11)
oldneck=pos[neckloop].copy();newneck=oldneck.copy();newneck[:,0]*=.63;newneck[:,2]=-.020+(oldneck[:,2]+.020)*.65
front=np.clip((oldneck[:,2]+.09)/.16,0,1);newneck[:,2]+=.021*front;newneck[:,1]=1.365-.042*front
for vi in torso:
 dist=np.linalg.norm(oldneck-pos[vi],axis=1);k=np.argmin(dist);influence=np.exp(-(dist[k]/.037)**2);pos[vi]+=(newneck[k]-oldneck[k])*influence
# Fit each horizontal cloth ray to the actual body surface, with a small fabric clearance.
surfacefaces=read(body['indices']).reshape(-1,3)
for garment in prims:
 if garment['material'] in (10,11):surfacefaces=np.concatenate([surfacefaces,read(garment['indices']).reshape(-1,3)])
surface=bp[surfacefaces];centers=surface.mean(1);surface=surface[(abs(centers[:,0])<.22)&(centers[:,1]>.9)&(centers[:,1]<1.35)]
v0=surface[:,0];e1=surface[:,1]-v0;e2=surface[:,2]-v0
for vi in torso:
 point=pos[vi].copy();blend=float(np.clip((1.29-point[1])/.065,0,1))
 if blend<=0:continue
 origin=np.array([0.,point[1],.015]);direction=point-origin;direction[1]=0;radius=np.linalg.norm(direction)
 if radius<1e-6:continue
 direction/=radius;h=np.cross(np.broadcast_to(direction,e2.shape),e2);det=np.sum(e1*h,axis=1);valid=abs(det)>1e-9;inv=np.zeros_like(det);inv[valid]=1/det[valid];delta=origin-v0;u=inv*np.sum(delta*h,axis=1);q=np.cross(delta,e1);v=inv*(q@direction);distance=inv*np.sum(e2*q,axis=1);hits=distance[valid&(u>=-1e-5)&(v>=-1e-5)&(u+v<=1.00001)&(distance>0)]
 # A regular tee hangs past the waist instead of tracing the body's hourglass.
 rx=float(np.interp(point[1],[.978,1.09,1.22],[.145,.142,.146]));rz=float(np.interp(point[1],[.978,1.09,1.22],[.123,.126,.131]));smoothradius=1/np.sqrt((direction[0]/rx)**2+(direction[2]/rz)**2)
 clearance=hits.max()+.013 if len(hits) else 0
 fitted=origin+direction*max(clearance,smoothradius);pos[vi]=point*(1-blend)+fitted*blend
clothloops=boundaries(pos,tri)
import copy
skinmat=copy.deepcopy(j['materials'][7]);skinmat['name']='Marina restored arm skin';skinmat['pbrMetallicRoughness'].pop('baseColorTexture',None);skinmat['pbrMetallicRoughness']['baseColorFactor']=[.90,.80,.74,1];skinmat.pop('normalTexture',None);skinmat['alphaMode']='OPAQUE';skinmat['doubleSided']=True
mt=skinmat['extensions']['VRMC_materials_mtoon'];mt.pop('shadeMultiplyTexture',None);mt['matcapFactor']=[0,0,0];mt['shadingShiftFactor']=.1;mt['shadeColorFactor']=[.75,.65,.60];mt['outlineWidthFactor']=0;j['materials'].append(skinmat);skinmaterial=len(j['materials'])-1

def emit_surface(points,bones,ws,segments,material):
 points=np.array(points);faces=[]
 for ri in range(len(points)//segments-1):
  for k in range(segments):
   a=ri*segments+k;b=ri*segments+(k+1)%segments;c=b+segments;dd=a+segments;faces.extend([(a,b,c),(a,c,dd)])
 normals=np.zeros_like(points)
 for fi,f in enumerate(faces):
  a,b,c=points[list(f)];n=np.cross(b-a,c-a)
  # Outward radial normal independent of the boundary loop traversal.
  if np.dot(n,(a+b+c)/3-np.array([(a[0]+b[0]+c[0])/3,1.315,-.025]))<0:
   n=-n;faces[fi]=(f[0],f[2],f[1])
  for vi in f:normals[vi]+=n
 normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-9)
 prims.append({'attributes':{'POSITION':access(points,'VEC3'),'NORMAL':access(normals,'VEC3'),'TEXCOORD_0':access(np.full((len(points),2),.01),'VEC2'),'JOINTS_0':access(bones,'VEC4',5123),'WEIGHTS_0':access(ws,'VEC4')},'indices':access(np.array(faces).reshape(-1,1),'SCALAR',5125,34963),'material':material,'mode':4})
for sign,upper,lower in [(1,70,71),(-1,93,94)]:
 rootloop=next(ids for ids in clothloops if len(ids)>10 and pos[ids,0].mean()*sign>.12 and pos[ids,1].mean()>1.2)
 # Root ring duplicates the exact torso boundary and its skin weights.
 rootpoints=pos[rootloop];center=rootpoints.mean(0);angles=np.arctan2(rootpoints[:,2]-center[2],rootpoints[:,1]-center[1]);segments=len(rootloop)
 cuff=np.stack([np.full(segments,sign*.273),1.312+.041*np.cos(angles),-.027+.040*np.sin(angles)],axis=1)
 points=[];bones=[];ws=[]
 for ri in range(13):
  t=ri/12; eased=t*t*(3-2*t)
  for k,vi in enumerate(rootloop):
   points.append(rootpoints[k]*(1-t)+cuff[k]*t)
   original={int(b):float(w) for b,w in zip(joints[vi],weights[vi]) if w>0};new={b:w*(1-eased) for b,w in original.items()};new[upper]=new.get(upper,0)+eased;items=sorted(new.items(),key=lambda a:-a[1])[:4];items+= [(0,0)]*(4-len(items));bones.append([b for b,w in items]);weight=np.array([w for b,w in items]);ws.append(weight/weight.sum())
 emit_surface(points,bones,ws,segments,8)
 # End the new arm exactly on the original forearm's open edge.
 endloop=next(ids for ids in skinloops if bp[ids,0].mean()*sign>.40 and bp[ids,0].mean()*sign<.46 and bp[ids,1].mean()>1.2)
 ep=bp[endloop];ec=ep.mean(0);ea=np.arctan2(ep[:,2]-ec[2],ep[:,1]-ec[1]);segments=len(endloop);start=np.stack([np.full(segments,sign*.245),1.314+.038*np.cos(ea),-.027+.038*np.sin(ea)],axis=1)
 points=[];bones=[];ws=[]
 for ri in range(18):
  t=ri/17
  for k,vi in enumerate(endloop):
   points.append(start[k]*(1-t)+ep[k]*t);original={int(b):float(w) for b,w in zip(bj[vi],bw[vi]) if w>0};new={b:w*t for b,w in original.items()};new[upper]=new.get(upper,0)+1-t;items=sorted(new.items(),key=lambda a:-a[1])[:4];items +=[(0,0)]*(4-len(items));bones.append([b for b,w in items]);ww=np.array([w for b,w in items]);ws.append(ww/ww.sum())
 emit_surface(points,bones,ws,segments,skinmaterial)

norm=np.zeros_like(pos)
for f in tri:
 a,b,c=pos[f];normal=np.cross(b-a,c-a)
 for v in f:norm[v]+=normal
norm/=np.maximum(np.linalg.norm(norm,axis=1,keepdims=True),1e-10)
p['attributes']={'POSITION':access(pos,'VEC3'),'NORMAL':access(norm,'VEC3'),'TEXCOORD_0':attrs['TEXCOORD_0'],'JOINTS_0':access(joints,'VEC4',5123),'WEIGHTS_0':access(weights,'VEC4')};p['indices']=access(tri.reshape(-1,1),'SCALAR',5125,34963)
# Remove the hoodie hardware; preserve the separate necklace and pendant.
prims[:]=[p for p in prims if p['material']!=12 and not (p['material']==15 and p['attributes']['POSITION']==158)]
# Remove the outline pass from the forearms and hands, retaining the body material elsewhere.
forearmmat=copy.deepcopy(j['materials'][7]);forearmmat['name']='Marina forearms without outline';forearmmat['extensions']['VRMC_materials_mtoon']['outlineWidthFactor']=0;forearmmat['extensions']['VRMC_materials_mtoon']['outlineWidthMode']='none';j['materials'].append(forearmmat)
bodyfaces=read(body['indices']).reshape(-1,3);centers=bp[bodyfaces].mean(1);isarm=(abs(centers[:,0])>.40)&(centers[:,1]>1.19)
body['indices']=access(bodyfaces[~isarm].reshape(-1,1),'SCALAR',5125,34963)
prims.append({'attributes':body['attributes'].copy(),'indices':access(bodyfaces[isarm].reshape(-1,1),'SCALAR',5125,34963),'material':len(j['materials'])-1,'mode':4})
j['buffers'][0]['byteLength']=len(data);data.extend(b'\0'*((-len(data))%4));js=json.dumps(j,separators=(',',':')).encode();js+=b' '*((-len(js))%4);out=root.parent/'marina white Hack Club tshirt regular fit.vrm';out.write_bytes(struct.pack('<III',0x46546c67,2,28+len(js)+len(data))+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(data),0x004e4942)+data);print(out)
