/* Shared point/polygon editor. Empty coordinates never create a selected marker. */
window.AgroLocationEditor=class {
 constructor(host,{polygon=false,onChange=()=>{}}={}){
  this.host=host;this.polygon=polygon;this.onChange=onChange;this.points=[];this.vertices=[];this.drawing=polygon;this.mode=polygon?'boundary':'point';
  host.classList.add('location-editor');
  const make=(tag,text,parent=host)=>{const n=document.createElement(tag);n.textContent=text;parent.append(n);return n;};
  this.make=make;
  make('p',polygon?'Натискайте по межі поля, щоб додати вершини. Маркери можна пересувати. Після трьох вершин з’явиться контур.':'Натисніть на карту в місці ферми. Або знайдіть населений пункт і уточніть точку.',host).className='hint';
  const search=make('div','');search.className='map-controls';
  const searchLabel=make('label','Населений пункт',search);this.query=make('input','',searchLabel);this.query.placeholder='Назва села або міста';this.query.maxLength=150;this.query.minLength=2;this.query.setAttribute('aria-label','Населений пункт');
  this.searchButton=make('button','Знайти',search);this.searchButton.type='button';this.searchButton.onclick=()=>this.search();
  this.query.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();this.search();}});
  this.results=make('div','');this.results.className='search-results';
  const attribution=make('p','Пошук: ');attribution.className='hint';const credit=make('a','Open-Meteo / GeoNames',attribution);credit.href='https://open-meteo.com/en/docs/geocoding-api';credit.target='_blank';credit.rel='noopener';
  this.mapHost=make('div','');this.mapHost.className='location-map';this.mapHost.setAttribute('aria-label',polygon?'Карта меж поля':'Карта розташування ферми');
  this.status=make('p','');this.status.className='map-status';this.status.setAttribute('role','status');
  if(polygon){
   const controls=make('div','');controls.className='map-controls map-actions';
   const action=(text,fn)=>{const b=make('button',text,controls);b.type='button';b.onclick=fn;return b;};
   action('Додати вершини',()=>{this.drawing=true;this.mode='boundary';this.status.textContent='Натискайте на карту по межі поля.';});
   action('Завершити контур',()=>{if(this.points.length<3){this.status.textContent='Додайте щонайменше три вершини.';return;}this.drawing=false;this.status.textContent='Контур готовий. Маркери можна пересувати; збережіть поле.';});
   action('Скасувати вершину',()=>{this.points.pop();this.renderBoundary();});
   action('Очистити межу',()=>{this.points=[];this.drawing=true;this.mode='boundary';this.renderBoundary();});
  }
  let inputHost=host;
  if(polygon){inputHost=make('details','');make('summary','Окрема точка прогнозу (необов’язково)',inputHost);make('p','Якщо координати порожні, прогноз використовує точку всередині контуру поля. Точка не є прогнозом для всієї площі.',inputHost).className='hint';const b=make('button','Поставити точку прогнозу на карті',inputHost);b.type='button';b.onclick=()=>{this.mode='point';this.status.textContent='Натисніть на карту, щоб поставити окрему точку прогнозу.';};}
  const nameLabel=make('label','Назва локації',inputHost);this.name=make('input','',nameLabel);this.name.name='location_name';this.name.maxLength=300;this.name.placeholder=polygon?'Наприклад: Північне поле':'Наприклад: Ферма біля села';
  const coords=make('div','',inputHost);coords.className='coordinates';
  const input=(label,key,min,max)=>{const l=make('label',label,coords),n=make('input','',l);n.type='number';n.name=key;n.min=min;n.max=max;n.step='any';n.placeholder='Не задано';n.addEventListener('input',()=>{this.renderPoint(false);this.onChange();});return n;};
  this.lat=input('Широта','latitude',-90,90);this.lon=input('Довгота','longitude',-180,180);
  const clear=make('button',polygon?'Прибрати окрему точку':'Прибрати точку',inputHost);clear.type='button';clear.onclick=()=>{this.lat.value='';this.lon.value='';this.name.value='';this.renderPoint(false);this.onChange();};
  make('p','Координати позначають точку, а не межі ферми. Не визначають тип ґрунту чи площу.',inputHost).className='hint';
  this.name.addEventListener('input',()=>this.onChange());
  if(!window.L){this.mapHost.textContent='Карта недоступна. Можна ввести координати вручну.';return;}
  // World overview only: there is no default farm point or field boundary.
  this.map=L.map(this.mapHost,{worldCopyJump:true}).fitWorld();
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,referrerPolicy:'strict-origin-when-cross-origin',attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(this.map).on('tileerror',()=>{this.status.textContent='Підкладка карти тимчасово недоступна. Координати можна ввести вручну.';});
  this.map.on('click',e=>{if(this.polygon&&this.mode==='boundary'){if(!this.drawing)return;if(this.points.length>=200){this.status.textContent='До 200 вершин на поле.';return;}this.points.push([e.latlng.lat,e.latlng.lng]);this.renderBoundary();}else{this.setPoint(e.latlng.lat,e.latlng.lng);this.name.value='';this.onChange();}});
 }
 value(){const number=n=>n.value===''?null:Number(n.value);return {latitude:number(this.lat),longitude:number(this.lon),location_name:this.name.value.trim()};}
 boundary(){if(!this.points.length)return null;if(this.points.length<3)throw Error('Для межі поля потрібно щонайменше три вершини.');const ring=this.points.map(([lat,lon])=>[lon,lat]);return {type:'Polygon',coordinates:[[...ring,[...ring[0]]]]};}
 setPoint(lat,lon){this.lat.value=Number(lat).toFixed(7);this.lon.value=Number(lon).toFixed(7);this.renderPoint(false);this.onChange();}
 renderPoint(fit){if(!this.map)return;const p=this.value(),valid=p.latitude!==null&&p.longitude!==null&&Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180;if(this.marker){this.map.removeLayer(this.marker);this.marker=null;}if(!valid)return;this.marker=L.marker([p.latitude,p.longitude],{draggable:true,title:'Точка прогнозу'}).addTo(this.map);this.marker.on('dragend',()=>{const p=this.marker.getLatLng();this.setPoint(p.lat,p.lng);this.name.value='';this.onChange();});if(fit)this.map.setView([p.latitude,p.longitude],14);}
 renderBoundary(){if(!this.map)return;for(const m of this.vertices)this.map.removeLayer(m);this.vertices=[];if(this.shape)this.map.removeLayer(this.shape);this.points.forEach((p,i)=>{const marker=L.marker(p,{draggable:true,title:'Вершина '+(i+1)}).addTo(this.map);marker.on('drag',()=>{const ll=marker.getLatLng();this.points[i]=[ll.lat,ll.lng];if(this.shape)this.shape.setLatLngs(this.points);});marker.on('dragend',()=>this.onChange());this.vertices.push(marker);});if(this.points.length)this.shape=(this.points.length>=3?L.polygon(this.points,{color:'#6a942b',fillOpacity:.25}):L.polyline(this.points,{color:'#6a942b'})).addTo(this.map);this.status.textContent=this.points.length?'Вершин: '+this.points.length+'. Збережіть поле, щоб записати межу.':'Межі ще не задані.';this.onChange();}
 set(value={},viewPoint=null){this.lat.value=value.latitude??'';this.lon.value=value.longitude??'';this.name.value=value.location_name??(typeof value.location==='string'?value.location:'');this.renderPoint(true);this.points=(value.boundary?.coordinates?.[0]||[]).slice(0,-1).map(([lon,lat])=>[lat,lon]);this.drawing=this.points.length===0;this.mode=this.polygon?'boundary':'point';if(this.polygon){this.renderBoundary();if(this.points.length)this.map?.fitBounds(L.latLngBounds(this.points),{padding:[24,24],maxZoom:16});else if(this.lat.value===''&&viewPoint?.latitude!=null)this.map?.setView([viewPoint.latitude,viewPoint.longitude],13);}this.results.replaceChildren();this.status.textContent='';}
 async search(){const q=this.query.value.trim();if(q.length<2){this.status.textContent='Введіть щонайменше два символи.';return;}this.searchButton.disabled=true;this.results.replaceChildren();this.status.textContent='Шукаю…';try{const r=await fetch('/api/locations/search?q='+encodeURIComponent(q));if(r.status===401){location.href='/login';return;}const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Пошук недоступний.');for(const p of d.results){const b=this.make('button',p.location_name,this.results);b.type='button';b.onclick=()=>{if(this.polygon){this.map?.setView([p.latitude,p.longitude],14);this.status.textContent='Позначте межі поля на карті. Пошук лише перемістив карту.';}else{this.setPoint(p.latitude,p.longitude);this.name.value=p.location_name;this.renderPoint(true);this.status.textContent='Точку вибрано. Натисніть «Зберегти точку ферми».';this.onChange();}this.results.replaceChildren();};}this.status.textContent=d.results.length?'Виберіть населений пункт зі списку.':'Нічого не знайдено. Спробуйте іншу назву або введіть координати.';}catch(e){this.status.textContent='Не вдалося виконати пошук. Можна ввести координати вручну.';}finally{this.searchButton.disabled=false;}}
};
