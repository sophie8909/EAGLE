import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Project/EAGLE/Meeting/20261104_genotype';
const p=await PresentationFile.importPptx(await FileBlob.load(root+'/deliverables/EAGLE_1105_with_genotype.pptx'));
await fs.mkdir(root+'/build/preview',{recursive:true});
for(const n of [60,61,62,63,64,65,66]){await fs.writeFile(root+`/build/preview/${n}.png`,new Uint8Array(await (await p.export({slide:p.slides.items[n-1],format:'png',scale:1})).arrayBuffer()));console.log('rendered '+n);}
