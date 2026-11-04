import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Project/EAGLE/Meeting/20261104_strategy_initialization';
const p=await PresentationFile.importPptx(await FileBlob.load(root+'/deliverables/EAGLE_1105_strategy_initialization_implemented.pptx'));
await fs.mkdir(root+'/build/preview-v2',{recursive:true});
for(const n of [65,66,67,68]){await fs.writeFile(root+`/build/preview-v2/${n}.png`,new Uint8Array(await (await p.export({slide:p.slides.items[n-1],format:'png',scale:1})).arrayBuffer()));console.log('rendered '+n);}
