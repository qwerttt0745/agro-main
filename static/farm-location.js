/* Save the current user's point without replacing unrelated profile values. */
(()=>{
 const form=document.getElementById('location-form'),button=document.getElementById('save-location'),status=document.getElementById('location-status');
 const editor=new AgroLocationEditor(document.getElementById('farm-map-editor'),{onChange:()=>{status.textContent='Є незбережені зміни.';}});
 const summary=p=>{document.getElementById('point').textContent=p.latitude==null||p.longitude==null?'Точка ферми ще не задана.':(p.location_name?p.location_name+' · ':'')+p.latitude+', '+p.longitude;};
 async function response(r){if(r.status===401){location.href='/login';throw Error('Увійдіть знову.');}const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Перевірте координати: широта −90…90, довгота −180…180. Потрібні обидва значення.');return d;}
 form.onsubmit=async e=>{e.preventDefault();button.disabled=true;status.textContent='Зберігаю…';try{const p=await response(await fetch('/api/farm/location',{method:'PUT',headers:{'Content-Type':'application/json','X-Agro-Request':'1'},body:JSON.stringify(editor.value())}));editor.set(p);summary(p);status.textContent='Точку ферми збережено.';if(!document.getElementById('weather-target').value)await loadWeather();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}};
 async function load(){
  try{
   const p=await response(await fetch('/api/farm/location'));editor.set(p);summary(p);status.textContent='';button.disabled=false;
   const fields=await response(await fetch('/api/fields')),select=document.getElementById('weather-target');
   for(const f of fields){const opt=document.createElement('option');opt.value=f.id;const known=(f.latitude!=null&&f.longitude!=null)||f.boundary;opt.textContent=f.name+(known?'':' — точку ще не задано');select.append(opt);}
   const requested=new URLSearchParams(location.search).get('field_id');if(requested&&fields.some(f=>String(f.id)===requested))select.value=requested;
   await loadWeather();
  }catch(e){status.textContent=e.message;}
 }
 load();
})();
