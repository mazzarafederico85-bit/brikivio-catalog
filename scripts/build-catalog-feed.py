"""Build only public catalog data for the updater, never application/user files.
CSV downloads: Rebrickable's bulk dataset; no API key or customer data.
"""
import csv, gzip, io, json, hashlib, urllib.request, tempfile, argparse
from pathlib import Path
from datetime import datetime, timezone

def rows(name, cache):
    cache.mkdir(parents=True,exist_ok=True)
    path=cache/(name+'.csv.gz')
    if not path.exists():
        with urllib.request.urlopen('https://cdn.rebrickable.com/media/downloads/'+name+'.csv.gz', timeout=120) as r, path.open('wb') as out:
            while chunk:=r.read(1024*1024):out.write(chunk)
    with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)

def build(source, output, cache):
    old=json.loads((source/'catalog.json').read_text()) if (source/'catalog.json').exists() else {'sets':[]}
    oldparts=json.loads((source/'parts-catalog.json').read_text()) if (source/'parts-catalog.json').exists() else {'parts':[],'colors':[]}
    oldsets={s['id']:s for s in old['sets']}; oldp={p['id']:p for p in oldparts['parts']}
    themes={r['id']:r for r in rows('themes',cache)}; categories={r['id']:r['name'] for r in rows('part_categories',cache)}
    colors=[{'id':int(r['id']),'name':r['name'],'rgb':r['rgb']} for r in rows('colors',cache) if int(r['id'])>=-1]
    colors={c['id']:c for c in colors};colors.update({c['id']:c for c in oldparts['colors']})
    sets={}
    for r in rows('sets',cache):
        tid=r['theme_id'];seen=set()
        while tid in themes and themes[tid]['parent_id'] and tid not in seen:seen.add(tid);tid=themes[tid]['parent_id']
        sid=r['set_num'];prior=oldsets.get(sid,{})
        sets[sid]={'id':sid,'code':sid.rsplit('-',1)[0],'name':r['name'],'year':int(r['year']),'theme':prior.get('theme',themes.get(tid,{}).get('name','Altri set')),'subtheme':prior.get('subtheme',''),'parts':int(r['num_parts']),'image':r.get('img_url',r.get('set_img_url','')),'type':prior.get('type','set')}
    if len(sets)<len(oldsets)*.9:raise ValueError('Incomplete upstream set catalog')
    parts={r['part_num']:{'id':r['part_num'],'name':r['name'],'category':oldp.get(r['part_num'],{}).get('category',categories.get(r['part_cat_id'],'Altro')),'firstYear':oldp.get(r['part_num'],{}).get('firstYear'),'material':r.get('part_material','Plastic'),'image':r.get('part_img_url',''),'colors':set(oldp.get(r['part_num'],{}).get('colors',[]))} for r in rows('parts',cache)}
    chosen={}
    for r in rows('inventories',cache):
        sid=r['set_num'];v=(int(r['version']),int(r['id']))
        if sid in sets and v>chosen.get(sid,(0,0)):chosen[sid]=v
    ids={i:(s,v) for s,(v,i) in chosen.items()}; recipes={}
    for r in rows('inventory_parts',cache):
        match=ids.get(int(r['inventory_id']))
        if not match:continue
        sid,version=match;recipe=recipes.setdefault(sid,{'parts':[],'spares':[],'omitted':0,'version':version})
        pid=r['part_num'];cid=int(r['color_id']);qty=int(r['quantity'])
        if pid not in parts or cid not in colors:recipe['omitted']+=qty;continue
        parts[pid]['colors'].add(cid)
        if not parts[pid]['image']:parts[pid]['image']=r.get('img_url','')
        recipe['spares' if r['is_spare'].lower() in ('t','true','1') else 'parts'].append([pid,cid,qty])
    for p in parts.values():p['colors']=sorted(p['colors'])
    revision=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload={'schema':1,'revision':revision,'updated':revision[:10],'sets':list(sets.values()),'parts':list(parts.values()),'colors':list(colors.values()),'recipes':recipes}
    data=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode();digest=hashlib.sha256(data).hexdigest()
    if len(data)>80_000_000:raise ValueError('Catalog exceeds supported size')
    output.mkdir(parents=True,exist_ok=True);name='catalog-'+digest+'.json';(output/name).write_bytes(data)
    (output/'manifest.json').write_text(json.dumps({'schema':1,'revision':revision,'file':name,'sha256':digest,'bytes':len(data),'source':'https://rebrickable.com/downloads/'}))
    (output/'index.html').write_text('<!doctype html><html lang="it"><meta charset="utf-8"><title>Catalogo Brikivio</title><h1>Catalogo Brikivio</h1><p>Dati di catalogo da <a href="https://rebrickable.com/downloads/">Rebrickable</a>. Progetto indipendente, non affiliato al Gruppo LEGO.</p>')
    print(json.dumps({'sets':len(sets),'parts':len(parts),'recipes':len(recipes),'bytes':len(data),'revision':revision}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default='public');p.add_argument('--output',default='catalog-site/catalog');p.add_argument('--cache');a=p.parse_args()
    with tempfile.TemporaryDirectory() as temp:build(Path(a.source),Path(a.output),Path(a.cache or temp))
