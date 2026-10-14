from pathlib import Path
from copy import deepcopy
import zipfile
import sys
from xml.etree import ElementTree as E
p=Path(sys.argv[1]);ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
E.register_namespace('p',ns['p']);E.register_namespace('a',ns['a'])
with zipfile.ZipFile(p) as z: parts={n:z.read(n) for n in z.namelist()}
master=E.fromstring(parts['ppt/slideMasters/slideMaster1.xml'])
number=next(s for s in master.findall('.//p:sp',ns) if s.find('.//a:fld[@type="slidenum"]',ns) is not None)
for name,data in list(parts.items()):
 if not (name.startswith('ppt/slides/slide') and name.endswith('.xml')): continue
 root=E.fromstring(data);tree=root.find('p:cSld/p:spTree',ns);index=int(name.rsplit('slide',1)[1][:-4]);field=tree.find('.//a:fld[@type="slidenum"]',ns)
 if field is None:
  clone=deepcopy(number);ids=[int(x.get('id','0')) for x in tree.findall('.//p:cNvPr',ns)];clone.find('p:nvSpPr/p:cNvPr',ns).set('id',str(max(ids,default=0)+1));field=clone.find('.//a:fld',ns);tree.append(clone)
 field.find('a:t',ns).text=str(index);parts[name]=E.tostring(root,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
 for n,b in parts.items():z.writestr(n,b)
print('Native automatic slide numbers added')
