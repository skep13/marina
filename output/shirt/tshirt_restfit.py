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
# Shape both armholes into matching shoulder caps, smoothing the adjoining torso.
for sign in (1,-1):
 ids=next(ids for ids in clothloops if len(ids)>10 and pos[ids,0].mean()*sign>.12 and pos[ids,1].mean()>1.2)
 old=pos[ids].copy();raw=read(attrs['POSITION'])[ids];center=raw.mean(0);angle=np.arctan2(raw[:,2]-center[2],raw[:,1]-center[1]);new=np.stack([sign*(.122-.018*np.cos(angle)),1.305+.047*np.cos(angle),-.026+.054*np.sin(angle)],axis=1)
 for vi in torso:
  if pos[vi,0]*sign<0:continue
  distances=np.linalg.norm(old-pos[vi],axis=1);k=np.argmin(distances);influence=np.exp(-(distances[k]/.042)**2);pos[vi]+=(new[k]-old[k])*influence
  if influence>.001:
   upper=70 if sign==1 else 93;shoulder=69 if sign==1 else 92;height=float(np.clip((pos[vi,1]-1.260)/.080,0,1));armweight=.10+.35*height;shoulderweight=.06+.44*height;chestweight=1-armweight-shoulderweight;mix={int(b):float(w)*(1-influence) for b,w in zip(joints[vi],weights[vi]) if w>0};mix[upper]=mix.get(upper,0)+influence*armweight;mix[shoulder]=mix.get(shoulder,0)+influence*shoulderweight;mix[4]=mix.get(4,0)+influence*chestweight;items=sorted(mix.items(),key=lambda a:-a[1])[:4];items +=[(0,0)]*(4-len(items));joints[vi]=[b for b,w in items];ww=np.array([w for b,w in items]);weights[vi]=ww/ww.sum()
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
 cuff=np.stack([sign*(.230+.008*np.cos(angles)),1.302+.043*np.cos(angles),-.026+.043*np.sin(angles)],axis=1)
 points=[];bones=[];ws=[]
 for ri in range(13):
  t=ri/12; eased=t*t*(3-2*t)
  for k,vi in enumerate(rootloop):
   point=rootpoints[k]*(1-t)+cuff[k]*t;point[1]+=.004*np.sin(np.pi*t)*np.cos(angles[k]);point[2]+=.004*np.sin(np.pi*t)*np.sin(angles[k]);points.append(point)
   original={int(b):float(w) for b,w in zip(joints[vi],weights[vi]) if w>0};new={b:w*(1-eased) for b,w in original.items()};new[upper]=new.get(upper,0)+eased;items=sorted(new.items(),key=lambda a:-a[1])[:4];items+= [(0,0)]*(4-len(items));bones.append([b for b,w in items]);weight=np.array([w for b,w in items]);ws.append(weight/weight.sum())
 emit_surface(points,bones,ws,segments,8)
 # End the new arm exactly on the original forearm's open edge.
 endloop=next(ids for ids in skinloops if bp[ids,0].mean()*sign>.40 and bp[ids,0].mean()*sign<.46 and bp[ids,1].mean()>1.2)
 ep=bp[endloop];ec=ep.mean(0);ea=np.arctan2(ep[:,2]-ec[2],ep[:,1]-ec[1]);segments=len(endloop);start=np.stack([np.full(segments,sign*.211),1.304748+.039*np.cos(ea),-.02578+.039*np.sin(ea)],axis=1)
 points=[];bones=[];ws=[]
 for ri in range(18):
  t=ri/17
  for k,vi in enumerate(endloop):
   point=start[k]*(1-t)+ep[k]*t;points.append(point);elbowblend=float(np.clip((abs(point[0])-.307)/.043,0,1));original={int(b):float(w) for b,w in zip(bj[vi],bw[vi]) if w>0};new={b:w*elbowblend for b,w in original.items()};new[upper]=new.get(upper,0)+1-elbowblend;items=sorted(new.items(),key=lambda a:-a[1])[:4];items +=[(0,0)]*(4-len(items));bones.append([b for b,w in items]);ww=np.array([w for b,w in items]);ws.append(ww/ww.sum())
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
# Close the folded underarm area with a small skinned fabric gusset on each side.
for sign,upper in [(1,70),(-1,93)]:
 points=[];normals=[];bones=[];ww=[];faces=[]
 for zsign in (1,-1):
  z=.095 if zsign==1 else -.094
  for x,y,aw in [(.075,1.308,.10),(.172,1.307,.35),(.210,1.233,.45),(.145,1.195,.04)]:
   points.append([sign*x,y,z]);normals.append([0,0,zsign]);bones.append([upper,4,0,0]);ww.append([aw,1-aw,0,0])
  k=len(points)-4;faces.extend([(k,k+1,k+2),(k,k+2,k+3)])
 prims.append({'attributes':{'POSITION':access(points,'VEC3'),'NORMAL':access(normals,'VEC3'),'TEXCOORD_0':access(np.full((8,2),.01),'VEC2'),'JOINTS_0':access(bones,'VEC4',5123),'WEIGHTS_0':access(ww,'VEC4')},'indices':access(np.array(faces).reshape(-1,1),'SCALAR',5125,34963),'material':8,'mode':4})
# Consolidate the torso and both sleeves so their shared edges shade continuously.
def current(i):
 a=j['accessors'][i];v=j['bufferViews'][a['bufferView']];return np.frombuffer(data,dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[a['componentType']],count=a['count']*{'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']],offset=v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(a['count'],-1).copy()
cloth=[q for q in prims if q['material']==8];positions=[];texcoords=[];bones=[];skinweights=[];faces=[];count=0
for q in cloth:
 aa=q['attributes'];qq=current(aa['POSITION']);positions.extend(qq);texcoords.extend(current(aa['TEXCOORD_0']));bones.extend(current(aa['JOINTS_0']));skinweights.extend(current(aa['WEIGHTS_0']));faces.extend(current(q['indices']).reshape(-1,3)+count);count+=len(qq)
positions=np.array(positions);texcoords=np.array(texcoords);bones=np.array(bones);skinweights=np.array(skinweights);faces=np.array(faces)
# Remove degenerate faces from the levelled hem; average normals across UV and sleeve seams.
area=np.cross(positions[faces[:,1]]-positions[faces[:,0]],positions[faces[:,2]]-positions[faces[:,0]]);valid=np.linalg.norm(area,axis=1)>1e-10;faces=faces[valid];area=area[valid];groups={};keys=[tuple(np.round(v,5)) for v in positions];normalsum={}
for f,normal in zip(faces,area):
 for vi in f:
  key=keys[vi];normalsum[key]=normalsum.get(key,np.zeros(3))+normal
normals=np.array([normalsum.get(key,np.array([0,0,1])) for key in keys]);normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-9)
prims[:]=[q for q in prims if q['material']!=8];prims.append({'attributes':{'POSITION':access(positions,'VEC3'),'NORMAL':access(normals,'VEC3'),'TEXCOORD_0':access(texcoords,'VEC2'),'JOINTS_0':access(bones,'VEC4',5123),'WEIGHTS_0':access(skinweights,'VEC4')},'indices':access(faces.reshape(-1,1),'SCALAR',5125,34963),'material':8,'mode':4})
# Cotton should have a smooth silhouette, without outlining the old hoodie folds and pockets.
clothmat=j['materials'][8]['extensions']['VRMC_materials_mtoon'];clothmat['outlineWidthMode']='none';clothmat['outlineWidthFactor']=0;clothmat['shadeColorFactor']=[.89,.89,.91];clothmat['shadingToonyFactor']=.65
# Mask skin completely covered by the shirt to prevent underlying body outlines bleeding through.
coveredfaces=current(body['indices']).reshape(-1,3);cc=bp[coveredfaces].mean(1);covered=(cc[:,1]>.973)&(cc[:,1]<1.306)&(abs(cc[:,0])<.20);body['indices']=access(coveredfaces[~covered].reshape(-1,1),'SCALAR',5125,34963)
j['buffers'][0]['byteLength']=len(data);data.extend(b'\0'*((-len(data))%4));js=json.dumps(j,separators=(',',':')).encode();js+=b' '*((-len(js))%4);out=root.parent/'marina white Hack Club tshirt rest fit.vrm';out.write_bytes(struct.pack('<III',0x46546c67,2,28+len(js)+len(data))+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(data),0x004e4942)+data);print(out)
