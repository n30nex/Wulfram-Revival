'use strict';
const byId=id=>document.getElementById(id);
byId('copy-server').addEventListener('click',async()=>{
  try { await navigator.clipboard.writeText('wulfram.canadaverse.org'); byId('copy-server').textContent='Copied'; }
  catch { byId('copy-server').textContent='Select address to copy'; }
});
fetch('release.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Release unavailable');return r.json();}).then(release=>{
  if(!release.ready || !/^\/downloads\/wulfram\/[a-zA-Z0-9._-]+\.zip$/.test(release.url) || !/^[a-f0-9]{64}$/.test(release.sha256))return;
  byId('download').href=release.url;
  byId('download').removeAttribute('aria-disabled');
  byId('download').textContent='Download for Windows ↗';
  byId('release-note').textContent=`Community alpha ${release.version} · Windows · Free to play`;
  byId('package-detail').textContent=`ZIP · ${(release.bytes/1024/1024).toFixed(1)} MB · Extract the entire folder before playing.`;
  byId('checksum').href=release.url+'.sha256'; byId('checksum').hidden=false;
}).catch(()=>{});
const mapNames={crossroads:'Crossroads',mayhem:'Mayhem',frontier:'Canadaverse Frontier'};
async function refreshStatus(){
  try {
    const r=await fetch('status.json',{cache:'no-store',signal:AbortSignal.timeout(6000)});
    if(!r.ok)throw Error('Status unavailable');
    const status=await r.json(), age=Date.now()-Date.parse(status.updated_utc);
    if(!Number.isFinite(age)||age>30000||age< -10000||!Array.isArray(status.teams))throw Error('Status stale');
    byId('live-title').textContent=status.phase==='changing_map'?'Changing battlefield':`${mapNames[status.map]||status.map} · match in progress`;
    const remaining=status.seconds_remaining==null?'Untimed round':`${Math.floor(status.seconds_remaining/60)}:${String(status.seconds_remaining%60).padStart(2,'0')} remaining`;
    byId('live-detail').textContent=`${status.bots} CPU players · ${status.players}/${status.human_capacity} human places filled · ${remaining}`;
    for(const [id,name] of [[1,'red-score'],[2,'blue-score']]) byId(name).textContent=String(status.teams.find(t=>t.id===id)?.points??'—');
    byId('status-note').textContent='Live match snapshot · refreshes every 10 seconds';
  }catch{
    byId('live-title').textContent='Server status unavailable';
    byId('live-detail').textContent='The latest match snapshot could not be verified. Try connecting in the client or check back shortly.';
    byId('red-score').textContent=byId('blue-score').textContent='—';
    byId('status-note').textContent='No current status is being reported.';
  }
}
refreshStatus();setInterval(refreshStatus,10000);
