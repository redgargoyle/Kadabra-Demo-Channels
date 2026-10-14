import fs from 'node:fs/promises';
import path from 'node:path';
import {generateKeyPairSync,createHash,sign} from 'node:crypto';
import {Metadata,Root,Targets,Snapshot,Timestamp,Key,Signature,TargetFile,MetaFile} from '@tufjs/models';
import {atomicJson,readJson} from '../core/files.mjs';
import {validateCatalog,assert} from '../core/catalog.mjs';
const hash=b=>createHash('sha256').update(b).digest('hex');
const bytes=m=>Buffer.from(JSON.stringify(m.toJSON()));
const expires=days=>new Date(Date.now()+days*86400000).toISOString();
function pair(){const {privateKey,publicKey}=generateKeyPairSync('ed25519');const publicHex=publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('hex');const keyVal={public:publicHex};const keyID=hash(JSON.stringify({keytype:'ed25519',scheme:'ed25519',keyval:keyVal}));return{private:privateKey.export({format:'pem',type:'pkcs8'}).toString(),public:{keyID,keyType:'ed25519',scheme:'ed25519',keyVal}};}
const signer=k=>data=>new Signature({keyID:k.public.keyID,sig:sign(null,data,k.private).toString('hex')});
export async function initializePublisher(keyDir,feedDir){
 await fs.mkdir(keyDir,{recursive:true,mode:0o700});await fs.chmod(keyDir,0o700);
 assert(!await readJson(path.join(keyDir,'online.json'),null),'Publisher already initialized; preserve its root');
 const keys={root:[pair(),pair()],targets:pair(),snapshot:pair(),timestamp:pair()};
 const root=new Metadata(new Root({version:1,specVersion:'1.0.31',expires:expires(365),consistentSnapshot:true}));
 for(const k of keys.root)root.signed.addKey(new Key(k.public),'root');root.signed.roles.root.threshold=2;
 for(const role of ['targets','snapshot','timestamp'])root.signed.addKey(new Key(keys[role].public),role);
 for(const k of keys.root)root.sign(signer(k),true);
 root.verifyDelegate('root',root);
 await atomicJson(path.join(keyDir,'offline-root.json'),{root:keys.root,warning:'Offline root keys: move a verified encrypted backup to operator-controlled storage. Never upload these keys into the source or player release.'});
 await atomicJson(path.join(keyDir,'online.json'),{targets:keys.targets,snapshot:keys.snapshot,timestamp:keys.timestamp});
 await fs.mkdir(path.join(feedDir,'metadata'),{recursive:true});await fs.mkdir(path.join(feedDir,'targets'),{recursive:true});
 await fs.writeFile(path.join(feedDir,'metadata','1.root.json'),bytes(root));await fs.writeFile(path.join(feedDir,'metadata','root.json'),bytes(root));
 return root.toJSON();
}
export async function publishCatalog(keyDir,feedDir,catalog,{expectedRevision=0}={}){
 validateCatalog(catalog);const lock=path.join(keyDir,'publish.lock');const handle=await fs.open(lock,'wx',0o600);
 try{
  const current=await readJson(path.join(keyDir,'published.json'),{revision:0,identities:{}});assert(current.revision===expectedRevision,'Publisher revision changed; re-review proposal');assert(catalog.revision===current.revision+1,'A publication must advance exactly one catalog revision');
  const identities={...current.identities};for(const p of catalog.packages){const identity=hash(JSON.stringify(p));assert(!identities[p.id]||identities[p.id]===identity,'Immutable package identity changed');identities[p.id]=identity;}
  const keys=await readJson(path.join(keyDir,'online.json'));assert(keys,'Publisher keys unavailable');const version=catalog.revision;
  const targetBytes=Buffer.from(JSON.stringify(catalog));const targetHash=hash(targetBytes);
  const targets=new Metadata(new Targets({version,specVersion:'1.0.31',expires:expires(30)}));targets.signed.addTarget(new TargetFile({path:'catalog.json',length:targetBytes.length,hashes:{sha256:targetHash}}));targets.sign(signer(keys.targets));
  const targetMetaBytes=bytes(targets);const snapshot=new Metadata(new Snapshot({version,specVersion:'1.0.31',expires:expires(7),meta:{'targets.json':new MetaFile({version,length:targetMetaBytes.length,hashes:{sha256:hash(targetMetaBytes)}})}}));snapshot.sign(signer(keys.snapshot));
  const snapshotBytes=bytes(snapshot);const timestamp=new Metadata(new Timestamp({version,specVersion:'1.0.31',expires:expires(3),snapshotMeta:new MetaFile({version,length:snapshotBytes.length,hashes:{sha256:hash(snapshotBytes)}})}));timestamp.sign(signer(keys.timestamp));
  await fs.writeFile(path.join(feedDir,'targets',targetHash+'.catalog.json'),targetBytes);
  await fs.writeFile(path.join(feedDir,'metadata',version+'.targets.json'),targetMetaBytes);await fs.writeFile(path.join(feedDir,'metadata',version+'.snapshot.json'),snapshotBytes);
  // Publish the timestamp last; clients can never observe a pointer to missing metadata.
  await atomicJson(path.join(feedDir,'metadata','timestamp.json'),timestamp.toJSON());
  await atomicJson(path.join(keyDir,'published.json'),{revision:version,identities,catalogHash:targetHash,publishedAt:new Date().toISOString()});
  return{revision:version,catalogHash:targetHash};
 }finally{await handle.close();await fs.rm(lock,{force:true});}
}
if(import.meta.url===new URL(process.argv[1],'file:').href){
 const [action,keyDir,feedDir,catalogFile,expected='0']=process.argv.slice(2);
 if(!keyDir||!feedDir)throw new Error('Usage: node tools/publisher.mjs init|publish <key-directory> <feed-directory> [catalog.json] [expected-revision]');
 if(action==='init'){await initializePublisher(path.resolve(keyDir),path.resolve(feedDir));console.log('Publisher initialized. Root keys and online signing keys are separate; private keys were not printed.');}
 else if(action==='publish')console.log(await publishCatalog(path.resolve(keyDir),path.resolve(feedDir),JSON.parse(await fs.readFile(catalogFile,'utf8')),{expectedRevision:Number(expected)}));
 else throw new Error('Unknown publisher action');
}
