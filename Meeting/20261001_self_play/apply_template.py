"""Apply the exact EAGLE master and layouts to the authored report."""
import copy
import re
import sys
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as E

P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PR='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
NS={'p':P,'a':A,'r':R}
for prefix,uri in NS.items(): E.register_namespace(prefix,uri)
def xml(data): return E.fromstring(data)
def dump(node):
 if node.tag.startswith('{'+CT+'}'): E.register_namespace('',CT)
 elif node.tag.startswith('{'+PR+'}'): E.register_namespace('',PR)
 return E.tostring(node,encoding='utf-8',xml_declaration=True)
def texts(node): return ''.join(t.text or '' for t in node.iter('{'+A+'}t'))
def read(path):
 with zipfile.ZipFile(path) as z: return {n:z.read(n) for n in z.namelist()}
def resize(node):
 for e in node.iter():
  tag=e.tag.split('}')[-1]
  if tag in ('off','ext','chOff','chExt'):
   for attr in ('x','y','cx','cy'):
    if attr not in e.attrib: continue
    v=int(e.get(attr)); sx=1372/1160; sy=555/480
    if attr=='x': v=round((150+(v/9525-60)*sx)*9525)
    elif attr=='y': v=round((250+(v/9525-170)*sy)*9525)
    else: v=round(v*(sx if attr=='cx' else sy))
    e.set(attr,str(v))
  if tag in ('gridCol',): e.set('w',str(round(int(e.get('w'))*1372/1160)))
  if tag=='tr': e.set('h',str(round(int(e.get('h'))*555/480)))
  if tag in ('rPr','defRPr','endParaRPr') and 'sz' in e.attrib:
   e.set('sz',str(round(int(e.get('sz'))*1.15)))
def placeholder(layout,idx):
 return next(s for s in layout.findall('.//p:sp',NS) if (ph:=s.find('p:nvSpPr/p:nvPr/p:ph',NS)) is not None and ph.get('idx','0')==str(idx))
def filled(source,content,shape_id,size=None):
 shape=copy.deepcopy(source)
 shape.find('p:nvSpPr/p:cNvPr',NS).set('id',str(shape_id))
 for e in shape.iter():
  if e.tag.endswith('}creationId'): e.set('id','{'+str(uuid.uuid4()).upper()+'}')
 body=shape.find('p:txBody',NS)
 sample=body.find('a:p',NS)
 props=copy.deepcopy(sample.find('a:pPr',NS))
 runprops=copy.deepcopy(sample.find('a:r/a:rPr',NS))
 if props is None: props=E.Element('{'+A+'}pPr')
 for c in list(body):
  if c.tag=='{'+A+'}p': body.remove(c)
 para=E.SubElement(body,'{'+A+'}p');para.append(props)
 E.SubElement(props,'{'+A+'}buNone')
 run=E.SubElement(para,'{'+A+'}r')
 if runprops is not None: run.append(runprops)
 E.SubElement(run,'{'+A+'}t').text=content
 if size:
  for e in shape.iter():
   if e.tag in ('{'+A+'}rPr','{'+A+'}defRPr'): e.set('sz',str(round(size*75)))
 return shape

def main(authored,template,output):
 src=read(authored); tpl=read(template); out=dict(tpl)
 prefixes=('ppt/slides/','ppt/notesSlides/','ppt/charts/','ppt/embeddings/')
 for n in list(out):
  if n.startswith(prefixes): del out[n]
 copied={n:v for n,v in src.items() if n.startswith(prefixes)}
 out.update(copied)
 # This report contains native charts/tables only; template artwork stays untouched.
 assert not any(n.startswith('ppt/media/') for n in src),'Unexpected authored media'
 pres=xml(tpl['ppt/presentation.xml']); ids=pres.find('p:sldIdLst',NS);ids.clear()
 rels=xml(tpl['ppt/_rels/presentation.xml.rels'])
 for r in list(rels):
  if r.get('Type','').endswith('/slide'): rels.remove(r)
 source_rels=xml(src['ppt/_rels/presentation.xml.rels'])
 source_pres=xml(src['ppt/presentation.xml'])
 source_map={r.get('Id'):r for r in source_rels}
 layouts=[9,9,10,3,10,10,9,10,10,3,10,10,3,10,10,9,10,10]
 for i,oldid in enumerate(source_pres.find('p:sldIdLst',NS),1):
  rid='rIdReportSlide'+str(i);r=copy.deepcopy(source_map[oldid.get('{'+R+'}id')]);r.set('Id',rid);rels.append(r)
  E.SubElement(ids,'{'+P+'}sldId',{'id':str(255+i),'{'+R+'}id':rid})
  part='ppt/slides/slide'+str(i)+'.xml';s=xml(out[part]);cs=s.find('p:cSld',NS)
  bg=cs.find('p:bg',NS)
  if bg is not None: cs.remove(bg)
  s.set('showMasterSp','1'); tree=cs.find('p:spTree',NS); shapes=tree.findall('p:sp',NS)
  title,subtitle=texts(shapes[0]),texts(shapes[1])
  for shape in shapes[:4]: tree.remove(shape)
  for item in list(tree)[2:]: resize(item)
  for table in tree.findall('.//a:tbl',NS):
   props=table.find('a:tblPr',NS)
   if props is None: props=E.Element('{'+A+'}tblPr');table.insert(0,props)
   props.set('firstRow','1');props.set('bandRow','0')
   for oldstyle in props.findall('a:tableStyleId',NS):props.remove(oldstyle)
   E.SubElement(props,'{'+A+'}tableStyleId').text=xml(tpl['ppt/tableStyles.xml']).get('def')
  layout_id=layouts[min(i-1,len(layouts)-1)]
  layout=xml(tpl[f'ppt/slideLayouts/slideLayout{layout_id}.xml'])
  maxid=max(int(e.get('id')) for e in tree.iter('{'+P+'}cNvPr'))+1
  # Keep the template title geometry, fitting long research headings locally.
  units=sum(1 if ord(c)>255 else .55 for c in title)
  size=min(62,max(40,1120/max(units,1)))
  tree.insert(2,filled(placeholder(layout,0),title,maxid,size))
  tree.insert(3,filled(placeholder(layout,1),subtitle,maxid+1,25))
  num=copy.deepcopy(placeholder(layout,90));num.find('p:nvSpPr/p:cNvPr',NS).set('id',str(maxid+2))
  for field in num.iter('{'+A+'}fld'):
   field.set('id','{'+str(uuid.uuid4()).upper()+'}');field.find('a:t',NS).text=str(i)
  tree.append(num);out[part]=dump(s)
  rp=f'ppt/slides/_rels/slide{i}.xml.rels';rs=xml(out[rp])
  for r in rs:
   if r.get('Type','').endswith('/slideLayout'): r.set('Target',f'../slideLayouts/slideLayout{layout_id}.xml')
  out[rp]=dump(rs)
 for n in copied:
  if '/charts/' in n and n.endswith('.xml'):
   c=xml(out[n])
   for e in c.iter():
    if e.tag in ('{'+A+'}rPr','{'+A+'}defRPr','{'+A+'}endParaRPr') and 'sz' in e.attrib:e.set('sz',str(round(int(e.get('sz'))*1.15)))
   out[n]=dump(c)
 out['ppt/presentation.xml']=dump(pres);out['ppt/_rels/presentation.xml.rels']=dump(rels)
 ct=xml(tpl['[Content_Types].xml'])
 for e in list(ct):
  if e.get('PartName','').lstrip('/').startswith(prefixes):ct.remove(e)
 for e in xml(src['[Content_Types].xml']):
  if e.get('PartName','').lstrip('/') in copied or (e.tag.endswith('Default') and not any(x.get('Extension')==e.get('Extension') for x in ct)):
   ct.append(copy.deepcopy(e))
 for e in ct:
  if e.get('PartName')=='/ppt/presentation.xml':e.set('ContentType','application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml')
 out['[Content_Types].xml']=dump(ct)
 for n in tpl:
  if n.startswith(('ppt/slideMasters/','ppt/slideLayouts/','ppt/theme/','ppt/media/')):assert out[n]==tpl[n],n
 assert len(ids)==len(source_pres.find("p:sldIdLst",NS))
 assert len([n for n in out if re.fullmatch(r'ppt/slideLayouts/slideLayout\d+\.xml',n)])==12
 for n in copied:
  if n.startswith('ppt/notesSlides/'):assert out[n]==src[n],n
 with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
  for n,b in out.items():z.writestr(n,b)
 print(f'Applied exact EAGLE template: {len(ids)} slides, 12 preserved layouts, native slide numbering')
if __name__=='__main__':main(*map(Path,sys.argv[1:]))
