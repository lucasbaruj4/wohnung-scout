let state, filter = 'matches', selected;
const $ = id => document.getElementById(id);
const euro = n => new Intl.NumberFormat('de-DE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(n);
const median = xs => { const a=[...xs].sort((a,b)=>a-b); return a.length ? (a[Math.floor((a.length-1)/2)]+a[Math.floor(a.length/2)])/2 : null; };
const text = (tag, content, className) => {const el=document.createElement(tag);el.textContent=content;if(className)el.className=className;return el;};
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
async function load(initial=false){
  try {
    state=await api('/api/state');
    if(initial) for(const [key,value] of Object.entries(state.settings)){const input=$('settings').elements[key];if(input.type==='checkbox')input.checked=value;else input.value=value;}
    $('current').textContent=euro(state.settings.current_total);
    $('connection').textContent=state.scanning?'● Checking sources…':'● Local collector';
    $('last-check').textContent=state.last_check?`Last check ${new Date(state.last_check).toLocaleString()}`:'Waiting for first check';
    $('telegram-status').textContent=state.telegram_connected?'Bot configured. New matches will be sent at the next check.':'Telegram is not connected yet. Run the setup script below.';
    $('notice').textContent=[...state.errors,state.telegram_error].filter(Boolean).join(' ');
    $('refresh').disabled=state.scanning;
    market();renderListings();
  } catch(error){$('notice').textContent=error.message+' Existing results remain visible.';}
}
function market(){
  const rows=state.listings.filter(r=>r.currently_seen&&!r.temporary);
  $('count').textContent=rows.length;
  $('median-rent').textContent=rows.length?euro(median(rows.map(r=>r.rent))):'—';
  $('median-size').textContent=rows.length?`${Math.round(median(rows.map(r=>r.size)))} m²`:'—';
  $('median-rate').textContent=rows.length?`${median(rows.map(r=>r.price_per_m2)).toFixed(1)} €`:'—';
  chart(rows);
  $('size-bands').replaceChildren();
  for(const [lo,hi,label] of [[0,30,'Under 30 m²'],[30,50,'30–49 m²'],[50,75,'50–74 m²'],[75,Infinity,'75 m² and up']]){
    const band=rows.filter(r=>r.size>=lo&&r.size<hi),div=text('div','', 'band');
    div.append(text('span',label),text('strong',band.length?euro(median(band.map(r=>r.rent))):'No sample'),text('span',`${band.length} listings · median listed rent`));$('size-bands').append(div);
  }
}
function chart(rows){
  const svg=$('chart');svg.replaceChildren();
  const make=(tag,attrs,label)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(label!==undefined)n.textContent=label;svg.append(n);return n;};
  if(!rows.length){make('text',{x:80,y:180,class:'plot-label'},'The chart will appear after the first successful check.');return;}
  const xmax=Math.ceil(Math.max(100,...rows.map(r=>r.size))/25)*25;
  const ymax=Math.ceil(Math.max(1200,state.settings.current_total,...rows.map(r=>r.rent))/250)*250;
  const x=n=>55+n/xmax*660,y=n=>325-n/ymax*285;
  for(let i=0;i<=4;i++){const v=ymax*i/4;make('line',{x1:55,y1:y(v),x2:715,y2:y(v),stroke:'#e4e7df'});make('text',{x:44,y:y(v)+4,'text-anchor':'end',class:'plot-label'},Math.round(v));const size=xmax*i/4;make('text',{x:x(size),y:348,'text-anchor':'middle',class:'plot-label'},Math.round(size));}
  make('text',{x:715,y:375,'text-anchor':'end',class:'plot-label'},'APARTMENT SIZE (m²)');
  const budget=Math.max(0,state.settings.budget-state.settings.extra_costs);
  if(budget<=ymax){make('line',{x1:55,y1:y(budget),x2:715,y2:y(budget),stroke:'#c46436','stroke-dasharray':'6 5'});make('text',{x:60,y:y(budget)-7,class:'plot-label'},`Your listed-rent limit: ${euro(budget)}`);}
  for(const row of rows){
    const dot=make('circle',{cx:x(row.size),cy:y(row.rent),r:5,fill:row.matches?'#246446':'#bcc7bb',class:'plot-point',tabindex:0,role:'button','aria-label':`${row.title}, ${row.size} square metres, listed rent ${euro(row.rent)}`});
    const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=`${row.size} m² · ${euro(row.rent)} listed · ${row.title}`;dot.append(title);
    const choose=()=>{selected=row.id;filter='all';updateTabs();renderListings();document.getElementById(`listing-${row.id}`)?.scrollIntoView({behavior:'smooth',block:'center'});};
    dot.addEventListener('click',choose);dot.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});
  }
}
function updateTabs(){document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===filter);b.setAttribute('aria-pressed',String(b.dataset.filter===filter));});}
function renderListings(){
  let rows=state.listings.filter(r=>filter==='saved'?r.status==='saved':filter==='hidden'?r.status==='hidden':r.currently_seen&&r.status!=='hidden'&&(filter==='all'||r.matches));
  const sort=$('sort').value;
  rows.sort((a,b)=>sort==='size'?b.size-a.size:sort==='value'?(b.value_discount??-Infinity)-(a.value_discount??-Infinity):sort==='new'?b.first_seen.localeCompare(a.first_seen):b.estimated_saving-a.estimated_saving);
  const container=$('listings');container.replaceChildren();
  if(!rows.length){container.append(text('p',state.scanning?'Checking sources. Results will appear automatically.':filter==='matches'?'No apartments meet these limits. Try a higher budget, a smaller size, or browse all listings.':'No listings in this view yet.','empty'));return;}
  for(const row of rows){
    const card=text('article','',`listing${selected===row.id?' selected':''}`);card.id=`listing-${row.id}`;
    const top=text('div','','listing-top');top.append(text('span',row.temporary?'TEMPORARY LET':'OWN APARTMENT'));
    if(row.good_value)top.append(text('span',`${Math.round(row.value_discount)}% below peers`,'badge'));
    else if(row.status==='saved')top.append(text('span','Saved','badge'));
    card.append(top);
    const h=text('h3',''),link=text('a',row.title);link.href=row.url;link.target='_blank';link.rel='noopener noreferrer';h.append(link);card.append(h,text('p',row.location,'location'));
    const facts=text('div','','facts');for(const [value,label]of [[euro(row.rent),'Listed rent'],[`${row.size} m²`,'Space'],[`${row.price_per_m2.toFixed(1)} €`,'Listed / m²']]){const box=text('div','');box.append(text('strong',value),text('span',label));facts.append(box);}card.append(facts);
    const saving=text('div','','saving');saving.append(text('span',`${euro(row.estimated_total)} estimated total`),text('strong',row.estimated_saving>=0?`${euro(row.estimated_saving)} less / month`:`${euro(-row.estimated_saving)} more / month`));card.append(saving);
    const detail=row.details_checked?`Base rent ${row.base_rent===null?'unknown':euro(row.base_rent)} · service charges ${row.service_costs===null?'unknown':euro(row.service_costs)} · other costs ${row.other_costs===null?'unknown':euro(row.other_costs)}`:'Rent basis not verified on the detail page.';
    card.append(text('p',`${detail}. Added reserve: ${euro(state.settings.extra_costs)}. Utilities need confirmation.`,'costs'));
    if(row.available)card.append(text('p',`Available: ${row.available}${row.currently_seen?'':' · Not seen in latest sample'}`,'costs'));
    const bottom=text('div','','listing-bottom'),view=text('a','View listing ↗');view.href=row.url;view.target='_blank';view.rel='noopener noreferrer';bottom.append(view);
    const actions=text('div','');for(const [label,status]of [[row.status==='saved'?'Unsave':'Save',row.status==='saved'?'new':'saved'],[row.status==='hidden'?'Restore':'Hide',row.status==='hidden'?'new':'hidden']]){const b=text('button',label);b.addEventListener('click',async()=>{try{await api(`/api/listings/${row.id}/status`,{status});await load();}catch(e){$('notice').textContent=e.message;}});actions.append(b);}bottom.append(actions);card.append(bottom);container.append(card);
  }
}
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;updateTabs();renderListings();}));
$('sort').addEventListener('change',renderListings);
$('settings').addEventListener('submit',async e=>{e.preventDefault();const data={};for(const key of ['budget','min_size','extra_costs','current_total'])data[key]=Number(e.target.elements[key].value);data.include_temporary=e.target.elements.include_temporary.checked;try{await api('/api/settings',data);await load();$('notice').textContent='Limits saved. Telegram uses these limits at the next check.';}catch(error){$('notice').textContent=error.message;}});
$('refresh').addEventListener('click',async()=>{try{await api('/api/scan',{});await load();}catch(error){$('notice').textContent=error.message;}});
load(true);setInterval(()=>load(),15000);
