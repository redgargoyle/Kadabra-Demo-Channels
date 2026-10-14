import {validateCatalog, packageForGame} from '../core/catalog.mjs';
const platforms=['linux','windows','macos'];
const clone=value=>JSON.parse(JSON.stringify(value));
export function publicAsset(pkg){return {name:pkg.name||decodeURIComponent(new URL(pkg.url).pathname.split('/').at(-1)),url:pkg.url,sizeBytes:pkg.sizeBytes,sha256:pkg.sha256,version:pkg.version,packageId:pkg.id,kind:pkg.kind,platform:pkg.platform,arch:pkg.arch};}
export function buildLatest(catalog,{websiteBaseline,previous=null,publishedAt=new Date().toISOString()}={}){
 validateCatalog(catalog);
 if(!websiteBaseline||websiteBaseline.schemaVersion!==1||!websiteBaseline.games)throw Error('Website baseline required; never replace existing public choices with preview defaults');
 const games={};
 for(const game of catalog.games){
  const targets={};
  for(const platform of platforms)for(const arch of ['x64','arm64']){const pkg=packageForGame(catalog,game.id,platform,arch);if(pkg)targets[pkg.platform+':'+pkg.arch]=publicAsset(pkg);}
  let stable=clone(previous?.games?.[game.id]?.stable||websiteBaseline.games[game.id]||null);
  // Only an explicitly reviewed Stable proposal moves public website downloads.
  if(game.releaseChannel==='stable'){
   stable={...(stable||{}),title:game.title,tag:game.version,updatedAt:publishedAt,hidden:!!game.hidden,targets,knownPublished:true,directAssets:{...(stable?.directAssets||{})}};
   if(game.webUrl)stable.webDemo=game.webUrl;
   for(const platform of platforms){const pkg=targets[platform+':x64']||targets[platform+':any'];if(pkg?.kind==='native')stable.directAssets[platform]=pkg;}
  }
  if(!stable&&game.webUrl)stable={title:game.title,tag:game.version||'Browser edition',updatedAt:publishedAt,webDemo:game.webUrl,webDemoLabel:'Play in your browser',knownPublished:true,directAssets:{}};
  games[game.id]={title:game.title,preview:{version:game.version,hidden:!!game.hidden,targets,webDemo:game.webUrl||null},stable};
 }
 return {schemaVersion:2,revision:catalog.revision,publishedAt,games};
}
export function websiteChannels(latest){
 if(latest.schemaVersion!==2)throw Error('Unsupported latest manifest');
 return {schemaVersion:1,revision:latest.revision,updatedAt:latest.publishedAt,games:Object.fromEntries(Object.entries(latest.games).filter(([,g])=>g.stable&&!g.stable.hidden).map(([id,g])=>[id,g.stable]))};
}
