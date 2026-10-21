'use strict';
const el=id=>document.getElementById(id);
let ws,ctx,stream,cam,node,source,silent,timer,starting=false,ready=false,muted=false,nextPlay=0,epoch=0;
let playing=new Set(),lastRole=null;
const status=text=>el('status').textContent=text;
function send(value){if(ready&&ws?.readyState===1&&ws.bufferedAmount<128000)ws.send(JSON.stringify(value));}
function b64(buffer){let s='';for(const b of new Uint8Array(buffer))s+=String.fromCharCode(b);return btoa(s);}
function stopAudio(){for(const s of playing){try{s.stop();}catch{}}playing.clear();nextPlay=0;}
function transcript(role,text){if(lastRole!==role){const p=document.createElement('p');p.dataset.role=role;p.textContent=(role==='user'?'Ви: ':'Помічник: ');el('transcript').append(p);lastRole=role;}el('transcript').lastChild.append(document.createTextNode(text));el('transcript').scrollTop=el('transcript').scrollHeight;}
function play(encoded){if(!ctx)return;const raw=atob(encoded),pcm=new Int16Array(raw.length/2);const view=new DataView(new ArrayBuffer(raw.length));for(let i=0;i<raw.length;i++)view.setUint8(i,raw.charCodeAt(i));for(let i=0;i<pcm.length;i++)pcm[i]=view.getInt16(i*2,true);const buffer=ctx.createBuffer(1,pcm.length,24000);const floats=buffer.getChannelData(0);for(let i=0;i<pcm.length;i++)floats[i]=pcm[i]/32768;if(nextPlay-ctx.currentTime>15){stopAudio();status('Звук відставав; зайву чергу скинуто.');}const s=ctx.createBufferSource();s.buffer=buffer;s.connect(ctx.destination);s.onended=()=>playing.delete(s);playing.add(s);nextPlay=Math.max(ctx.currentTime+.03,nextPlay);s.start(nextPlay);nextPlay+=buffer.duration;}
function cameraOff(){clearInterval(timer);timer=null;cam?.getTracks().forEach(t=>t.stop());cam=null;el('preview').srcObject=null;el('preview').hidden=true;el('camera').textContent='Увімкнути камеру';}
function cleanup(){epoch++;ready=false;starting=false;cameraOff();stream?.getTracks().forEach(t=>t.stop());stream=null;node?.disconnect();source?.disconnect();silent?.disconnect();stopAudio();if(ctx){ctx.close().catch(()=>{});ctx=null;}if(ws){ws.onclose=null;ws.close();ws=null;}el('start').disabled=false;for(const id of ['stop','mic','camera','send'])el(id).disabled=true;el('consent').disabled=false;muted=false;el('mic').textContent='Вимкнути мікрофон';}
el('start').onclick=async()=>{
 if(starting||ready)return;if(!el('consent').checked){status('Підтвердьте передачу голосу та кадрів перед початком.');return;}
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){status('Потрібен HTTPS або localhost і браузер із доступом до мікрофона.');return;}
 starting=true;const attempt=++epoch;el('start').disabled=true;el('stop').disabled=false;el('consent').disabled=true;status('Підключаю мікрофон…');
 try{
  ctx=new AudioContext();await ctx.resume();
  const media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,channelCount:1},video:false});
  if(attempt!==epoch){media.getTracks().forEach(t=>t.stop());return;}stream=media;
  await ctx.audioWorklet.addModule('/static/pcm-worklet.js');if(attempt!==epoch)return;
  source=ctx.createMediaStreamSource(stream);node=new AudioWorkletNode(ctx,'pcm-capture');silent=ctx.createGain();silent.gain.value=0;source.connect(node);node.connect(silent);silent.connect(ctx.destination);
  node.port.onmessage=e=>{if(!muted)send({type:'audio',data:b64(e.data)});};
  ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/live');status('З’єднуюся з голосовим помічником…');
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==='ready'){ready=true;starting=false;for(const id of ['mic','camera','send'])el(id).disabled=false;status('Слухаю. Сеанс до 5 хвилин.');}else if(m.type==='audio')play(m.data);else if(m.type==='interrupted')stopAudio();else if(m.type==='transcript')transcript(m.role,m.text);else if(m.type==='status')status(m.message);else if(m.type==='turn_complete'){lastRole=null;status('Слухаю…');}else if(m.type==='sources'){for(const s of m.sources||[]){if(!s.url?.startsWith('/library/'))continue;const a=document.createElement('a');a.href=s.url;a.target='_blank';a.rel='noopener';a.textContent=s.document+', стор. '+s.page;el('sources').append(a);}}else if(m.type==='error'){status(m.message);cleanup();}};
  ws.onerror=()=>{status('Не вдалося з’єднатися. Перевірте вхід та мережу, потім повторіть.');cleanup();};
  ws.onclose=()=>{status('З’єднання завершено. Натисніть «Почати» для нового сеансу.');cleanup();};
 }catch(e){if(attempt!==epoch)return;status(e.name==='NotAllowedError'?'Надайте браузеру доступ до мікрофона.':'Не вдалося підключити звук. Перевірте браузер та пристрої.');cleanup();}
};
el('stop').onclick=()=>{send({type:'stop'});cleanup();status('Розмову завершено. Мікрофон і камера вимкнені.');};
el('mic').onclick=()=>{muted=!muted;stream?.getAudioTracks().forEach(t=>t.enabled=!muted);if(muted)send({type:'mute'});el('mic').textContent=muted?'Увімкнути мікрофон':'Вимкнути мікрофон';};
el('camera').onclick=async()=>{if(cam){cameraOff();return;}const attempt=epoch;el('camera').disabled=true;try{const media=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:640},height:{ideal:480}},audio:false});if(attempt!==epoch||!ready){media.getTracks().forEach(t=>t.stop());return;}cam=media;const video=el('preview');video.srcObject=cam;video.hidden=false;await video.play();if(attempt!==epoch||!ready){cameraOff();return;}el('camera').textContent='Вимкнути камеру';const canvas=document.createElement('canvas');timer=setInterval(()=>{if(!ready||video.readyState<2)return;canvas.width=640;canvas.height=Math.round(video.videoHeight/video.videoWidth*640);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);send({type:'video',data:canvas.toDataURL('image/jpeg',.65).split(',')[1]});},1000);}catch{cameraOff();status('Камера недоступна. Голосова розмова працює без неї.');}finally{el('camera').disabled=!ready;}};
el('textform').onsubmit=e=>{e.preventDefault();const text=el('text').value.trim();if(!ready||!text)return;send({type:'text',text});transcript('user',text);lastRole=null;el('text').value='';};
window.addEventListener('pagehide',cleanup);document.addEventListener('visibilitychange',()=>{if(document.hidden&&(ready||starting)){cleanup();status('Розмову зупинено, бо сторінку приховано.');}});
