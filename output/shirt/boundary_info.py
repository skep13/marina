exec(open('output/shirt/mesh_info.py').read().split('for mesh')[0])
p=j['meshes'][1]['primitives'][1];pos=read(p['attributes']['POSITION']);uv=read(p['attributes']['TEXCOORD_0']);tri=read(p['indices']).reshape(-1,3);tri=tri[(uv[tri].mean(1)[:,1]>.465)&(abs(pos[tri].mean(1)[:,0])<.24)]
# Weld positions only for boundary detection.
keys={};weld={};rev={}
for i in np.unique(tri):
 key=tuple(np.round(pos[i],5));k=keys.setdefault(key,len(keys));weld[i]=k;rev.setdefault(k,[]).append(i)
edges={}
for t in tri:
 for a,b in zip(t,np.roll(t,-1)):
  a,b=weld[a],weld[b];key=tuple(sorted([a,b]));edges[key]=edges.get(key,0)+1
adj={}
for (a,b),n in edges.items():
 if n==1:adj.setdefault(a,[]).append(b);adj.setdefault(b,[]).append(a)
seen=set()
for k in adj:
 if k in seen:continue
 todo=[k];comp=[]
 while todo:
  v=todo.pop()
  if v in seen:continue
  seen.add(v);comp.append(rev[v][0]);todo+=adj.get(v,[])
 q=pos[comp];print('loop',len(comp),'bounds',q.min(0),q.max(0),'avg',q.mean(0));print([(int(i),pos[i].round(4).tolist()) for i in comp] if len(comp)<70 else '')
