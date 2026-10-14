import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {publishCatalog} from './publisher.mjs';
import {buildLatest} from './latest.mjs';
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
 const previous=await fs.readFile(path.join(base,'latest.json'),'utf8').then(JSON.parse).catch(e=>{if(e.code==='ENOENT')return null;throw e;});
 const websiteBaseline=JSON.parse(await fs.readFile(path.join(base,'website-stable-baseline.json'),'utf8'));
 const latest=buildLatest(catalog,{websiteBaseline,previous});
 await fs.mkdir(path.join(base,'latest'),{recursive:true});
 await fs.writeFile(path.join(base,'latest.json'),JSON.stringify(latest,null,2)+'\n');
 for(const [gameId,game]of Object.entries(latest.games))await fs.writeFile(path.join(base,'latest',gameId+'.json'),JSON.stringify({schemaVersion:2,revision:latest.revision,publishedAt:latest.publishedAt,gameId,...game},null,2)+'\n');
 await fs.copyFile(path.join(temp,'published.json'),path.join(feed,'publisher-state.json'));
 console.log('Renewed signed preview catalog, revision '+result.revision);
}finally{await fs.rm(temp,{recursive:true,force:true});}
