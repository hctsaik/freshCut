const p=require('puppeteer-core');const O='/workspace/insta-editor/review/v4/r4/';const U='file:///workspace/insta-editor/mockup.html';
const R={};const S=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const b=await p.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});const errs=[];
async function fresh(w=1440,pf){const pg=await b.newPage();pg.on('pageerror',e=>errs.push(e.message));await pg.setViewport({width:w,height:900});await pg.goto(U);await pg.evaluate(()=>show('main'));if(pf)await pg.evaluate(p=>setPf(p),pf);return pg}
const A=pg=>pg.evaluate(()=>{const a=document.activeElement;return {id:a.id,txt:(a.getAttribute('aria-label')||a.textContent||a.value||'').trim().slice(0,24),vis:!!a.offsetParent,dlg:document.querySelector('.modal.on')?.id||null,mode:document.querySelector('.modal.on')?.dataset.mode,scr:document.querySelector('.screen.on')?.id}});
const vis=(pg,s)=>pg.evaluate(s=>{const e=document.querySelector(s);return !!e&&e.getClientRects().length>0&&getComputedStyle(e).display!='none'},s);
const tabPath=async(pg,from,to,max=80)=>{await pg.focus(from);const path=[];for(let i=0;i<max;i++){await pg.keyboard.press('Tab');const a=await A(pg);path.push(a.id||a.txt);if(a.id==to)return path}return path};
let pg=await fresh();
// R1 info mode
await pg.evaluate(()=>{toggleAI(true);keyOK=true;demoAI('idle')});await pg.click('#aiNote .lnk');await S(60);R.R1_open=await A(pg);R.R1_btns=await pg.evaluate(()=>$$('#dConsent button,#dConsent a').filter(x=>x.offsetParent).map(x=>x.textContent.trim()));await pg.screenshot({path:O+'01_info_mode_1440.png'});
await pg.keyboard.press('Escape');await S(50);R.R1_esc=[await A(pg),await pg.evaluate(()=>aiOn)];
await pg.click('#aiNote .lnk');await pg.keyboard.press('Enter');await S(50);R.R1_enter=[await A(pg),await pg.evaluate(()=>aiOn)];
// then consent mode still works after info (mode reset)?
await pg.evaluate(()=>{toggleAI(false);openDlg('dSet');$$('#tabs [role=tab]')[4].click()});await pg.click('#s14');await S(50);R.R1_consentAfterInfo=[await A(pg),await pg.evaluate(()=>$$('#dConsent button').filter(x=>x.offsetParent).map(x=>x.textContent.trim()))];
await pg.keyboard.press('Escape');R.R1_consentEsc=[await A(pg),await pg.evaluate(()=>aiOn)];
await pg.evaluate(()=>{closeDlg();toggleAI(true);keyOK=true;renderAI()});await pg.click('#aiNote .lnk');
const off=await pg.evaluateHandle(()=>$$('#dConsent button,#dConsent a').find(x=>x.offsetParent&&/在設定中關閉/.test(x.textContent)));if(off.asElement()){await off.asElement().click();await S(50);R.R1_offLink=[await A(pg),await pg.evaluate(()=>[aiOn,$('#s14').checked])]}
await pg.close();
// F3 states
pg=await fresh();for(const st of ['idle','run','done','key','quota','off']){await pg.evaluate(s=>demoAI(s),st);await S(60);
R['F3_'+st]=await pg.evaluate(()=>({all:$('#aiAll').getClientRects().length>0,q:$('#aiq').disabled,go:$('#aiGo').disabled,note:$('#aiNote').innerText.replace(/\n/g,' '),err:$('#aiErr').innerText.replace(/\n/g,' '),tags:$$('.aim').length}));await pg.screenshot({path:O+`02_ai_${st}_1440.png`})}
// key state fixed via testKey
await pg.evaluate(()=>demoAI('key'));R.F3_keyOK=await pg.evaluate(()=>keyOK);await pg.close();
// R2
pg=await fresh();R.R2_at30=await vis(pg,'#custRow');R.R2_hiddenVisible=await pg.evaluate(()=>$$('[hidden]').filter(x=>x.getClientRects().length).map(x=>x.id||x.className));
await pg.select('#target','-1');R.R2_custom=await vis(pg,'#custRow');
const setv=async v=>{await pg.click('#tcust',{clickCount:3});await pg.keyboard.press('Backspace');if(v!=='')await pg.type('#tcust',String(v));await S(30);return pg.evaluate(()=>({inv:$('#tcust').getAttribute('aria-invalid'),err:$('#custErr').getClientRects().length?$('#custErr').innerText:null,sum:$('#sum').innerText.replace(/\n/g,' '),bc:getComputedStyle($('#tcust')).borderColor}))};
R.R2_8=await setv(8);R.R2_3=await setv(3);await pg.screenshot({path:O+'03_custom_invalid_1440.png'});R.R2_empty=await setv('');R.R2_700=await setv(700);R.R2_601=await setv(601);R.R2_ok=await setv(45);
R.R2_live=await pg.evaluate(()=>[$('#custErr').getAttribute('role'),$('#custErr').getAttribute('aria-live'),$('#tcust').getAttribute('aria-describedby')]);
await pg.select('#target','30');R.R2_back30=[await vis(pg,'#custRow'),await vis(pg,'#custErr')];
// invalid then switch to 30 -> err hidden?
await pg.select('#target','-1');await setv(2);await pg.select('#target','30');R.R2_invThen30=[await vis(pg,'#custRow'),await vis(pg,'#custErr'),await pg.evaluate(()=>$('#sum').innerText)];
await pg.close();
// R3
pg=await fresh(1440,'win');await pg.evaluate(()=>demoPerm());await S(60);R.R3=await pg.evaluate(()=>{const g=()=>{const c=getComputedStyle($('#permGo'));return [$('#permGo').disabled,c.color,c.borderColor,c.backgroundColor,c.cursor]};const a=g();$('#permOk').click();const b=g();return [a,b]});
R.S2=await pg.evaluate(()=>[$('#permMsg').innerText,$$('#dPerm button').filter(x=>x.offsetParent).map(x=>x.textContent.trim())]);
await pg.evaluate(()=>{$('#permOk').click()});await pg.screenshot({path:O+'04_perm_disabled_win_1440.png'});
const tb=[];for(let i=0;i<5;i++){await pg.keyboard.press('Tab');tb.push((await A(pg)).txt)}R.R3_tab=tb;
const sk=await pg.evaluateHandle(()=>$$('#dPerm button').find(x=>/略過/.test(x.textContent)));if(sk.asElement()){await sk.asElement().click();await S(60);R.S2_skip=[await pg.evaluate(()=>$('#toast').innerText.replace(/\n/g,' ')),await pg.evaluate(()=>removed)]}
await pg.keyboard.down('Control');await pg.keyboard.press('z');await pg.keyboard.up('Control');await S(50);R.S4=await pg.evaluate(()=>[$('#toast').classList.contains('on')?$('#toast').innerText.replace(/\n/g,' '):null,removed]);
await pg.close();
// R4 windows
pg=await fresh(1440,'win');await pg.evaluate(()=>openDlg('dSet'));R.R4_btns=await pg.evaluate(()=>$$('#dSet .actions button,#dSet button').filter(x=>x.offsetParent).map(x=>x.textContent.trim()+(x.disabled?'(dis)':'')).slice(-4));
const s3=await pg.evaluate(()=>[$('#s3').checked,$('label[for=s3]')?.textContent||$('#s3').closest('label')?.textContent]);R.R4_s3=s3;
await pg.click('#s3');R.R4_dirty=await pg.evaluate(()=>[$('#setDirty').innerText,$('#setApply').disabled,document.body.className]);
await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='取消'&&b.offsetParent).click());await pg.evaluate(()=>openDlg('dSet'));R.R4_cancel=await pg.evaluate(()=>[$('#s3').checked,document.body.className]);
// change select (s9?) and slider; Esc
const ctl=await pg.evaluate(()=>$$('#dSet select').map(x=>x.id));R.R4_selects=ctl;
await pg.evaluate(()=>{const s=$('#s8');s.selectedIndex=(s.selectedIndex+1)%s.options.length;s.dispatchEvent(new Event('change',{bubbles:true}));window._sid=s.id;window._sv=s.value});R.R4_selDirty=await pg.evaluate(()=>$('#setDirty').innerText);
await pg.keyboard.press('Escape');await pg.evaluate(()=>openDlg('dSet'));R.R4_escRevertSel=await pg.evaluate(()=>[document.getElementById(window._sid).value,window._sv]);
// consent staged then cancel
await pg.evaluate(()=>$$('#tabs [role=tab]')[4].click());await pg.click('#s14');await pg.evaluate(()=>[...$$('#dConsent button')].find(b=>b.textContent.includes('我了解')).click());R.R4_staged=await pg.evaluate(()=>[aiOn,$('#s14').checked,$('#setDirty').innerText]);
await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='取消'&&b.offsetParent).click());R.R4_cancelAI=await pg.evaluate(()=>[aiOn,$('#aiwrap').getClientRects().length>0]);
// consent + apply + cancel
await pg.evaluate(()=>{openDlg('dSet');$$('#tabs [role=tab]')[4].click()});await pg.click('#s14');await pg.evaluate(()=>[...$$('#dConsent button')].find(b=>b.textContent.includes('我了解')).click());
await pg.click('#setApply');R.R4_apply=await pg.evaluate(()=>[aiOn,$('#setApply').disabled,$('#setDirty').innerText]);await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='取消'&&b.offsetParent).click());R.R4_cancelAfterApply=await pg.evaluate(()=>aiOn);
// key: test key in win then cancel -> keyOK revert? delete key then cancel
await pg.evaluate(()=>{openDlg('dSet');$$('#tabs [role=tab]')[4].click()});await pg.type('#s16','abcdefghij');await pg.click('#keyTest');R.R4_keyTested=await pg.evaluate(()=>[keyOK,$('#aiq').disabled]);
await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='取消'&&b.offsetParent).click());R.R4_keyAfterCancel=await pg.evaluate(()=>[keyOK,$('#s16').value,$('#aiq').disabled]);
// delete key then cancel -> is key restored? (real keychain deletion is irreversible)
await pg.evaluate(()=>{keyOK=true;openDlg('dSet');$$('#tabs [role=tab]')[4].click()});await pg.evaluate(()=>[...$$('#dSet button')].find(b=>/刪除已儲存/.test(b.textContent)).click());R.R4_delKey=await pg.evaluate(()=>[keyOK,$('#keySt').innerText]);
await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='取消'&&b.offsetParent).click());R.R4_delKeyCancel=await pg.evaluate(()=>[keyOK,$('#s16').value]);
// dirty + close via X? check OK button
await pg.evaluate(()=>{openDlg('dSet');$('#s3').click()});await pg.evaluate(()=>[...$$('#dSet button')].find(b=>b.textContent.trim()=='確定'&&b.offsetParent).click());await pg.evaluate(()=>openDlg('dSet'));R.R4_ok=await pg.evaluate(()=>[$('#s3').checked,document.body.className]);
await pg.screenshot({path:O+'05_settings_win_1440.png'});
await pg.close();
// mac immediate
pg=await fresh(1440,'mac');await pg.evaluate(()=>{openDlg('dSet');$$('#tabs [role=tab]')[0].click()});await pg.click('#s3');await pg.keyboard.press('Escape');await pg.evaluate(()=>openDlg('dSet'));R.R4_mac=await pg.evaluate(()=>[$('#s3').checked,document.body.className,$$('#dSet button').filter(x=>x.offsetParent).map(x=>x.textContent.trim()).slice(-2)]);await pg.close();
// S1 tab counts
pg=await fresh();R.S1_path=await tabPath(pg,'#q','go');R.S1_n=R.S1_path.length;
await pg.evaluate(()=>$('#watchBanner')?.querySelector('button').click());R.S1_nNoBanner=(await tabPath(pg,'#q','go')).length;
// from top of app (first focusable) to go
await pg.evaluate(()=>document.activeElement.blur());const p2=[];await pg.evaluate(()=>{window.scrollTo(0,0)});
// shortcut
await pg.focus('#q');await pg.keyboard.down('Alt');await pg.keyboard.down('Meta');await pg.keyboard.press('KeyT');await pg.keyboard.up('Meta');await pg.keyboard.up('Alt');R.S1_skip=await A(pg);
R.S1_discover=await pg.evaluate(()=>{const t=[...document.querySelectorAll('[title],[aria-keyshortcuts],[aria-describedby]')].map(x=>(x.title||'')+'|'+(x.getAttribute('aria-keyshortcuts')||'')).filter(s=>/T/.test(s));return [t,$('#skipKeys').getAttribute('aria-hidden'),$('#skipKeys').textContent,$('#go').title]});
// wall roving
await pg.focus('#q');let a;for(let i=0;i<20;i++){await pg.keyboard.press('Tab');a=await A(pg);if(a.id&&a.id.startsWith('c'))break}R.S1_wallEntry=a;
await pg.keyboard.press('ArrowRight');await pg.keyboard.press('ArrowRight');const mid=await A(pg);await pg.keyboard.press('Tab');const after=await A(pg);await pg.keyboard.down('Shift');await pg.keyboard.press('Tab');await pg.keyboard.up('Shift');R.S1_remember=[mid.id,after.id||after.txt,(await A(pg)).id];
await pg.keyboard.press('Space');R.S1_space=[await pg.evaluate(()=>document.activeElement.getAttribute('aria-checked')),(await A(pg)).id];
await pg.keyboard.press('Home');R.S1_home=await A(pg);await pg.keyboard.press('ArrowDown');R.S1_homeDown=await A(pg);
// Enter on header? arrow from header right
await pg.keyboard.press('ArrowRight');R.S1_hdrRight=await A(pg);
// trim reachable (微調 removed from tab): Enter on chk
await pg.focus('#c1_1');await pg.keyboard.press('Enter');R.S1_enterTrim=(await A(pg)).scr;
R.wallStops=await pg.evaluate(()=>{show('main');return $$('#wall button').filter(b=>b.tabIndex>=0&&b.offsetParent).length});
R.wallHint=await pg.evaluate(()=>[$('#wallHint').className,getComputedStyle($('#wallHint')).position,$('#wall').getAttribute('aria-describedby')||$('#wall').getAttribute('role')]);
// clicking a chk with mouse then Tab away/back
await pg.click('#c2_2');await pg.keyboard.press('Tab');await pg.keyboard.down('Shift');await pg.keyboard.press('Tab');await pg.keyboard.up('Shift');R.S1_clickRemember=(await A(pg)).id;
// collapse a group then roving
await pg.evaluate(()=>tg(1));await pg.focus('#q');for(let i=0;i<20;i++){await pg.keyboard.press('Tab');a=await A(pg);if(a.id&&a.id.startsWith('c')||/VID|LRV/.test(a.txt))break}R.S1_afterCollapse=a;
await pg.close();
// S3 I/O
pg=await fresh();await pg.evaluate(()=>show('trim'));R.S3=await pg.evaluate(()=>{const t0=[tIn,tOut];document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'i',bubbles:true}));const t1=[tIn,tOut];document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'o',bubbles:true}));return [t0,t1,[tIn,tOut],$$('[aria-live]').map(x=>x.innerText).filter(Boolean).slice(0,3)]});
await pg.keyboard.press('i');R.S3_real=await pg.evaluate(()=>[tIn,tOut]);
// typing 'i' in tin input should not trigger
await pg.focus('#tin');await pg.keyboard.press('o');R.S3_inInput=await pg.evaluate(()=>[tIn,tOut,$('#tin').value]);
await pg.close();
// O1, O2, O3, drawer
pg=await fresh(1024);await pg.focus('.rail button');await pg.keyboard.press('Enter');await S(60);await pg.mouse.click(300,500);await S(60);R.O1=[await pg.evaluate(()=>$('#right').classList.contains('open')),await A(pg)];
await pg.close();
pg=await fresh();await pg.evaluate(()=>{vsel=new Set([1]);openDlg('dDelete')});await pg.evaluate(()=>$('#toTrash').click());R.O2_before=await pg.evaluate(()=>$('#trFiles').innerText.replace(/\n/g,' '));await pg.click('#pvOnly');R.O2_after=await pg.evaluate(()=>[$('#trFiles').innerText.replace(/\n/g,' '),$('#hTr').innerText,$$('#dTrash button').filter(x=>x.offsetParent).map(x=>x.textContent.trim())]);
await pg.screenshot({path:O+'06_previews_only_1440.png'});
await pg.evaluate(()=>[...$$('#dTrash button')].find(b=>b.className.includes('danger')).click());await S(50);R.O2_toast=await pg.evaluate(()=>[$('#toast').innerText.replace(/\n/g,' '),removed]);
R.O3=await pg.evaluate(()=>$$('#vlist .vid').map(x=>[x.querySelector('.nm')?.innerText.replace(/\n/g,' '),x.getAttribute('aria-label')]).slice(0,3));
await pg.close();
// N3/N4/N5 regression quick
pg=await fresh();const mod='Meta';await pg.focus('#c1_0');await pg.keyboard.down(mod);await pg.keyboard.press('Enter');await pg.keyboard.up(mod);R.reg_N3=(await A(pg)).dlg;await pg.close();
pg=await fresh();await pg.evaluate(()=>reqAI(true));R.reg_consent=await A(pg);await pg.close();
// sweep
const dl=['dResume','dImport','dDelete','dTrash','dPerm','dConsent','dDisk','dProg','dCancel','dDone','dErr','dSet'];
for(const w of [1440,1024])for(const pf of ['mac','win']){pg=await fresh(w,pf);for(const s of ['welcome','main','trim']){await pg.evaluate(x=>show(x),s);await pg.screenshot({path:O+`s_${s}_${pf}_${w}.png`})}
await pg.evaluate(()=>show('main'));R['hs_'+pf+w]=await pg.evaluate(()=>document.documentElement.scrollWidth);R['hid_'+pf+w]=await pg.evaluate(()=>$$('[hidden]').filter(x=>x.getClientRects().length).map(x=>x.id||x.className));
for(const d of dl){await pg.evaluate(x=>{closeDlg();openDlg(x)},d);await S(30);await pg.screenshot({path:O+`d_${d}_${pf}_${w}.png`})}await pg.close()}
R.errs=errs;require('fs').writeFileSync(O+'results.json',JSON.stringify(R,null,1));console.log(JSON.stringify(R));await b.close()})().catch(e=>{console.log('FAIL',e.stack,JSON.stringify(R));process.exit(1)});
