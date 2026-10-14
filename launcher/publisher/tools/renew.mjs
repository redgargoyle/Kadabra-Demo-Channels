import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {publishCatalog} from './publisher.mjs';
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const feed=path.join(base,'v1');
const temp=await fs.mkdtemp(path.join(os.tmpdir(),'kadabra-publisher-'));
try{
 if(!process.env.KADABRA_TUF_ONLINE_KEYS)throw new Error('Online publisher keys are not configured');
 await fs.writeFile(path.join(temp,'online.json'),process.env.KADABRA_TUF_ONLINE_KEYS,{mode:0o600});
 const state=JSON.parse(await fs.readFile(path.join(feed,'publisher-state.json'),'utf8'));
 await fs.writeFile(path.join(temp,'published.json'),JSON.stringify(state),{mode:0o600});
 const catalog=JSON.parse(await fs.readFile(path.join(base,'catalog-source.json'),'utf8'));
 catalog.revision=state.revision+1;catalog.validUntil=new Date(Date.now()+3*86400000).toISOString();
 const result=await publishCatalog(temp,feed,catalog,{expectedRevision:state.revision});
 await fs.copyFile(path.join(temp,'published.json'),path.join(feed,'publisher-state.json'));
 console.log('Renewed signed preview catalog, revision '+result.revision);
}finally{await fs.rm(temp,{recursive:true,force:true});}
