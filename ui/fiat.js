/* CashMiner v2.11: display-only fiat layer, adapted from Munia's currency catalog.
   Quotes arrive over the authenticated loopback API, never from the mining engine.
   No private wallet data or addresses are sent to the quote providers. */
(function(){
  'use strict';
  const CURRENCIES=[
    {code:'USD',symbol:'$',name:'US Dollar'},
    {code:'ARS',symbol:'$',name:'Peso Argentino'},
    {code:'BRL',symbol:'R$',name:'Real'},
    {code:'MXN',symbol:'$',name:'Peso Mexicano'},
    {code:'CLP',symbol:'$',name:'Peso Chileno'},
    {code:'COP',symbol:'$',name:'Peso Colombiano'},
    {code:'PEN',symbol:'S/',name:'Sol Peruano'},
    {code:'UYU',symbol:'$U',name:'Peso Uruguayo'},
    {code:'PYG',symbol:'₲',name:'Guaraní'},
    {code:'BOB',symbol:'Bs',name:'Boliviano'},
    {code:'VES',symbol:'Bs',name:'Bolívar'},
    {code:'EUR',symbol:'€',name:'Euro'},
    {code:'GBP',symbol:'£',name:'British Pound'},
    {code:'CHF',symbol:'CHF',name:'Swiss Franc'},
    {code:'CAD',symbol:'C$',name:'Canadian Dollar'},
    {code:'AUD',symbol:'A$',name:'Australian Dollar'},
    {code:'NZD',symbol:'NZ$',name:'NZ Dollar'},
    {code:'JPY',symbol:'¥',name:'Yen'},
    {code:'CNY',symbol:'¥',name:'Yuan'},
    {code:'KRW',symbol:'₩',name:'Won'},
    {code:'INR',symbol:'₹',name:'Rupee'},
    {code:'RUB',symbol:'₽',name:'Ruble'},
    {code:'TRY',symbol:'₺',name:'Lira'},
    {code:'ZAR',symbol:'R',name:'Rand'},
    {code:'SEK',symbol:'kr',name:'Swedish Krona'},
    {code:'NOK',symbol:'kr',name:'Norwegian Krone'},
    {code:'DKK',symbol:'kr',name:'Danish Krone'},
    {code:'PLN',symbol:'zł',name:'Zloty'},
    {code:'CZK',symbol:'Kč',name:'Koruna'},
    {code:'HUF',symbol:'Ft',name:'Forint'},
    {code:'UAH',symbol:'₴',name:'Hryvnia'},
    {code:'ILS',symbol:'₪',name:'Shekel'},
    {code:'AED',symbol:'د.إ',name:'Dirham'},
    {code:'SAR',symbol:'ر.س',name:'Riyal'},
    {code:'KWD',symbol:'ك',name:'Kuwaiti Dinar'},
    {code:'BHD',symbol:'ب.د',name:'Bahraini Dinar'},
    {code:'HKD',symbol:'$',name:'HK Dollar'},
    {code:'TWD',symbol:'NT$',name:'Taiwan Dollar'},
    {code:'SGD',symbol:'$',name:'Singapore Dollar'},
    {code:'MYR',symbol:'RM',name:'Ringgit'},
    {code:'THB',symbol:'฿',name:'Baht'},
    {code:'IDR',symbol:'Rp',name:'Rupiah'},
    {code:'PHP',symbol:'₱',name:'Piso'},
    {code:'VND',symbol:'₫',name:'Dong'},
    {code:'PKR',symbol:'₨',name:'Pakistani Rupee'},
    {code:'BDT',symbol:'৳',name:'Taka'},
    {code:'LKR',symbol:'රු',name:'Sri Lankan Rupee'},
    {code:'MMK',symbol:'K',name:'Kyat'},
    {code:'NGN',symbol:'₦',name:'Naira'},
    {code:'BMD',symbol:'$',name:'Bermudian Dollar'}
  ];
  const VALID=new Set(CURRENCIES.map(c=>c.code));
  const TTL=300000;
  let currency='USD', state={rates:{},as_of:{},source:'',degraded:[],updating:false};
  let doApi=null, lastRequest=0, pending=null;
  const select=()=>document.getElementById('fiatCurrencySelect');
  function locale(){return window.CMI18n?.getLocale?.()||'es-AR'}
  function language(){return window.CMI18n?.getLanguage?.()||'es'}
  function safe(text){return String(text??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
  function init(api){
    doApi=api;
    const el=select();
    if(!el)return;
    el.innerHTML=CURRENCIES.map(c=>`<option value="${c.code}" title="${safe(c.name)}">${c.code}</option>`).join('');
    el.value=currency;
    el.addEventListener('change',async()=>{
      const old=currency,next=el.value;
      if(!VALID.has(next))return;
      currency=next;
      // A currency choice must survive the random loopback port on next launch.
      try{await doApi('/api/settings',{fiat_currency:next});}
      catch(error){currency=old;el.value=old;window.CashMinerFiatError?.(error);}
      updateLive();
      document.dispatchEvent(new CustomEvent('cashminer:fiat-changed'));
    });
  }
  function hydrate(code){if(!VALID.has(code))return;currency=code;const el=select();if(el)el.value=code;updateLive();}
  function refresh(force=false){
    if(!doApi)return Promise.resolve(null);
    const now=Date.now();
    if(pending)return pending;
    if(!force && now-lastRequest < (Object.keys(state.rates).length ? 30000 : 5000))return Promise.resolve(state);
    lastRequest=now;
    pending=doApi('/api/fiat/rates').then(r=>{
      if(r&&r.rates&&r.as_of){state=r;updateLive();document.dispatchEvent(new CustomEvent('cashminer:fiat-updated'));}
      return state;
    }).catch(()=>state).finally(()=>{pending=null});
    return pending;
  }
  function details(sats){
    if(sats===null||sats===undefined||sats==='')return null;
    const raw=state.rates?.[currency];const rate=Number(raw);
    if(!Number.isFinite(rate)||rate<=0)return {text:'≈ — '+currency,stale:false,info:'',degraded:false};
    let bch;
    try{
      const n=typeof sats==='bigint'?sats:BigInt(String(sats));
      bch=Number(n/100000000n)+Number(n%100000000n)/100000000;
    }catch{return null;}
    const amount=bch*rate;
    if(!Number.isFinite(amount))return null;
    let decimals=2;
    try{decimals=new Intl.NumberFormat(locale(),{style:'currency',currency}).resolvedOptions().maximumFractionDigits}
    catch{return null;}
    if(Math.abs(amount)>0&&Math.abs(amount)<Math.pow(10,-decimals)){
      decimals=Math.min(8,1-Math.floor(Math.log10(Math.abs(amount))));
    }
    const formatter=new Intl.NumberFormat(locale(),{style:'currency',currency,currencyDisplay:'narrowSymbol',minimumFractionDigits:decimals,maximumFractionDigits:decimals});
    const parts=formatter.formatToParts(amount);
    let value=parts.map(p=>p.value).join('');
    if(!parts.some(p=>p.type==='currency'&&p.value===currency))value+=' '+currency;
    const at=Number(state.as_of?.[currency])||0;
    const age=at?Math.max(0,Date.now()-at):Infinity;
    const stale=age>TTL;
    const ageText=age<3600000?Math.max(1,Math.floor(age/60000))+'m':age<86400000?Math.floor(age/3600000)+'h':Math.floor(age/86400000)+'d';
    const time=at?new Date(at).toLocaleString(locale()):'—';
    const info=(language()==='es'?'Cotización':'Rate')+' · '+(state.source||'—')+' · '+time;
    const degraded=(state.degraded||[]).includes(currency);
    return {text:'≈ '+value,stale,ageText,info,degraded};
  }
  function html(sats,network,cl=''){
    if(network!=='mainnet')return '';
    const v=details(sats);
    if(!v)return '';
    if(cl==='compact'&&v.text.startsWith('≈ —'))return '';
    const note=v.stale?` <span class="fiat-age" tabindex="0" aria-label="${safe(v.info)}" title="${safe(v.info)}">◷ ${safe(v.ageText)}</span>`:'';
    const degraded=v.degraded?' <span class="fiat-degraded" title="'+safe(language()==='es'?'Cotización aproximada: fuente alternativa':'Approximate rate: fallback source')+'">*</span>':'';
    return `<span class="fiat-estimate ${safe(cl)}" data-fiat-sats="${safe(String(sats))}">${safe(v.text)}${note}${degraded}</span>`;
  }
  function updateLive(){
    document.querySelectorAll('.fiat-live[data-fiat-sats]').forEach(el=>{
      const sats=el.dataset.fiatSats;
      const net=el.dataset.fiatNetwork;
      el.innerHTML=html(sats,net)||'';
      el.hidden=net!=='mainnet';
    });
  }
  function inputToSats(input){
    if(String(input).trim().toUpperCase()==='MAX'||!String(input).trim())return null;
    try{
      const normalized=window.CMI18n.normalizeInput(input);
      if(!/^\d+(?:\.\d{1,8})?$/.test(normalized))return null;
      const [whole,frac='']=normalized.split('.');
      return (BigInt(whole)*100000000n+BigInt(frac.padEnd(8,'0'))).toString();
    }catch{return null;}
  }
  function getCurrency(){return currency}
  function getQuote(){
    const rate=Number(state.rates?.[currency]);
    const asOf=Number(state.as_of?.[currency]);
    if(!Number.isFinite(rate)||rate<=0||!Number.isFinite(asOf)||asOf<=0)return null;
    return Object.freeze({currency,rate,asOf,source:String(state.source||'')});
  }
  function quoteAge(quote){
    if(!quote)return {stale:true,text:'—',info:''};
    const age=Math.max(0,Date.now()-quote.asOf);
    const text=age<3600000?Math.max(1,Math.floor(age/60000))+'m':age<86400000?Math.floor(age/3600000)+'h':Math.floor(age/86400000)+'d';
    const info=(language()==='es'?'Cotización':'Rate')+' · '+(quote.source||'—')+' · '+new Date(quote.asOf).toLocaleString(locale());
    return {stale:age>TTL,text,info};
  }
  // Exact integer decimal arithmetic, including providers returning scientific notation.
  // Neither the amount nor the quote is converted through binary floating-point math.
  function rational(value){
    const str=String(value);
    const m=/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(str);
    if(!m||str.length>80)throw Error('Invalid decimal value');
    const exp=Number(m[3]||0);if(!Number.isInteger(exp)||Math.abs(exp)>40)throw Error('Invalid exponent');
    const frac=m[2]||'',scale=frac.length-exp;
    const num=BigInt(m[1]+frac);
    return scale>=0?{num,den:10n**BigInt(scale)}:{num:num*10n**BigInt(-scale),den:1n};
  }
  function satsToBch(sats){
    const n=BigInt(String(sats));if(n<0n)throw Error('Invalid sats');
    const fraction=(n%100000000n).toString().padStart(8,'0').replace(/0+$/,'');
    return String(n/100000000n)+(fraction?'.'+fraction:'');
  }
  function fiatToSats(input,quote){
    if(!quote||!quote.rate||quote.rate<=0)return null;
    const normalized=window.CMI18n.normalizeInput(input);
    if(!/^\d{1,24}(?:\.\d{1,12})?$/.test(normalized))return null;
    const fiat=rational(normalized),rate=rational(quote.rate);
    if(fiat.num<=0n||rate.num<=0n)return null;
    const numerator=fiat.num*rate.den*100000000n;
    const denominator=fiat.den*rate.num;
    const sats=(numerator*2n+denominator)/(2n*denominator);
    if(sats<=0n||sats>2100000000000000n)return null;
    return sats.toString();
  }
  function fiatFromSats(sats,quote){
    if(!quote||!quote.rate)return '';
    const n=BigInt(String(sats)),rate=rational(quote.rate);
    const precision=8n, scale=10n**precision;
    const fiat=(n*rate.num*scale*2n+rate.den*100000000n)/(rate.den*100000000n*2n);
    let dec=(fiat%scale).toString().padStart(Number(precision),'0').replace(/0+$/,'');
    return String(fiat/scale)+(dec?(locale()==='es-AR'?',':'.')+dec:'');
  }
  window.CMFiat={CURRENCIES,init,hydrate,refresh,details,html,updateLive,inputToSats,getCurrency,getQuote,quoteAge,fiatToSats,fiatFromSats,satsToBch};
})();
