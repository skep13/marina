exec(open('output/shirt/mesh_info.py').read().split('for mesh')[0].replace('marina necklace refined.vrm','marina white Hack Club shirt.vrm'))
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
# Straight T-shirt hem, lighter fitted torso, round neckline.
pos[torso,1]=np.maximum(pos[torso,1],.90);y=pos[torso,1];pos[torso,1]=.925+(y-.792)*(1.3526-.925)/(1.3526-.792)
pos[torso,0]*=.93;pos[torso,2]*=.91
# Lift the lowest centre of the old V-neck into a shallow crew neck.
neck=torso[(uv[torso,1]<.555)&(abs(pos[torso,0])<.074)&(pos[torso,1]>1.305)]
for vi in neck:
 blend=np.clip((1.36-pos[vi,1])/.06,0,1);pos[vi,1]+=blend*.039*(1-(abs(pos[vi,0])/.08)**2)
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
 cuff=np.stack([np.full(segments,sign*.295),1.312+.052*np.cos(angles),-.027+.049*np.sin(angles)],axis=1)
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
j['buffers'][0]['byteLength']=len(data);data.extend(b'\0'*((-len(data))%4));js=json.dumps(j,separators=(',',':')).encode();js+=b' '*((-len(js))%4);out=root.parent/'marina white Hack Club tshirt repaired.vrm';out.write_bytes(struct.pack('<III',0x46546c67,2,28+len(js)+len(data))+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(data),0x004e4942)+data);print(out)
