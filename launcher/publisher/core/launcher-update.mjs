const assert=(value,message)=>{if(!value)throw new Error(message);};
export function validateLauncherRelease(r){
 assert(r&&['linux','windows','macos'].includes(r.platform)&&['x64','arm64'].includes(r.arch),'Invalid launcher target');
 assert(/^\d+\.\d+\.\d+$/.test(r.version),'Invalid launcher version');
 assert(Number.isSafeInteger(r.sizeBytes)&&r.sizeBytes>0&&r.sizeBytes<2*1024**3,'Invalid launcher size');
 assert(/^[a-f0-9]{64}$/.test(r.sha256)&&/^[A-Za-z0-9+/]{86}==$/.test(r.sha512),'Invalid launcher digest');
 const url=new URL(r.url);assert(url.protocol==='https:'&&!url.username&&!url.password&&!url.hash,'Invalid launcher URL');
 assert(['github.com','release-assets.githubusercontent.com','kadabra.games'].includes(url.hostname),'Unapproved launcher host');
 const extension={linux:'.AppImage',windows:'.exe',macos:'.zip'}[r.platform];assert(url.pathname.endsWith(extension),'Invalid launcher format');
 assert(r.qualification==='qualified'&&r.updateRuntimeTested===true,'Launcher update has not passed platform qualification');
 return r;
}
export function newerVersion(candidate,current){const a=candidate.split('.').map(Number),b=current.split('.').map(Number);for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]>b[i];}return false;}
export function launcherRelease(catalog,platform,arch,current){const releases=(catalog.launcherReleases||[]).map(validateLauncherRelease).filter(r=>r.platform===platform&&r.arch===arch&&newerVersion(r.version,current));return releases.sort((a,b)=>newerVersion(a.version,b.version)?-1:1)[0]||null;}
