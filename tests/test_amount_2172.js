const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parse,bind}=require('../ui/amount.js');

class Input{
  constructor(value=''){this.value=value;this.selectionStart=value.length;this.selectionEnd=value.length;this.listeners={}}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn)}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end}
  emit(type,extra={}){const e={preventDefault(){this.defaultPrevented=true},...extra};for(const fn of this.listeners[type]||[])fn(e);return e}
  insert(text){
    const e=this.emit('beforeinput',{inputType:'insertText',data:text});
    if(e.defaultPrevented)return;
    const p=this.selectionStart;
    this.value=this.value.slice(0,p)+text+this.value.slice(this.selectionEnd);
    this.setSelectionRange(p+text.length,p+text.length);this.emit('input');
  }
  paste(text){this.emit('paste',{clipboardData:{getData:()=>text}})}
  delete(backward=true){
    const e=this.emit('beforeinput',{inputType:backward?'deleteContentBackward':'deleteContentForward'});
    if(e.defaultPrevented)return;
    let a=this.selectionStart,b=this.selectionEnd;
    if(a===b){if(backward)a=Math.max(0,a-1);else b++}
    this.value=this.value.slice(0,a)+this.value.slice(b);this.setSelectionRange(a,a);this.emit('input');
  }
}
function fixture(locale='en-US',precision=8){
  const input=new Input(),state={locale,error:'',changes:0,precision};
  const editor=bind(input,{getLocale:()=>state.locale,getPrecision:()=>state.precision,
    onError:e=>state.error=e,onChange:()=>state.changes++});
  return {input,state,editor};
}
test('clipboard separators follow the active format without guessing',()=>{
  for(const [locale,text,expected] of [
    ['es-AR','1.234','1234'],['en-US','1.234','1.234'],
    ['es-AR','1,234','1.234'],['en-US','1,234','1234'],
    ['es-AR','1.234.567,12345678','1234567.12345678'],
    ['en-US','1,234,567.12345678','1234567.12345678']]){
    const {input,editor,state}=fixture(locale);input.paste(text);
    assert.equal(state.error,'');assert.equal(editor.normalized(),expected);
  }
});
test('grouping appears while typing and selection remains by the inserted digit',()=>{
  for(const [locale,expected] of [['es-AR','1.234.567'],['en-US','1,234,567']]){
    const {input,editor}=fixture(locale);for(const c of '1234567')input.insert(c);
    assert.equal(input.value,expected);assert.equal(input.selectionStart,9);
    input.setSelectionRange(3,3);input.insert('9');
    assert.equal(editor.normalized(),'12934567');assert.equal(input.selectionStart,4);
  }
});
test('ninth decimal is rejected including zero; a rejected paste keeps value and selection',()=>{
  const {input,editor,state}=fixture();input.paste('1.12345678');input.insert('0');
  assert.equal(input.value,'1.12345678');assert.equal(state.error,'precision');
  input.setSelectionRange(0,input.value.length);input.paste('2.000000000');
  assert.equal(editor.normalized(),'1.12345678');assert.equal(state.error,'precision');
  assert.equal(input.selectionStart,0);assert.equal(input.selectionEnd,10);
  input.paste('2.00000000');assert.equal(state.error,'');assert.equal(editor.normalized(),'2.00000000');
});
test('malformed clipboard grouping, signs, scientific notation and mixed decimals are rejected',()=>{
  for(const text of ['1,23','1,234.5,6','1.2.3','-1','1e3','Infinity','<img>','12 345']){
    const {input,state}=fixture();input.paste('50');input.setSelectionRange(0,2);input.paste(text);
    assert.equal(input.value,'50',text);assert.equal(state.error,'format',text);
  }
});
test('partial decimal and trailing zeroes survive typing and locale changes exactly',()=>{
  const {input,editor,state}=fixture('es-AR');input.paste('1234,00');
  state.locale='en-US';editor.sync();assert.equal(input.value,'1,234.00');
  assert.equal(editor.normalized(),'1234.00');
  input.setSelectionRange(0,input.value.length);input.paste('0.');assert.equal(input.value,'0.');
  input.insert('0');input.insert('1');assert.equal(editor.normalized(),'0.01');
  state.locale='es-AR';editor.sync();assert.equal(input.value,'0,01');
});
test('deleting across automatic separators removes digits rather than getting stuck',()=>{
  const {input,editor}=fixture();input.paste('1234');input.setSelectionRange(2,2);input.delete();
  assert.equal(input.value,'234');assert.equal(input.selectionStart,0);
  input.setSelectionRange(0,3);input.paste('1234');input.setSelectionRange(1,1);input.delete(false);
  assert.equal(editor.normalized(),'134');assert.equal(input.selectionStart,1);
});
test('editing a selection and leading decimal preserves the intended amount',()=>{
  const {input,editor}=fixture('es-AR');input.insert(',');input.insert('5');
  assert.equal(input.value,'0,5');assert.equal(input.selectionStart,3);
  input.setSelectionRange(0,3);input.paste('1234567,12345678');
  input.setSelectionRange(2,5);input.insert('9');
  assert.equal(editor.normalized(),'19567.12345678');
});
test('MAX and programmatic resets do not leave a stale edit snapshot',()=>{
  const {input,editor,state}=fixture();input.value='MAX';editor.reset();
  state.locale='es-AR';editor.sync();assert.equal(input.value,'MAX');
  input.value='';editor.reset();input.insert('1');assert.equal(editor.normalized(),'1');
  input.setSelectionRange(0,1);input.paste('3,123456789');assert.equal(input.value,'1');
});
test('fiat retains its existing twelve-decimal precision',()=>{
  const {input,editor,state}=fixture('en-US',12);input.paste('1234.123456789012');
  assert.equal(editor.normalized(),'1234.123456789012');assert.equal(state.error,'');
  input.insert('3');assert.equal(state.error,'precision');
});
test('the formatter retains exact satoshi-scale digits near the supply limit',()=>{
  assert.equal(parse('20.999.999,99999999','es-AR',8,true).normalized,'20999999.99999999');
  assert.throws(()=>parse('1.000000000','en-US',8,true),/precision/);
});
