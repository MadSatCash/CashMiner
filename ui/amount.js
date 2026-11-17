/* CashMiner: exact, locale-aware amount editing. Grouping is presentation only. */
(function(){
  'use strict';
  function separators(locale){return locale==='es-AR'?{decimal:',',group:'.'}:{decimal:'.',group:','}}
  function parse(value,locale,precision=8,strict=false){
    const {decimal,group}=separators(locale),text=String(value).trim();
    if(!text)return {whole:'',fraction:'',decimal:false,normalized:'',text:''};
    if(text.length>128||[...text].some(c=>!('0123456789'+decimal+group).includes(c)))throw Error('format');
    const parts=text.split(decimal);
    if(parts.length>2)throw Error('format');
    let whole=parts[0],fraction=parts[1]||'';
    if(fraction.includes(group))throw Error('format');
    if(strict&&whole.includes(group)){
      const groups=whole.split(group);
      if(!/^\d{1,3}$/.test(groups[0])||groups.slice(1).some(g=>!/^\d{3}$/.test(g)))throw Error('format');
    }
    whole=whole.split(group).join('');
    if(!whole&&!fraction&&parts.length===1)throw Error('format');
    if(fraction.length>precision)throw Error('precision');
    whole=whole||'0';
    const hasDecimal=parts.length===2;
    return {whole,fraction,decimal:hasDecimal,
      normalized:whole+(fraction?'.'+fraction:''),
      text:whole.replace(/\B(?=(\d{3})+(?!\d))/g,group)+(hasDecimal?decimal+fraction:'')};
  }
  function present(parts,locale){
    if(!parts.whole)return '';
    const {decimal,group}=separators(locale);
    return parts.whole.replace(/\B(?=(\d{3})+(?!\d))/g,group)+(parts.decimal?decimal+parts.fraction:'');
  }
  function caretAt(text,count,group){
    if(count<=0)return 0;
    let seen=0;
    for(let i=0;i<text.length;i++)if(text[i]!==group&&++seen===count)return i+1;
    return text.length;
  }
  function bind(input,{getLocale,getPrecision=()=>8,onChange=()=>{},onError=()=>{}}){
    let locale=getLocale(),saved={value:input.value,start:0,end:0},composing=false;
    function remember(){saved={value:input.value,start:input.selectionStart??0,end:input.selectionEnd??0}}
    function restore(){input.value=saved.value;input.setSelectionRange(saved.start,saved.end)}
    function format(raw,start,end,strict=false){
      const {group,decimal}=separators(locale),parts=parse(raw,locale,getPrecision(),strict);
      const count=pos=>[...raw.slice(0,pos)].filter(c=>c!==group).length;
      const leading=raw.startsWith(decimal)?1:0;
      input.value=parts.text;
      input.setSelectionRange(caretAt(parts.text,count(start)+leading,group),caretAt(parts.text,count(end)+leading,group));
      remember();return parts;
    }
    function accepted(){onError('');onChange()}
    function rejected(error){restore();onError(error.message)}
    input.addEventListener('beforeinput',event=>{
      if(composing||event.isComposing)return;
      remember();
      // Deleting a generated separator consumes the adjacent digit too.
      const {group}=separators(locale),pos=saved.start;
      if(pos!==saved.end)return;
      let start,end;
      if(event.inputType==='deleteContentBackward'&&pos>0&&input.value[pos-1]===group){start=pos-2;end=pos}
      if(event.inputType==='deleteContentForward'&&input.value[pos]===group){start=pos;end=pos+2}
      if(start===undefined)return;
      event.preventDefault();
      try{format(input.value.slice(0,start)+input.value.slice(end),start,start);accepted()}
      catch(error){rejected(error)}
    });
    input.addEventListener('input',event=>{
      if(composing||event.isComposing)return;
      try{format(input.value,input.selectionStart??input.value.length,input.selectionEnd??input.value.length);accepted()}
      catch(error){rejected(error)}
    });
    input.addEventListener('paste',event=>{
      if(!event.clipboardData)return;
      event.preventDefault();remember();
      const text=event.clipboardData.getData('text').trim();
      try{
        parse(text,locale,getPrecision(),true);
        const raw=input.value.slice(0,saved.start)+text+input.value.slice(saved.end);
        format(raw,saved.start+text.length,saved.start+text.length);accepted();
      }catch(error){rejected(error)}
    });
    input.addEventListener('compositionstart',()=>{remember();composing=true});
    input.addEventListener('compositionend',()=>{
      composing=false;
      try{format(input.value,input.selectionStart??0,input.selectionEnd??0);accepted()}
      catch(error){rejected(error)}
    });
    function sync(){
      const next=getLocale();
      if(input.value.trim().toUpperCase()==='MAX'){locale=next;remember();return}
      const parts=parse(input.value,locale,getPrecision());
      if(next!==locale){
        const oldGroup=separators(locale).group;
        const start=[...input.value.slice(0,input.selectionStart??0)].filter(c=>c!==oldGroup).length;
        const end=[...input.value.slice(0,input.selectionEnd??0)].filter(c=>c!==oldGroup).length;
        input.value=present(parts,next);locale=next;
        const group=separators(locale).group;
        input.setSelectionRange(caretAt(input.value,start,group),caretAt(input.value,end,group));
      }else if(input.value!==parts.text)format(input.value,input.selectionStart??0,input.selectionEnd??0);
      remember();
    }
    function reset(){locale=getLocale();sync();onError('')}
    function normalized(){sync();return parse(input.value,locale,getPrecision()).normalized}
    remember();
    return {sync,reset,normalized};
  }
  const api={parse,present,bind};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CMAmount=api;
})();
