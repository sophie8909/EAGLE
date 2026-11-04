from pathlib import Path
from lxml import etree as E
import zipfile,posixpath,copy,uuid,json,hashlib,re
root=Path(__file__).resolve().parents[1]
base=root.parent/'20261104_genotype/deliverables/EAGLE_1105_with_genotype.pptx'
addition=root/'build/validated/genotype.pptx';out=root/'deliverables/EAGLE_1105_with_strategy_initialization.pptx'
P='http://schemas.openxmlformats.org/presentationml/2006/main';A='http://schemas.openxmlformats.org/drawingml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';PR='http://schemas.openxmlformats.org/package/2006/relationships';CT='http://schemas.openxmlformats.org/package/2006/content-types';P14='http://schemas.microsoft.com/office/powerpoint/2010/main'
ns={'p':P,'a':A,'r':R,'p14':P14}
xml=E.fromstring
serialize=lambda x:E.tostring(x,xml_declaration=True,encoding='UTF-8',standalone=True)
with zipfile.ZipFile(base) as b,zipfile.ZipFile(addition) as z:
 data={n:b.read(n) for n in b.namelist()};pres=xml(data['ppt/presentation.xml']);rels=xml(data['ppt/_rels/presentation.xml.rels']);ct=xml(data['[Content_Types].xml']);lst=pres.find('p:sldIdLst',ns);original=list(lst);assert len(original)==74
 targets={e.get('Id'):posixpath.normpath(posixpath.join('ppt',e.get('Target'))) for e in rels}
 sourcepaths=[targets[s.get('{'+R+'}id')] for s in original]
 sample=xml(data[sourcepaths[64]]);numbers=[s for s in sample.findall('.//p:sp',ns) if s.find('.//a:fld[@type="slidenum"]',ns) is not None];assert len(numbers)==1
 sourceCT=xml(z.read('[Content_Types].xml'));types={e.get('PartName').lstrip('/'):e.get('ContentType') for e in sourceCT if e.tag.endswith('Override')};defaults={e.get('Extension') for e in ct if e.tag.endswith('Default')}
 for e in sourceCT:
  if e.tag.endswith('Default') and e.get('Extension') not in defaults:ct.append(copy.deepcopy(e));defaults.add(e.get('Extension'))
 copied={};mapping={}
 def copy_part(name):
  name=name.lstrip('/')
  if name in mapping:return mapping[name]
  if '/slideLayouts/' in name:return 'ppt/slideLayouts/slideLayout12.xml'
  if '/notesMasters/' in name:return 'ppt/notesMasters/notesMaster1.xml'
  target=posixpath.join(posixpath.dirname(name),'strategy_'+posixpath.basename(name));mapping[name]=target;assert target not in data
  payload=z.read(name);rp=posixpath.join(posixpath.dirname(name),'_rels',posixpath.basename(name)+'.rels')
  if rp in z.namelist():
   rr=xml(z.read(rp))
   for rel in rr:
    if rel.get('TargetMode')=='External':continue
    old=posixpath.normpath(posixpath.join(posixpath.dirname(name),rel.get('Target')));new=copy_part(old);rel.set('Target',posixpath.relpath(new,posixpath.dirname(target)))
   copied[posixpath.join(posixpath.dirname(target),'_rels',posixpath.basename(target)+'.rels')]=serialize(rr)
  copied[target]=payload
  if name in types:E.SubElement(ct,'{'+CT+'}Override',PartName='/'+target,ContentType=types[name])
  return target
 az=xml(z.read('ppt/presentation.xml'));ar=xml(z.read('ppt/_rels/presentation.xml.rels'));at={e.get('Id'):posixpath.normpath(posixpath.join('ppt',e.get('Target'))) for e in ar}
 nextid=max(int(e.get('id')) for e in original)+1;nextrid=max(int(e.get('Id')[3:]) for e in rels if e.get('Id').startswith('rId'))+1;newpaths=[];newids=[]
 section=pres.find('.//p14:section[@name="1105"]',ns);assert section is not None
 for i,s in enumerate(az.find('p:sldIdLst',ns)):
  target=copy_part(at[s.get('{'+R+'}id')]);newpaths.append(target);slide=xml(copied[target]);bg=slide.find('p:cSld/p:bg',ns)
  if bg is not None:bg.getparent().remove(bg)
  for attr in ('showMasterSp','showMasterPhAnim'):
   if sample.get(attr) is not None:slide.set(attr,sample.get(attr))
  number=copy.deepcopy(numbers[0]);number.find('.//p:cNvPr',ns).set('id','9999');number.find('.//a:fld',ns).set('id','{'+str(uuid.uuid4()).upper()+'}');slide.find('p:cSld/p:spTree',ns).append(number);copied[target]=serialize(slide)
  rid='rId'+str(nextrid+i);sid=str(nextid+i);newids.append(sid)
  E.SubElement(rels,'{'+PR+'}Relationship',Id=rid,Type=R+'/slide',Target=posixpath.relpath(target,'ppt'))
  lst.insert(65+i,E.Element('{'+P+'}sldId',id=sid,attrib={'{'+R+'}id':rid}))
 assert len(newpaths)==2
 for i,sid in enumerate(newids):section[0].insert(7+i,E.Element('{'+P14+'}sldId',id=sid))
 data.update(copied);allpaths=sourcepaths[:65]+newpaths+sourcepaths[65:]
 for index,path in enumerate(allpaths,1):
  slide=xml(data[path])
  for fld in slide.findall('.//a:fld[@type="slidenum"]',ns):
   fld.find('a:t',ns).text=str(index)
   for t in fld.getparent().findall('a:r/a:t',ns):
    if t.text and re.fullmatch(r'\s*/\s*\d+\s*',t.text):t.text=' / 76'
  data[path]=serialize(slide)
 data['ppt/presentation.xml']=serialize(pres);data['ppt/_rels/presentation.xml.rels']=serialize(rels);data['[Content_Types].xml']=serialize(ct)
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dst:
  for name,payload in data.items():dst.writestr(name,payload)
 # Original slide content remains identical after excluding number text.
 def body(payload):
  s=xml(payload)
  for fld in s.findall('.//a:fld[@type="slidenum"]',ns):
   for t in fld.getparent().findall('.//a:t',ns):t.text='NUMBER'
  return E.tostring(s,method='c14n')
 for path in sourcepaths:assert body(b.read(path))==body(data[path]),path
 untouched=[n for n in b.namelist() if n not in sourcepaths and n not in {'ppt/presentation.xml','ppt/_rels/presentation.xml.rels','[Content_Types].xml'}]
 assert all(b.read(n)==data[n] for n in untouched)
 report={'totalSlides':76,'insertedSlides':[66,67],'originalSlideContentPreservedExceptPageNumbers':True,'originalNonSlidePartsPreserved':len(untouched),'nativeTablesAdded':2,'sourceSha256':hashlib.sha256(base.read_bytes()).hexdigest(),'finalSha256':hashlib.sha256(out.read_bytes()).hexdigest()}
 (root/'build/preservation.json').write_text(json.dumps(report,indent=2),'utf8');print(json.dumps(report))
