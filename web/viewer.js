/* System One Arena viewer.

   Draws frames in the shape arena/engine/sim.py streams. Three sources feed it:
     live    (default)    frames over SSE from /api/stream; the service runs the match
     replay  (?replay=id) a recorded match's frames, played back on their own clock
     demo    (?demo)      demo-sim.js runs the engine in the browser; no model is called
   Nothing here changes a match except the Start buttons, which need the admin token
   when one is set. Art: Tiny Swords (CC0) by Pixel Frog, in web/tinyswords. */
(function(){
'use strict';
const W=18,H=28,RIVER=14,LANES=[4,14];
const $=id=>document.getElementById(id);
const QS=new URLSearchParams(location.search);
const MODE=(window.ARENA_DEMO||QS.has('demo'))?'demo':QS.get('replay')?'replay':'live';
const ADMIN=QS.get('admin'),AUTH=ADMIN?{Authorization:'Bearer '+ADMIN}:{};
// The start banner holds over a frozen board for BANNER_HOLD seconds, then the clock starts. Live, the server's
// pre-roll (MATCH_PREROLL_SECONDS) freezes the board; in replays and the demo the viewer holds the first frame.
// Start banner: 0-2s over a frozen board (the pre-roll), the match starts at 2s underneath it, and it fades out
// from 3.6s to 4s, when the clock appears.
const BANNER_HOLD=2,BANNER_OFF=4,INTRO=MODE==='live'?0:BANNER_HOLD,OUTRO_DELAY=1.4;
let bannerStart=-99,bannerWall=0;
let LAT=null;  // each side's average decision time, when known before the match plays (replay, demo)
// ?at=<seconds> starts a demo or replay that far into the match (skipping the start banner); ?pause starts it paused.
const AT=Math.max(0,parseFloat(QS.get('at'))||0);
// ?record (with ?replay or ?demo): only the frame, at 1:1, and time advances only when tools/record.py calls
// window.arenaRecord.step(dt), so every video frame is exactly 1/fps apart.
const RECORD=QS.has('record');
if(RECORD)document.body.classList.add('clean','record');
const ROLES=['Fast decision model','Frontier model'];
let NAMES=['Jev','Sol'],CONFIG=null,MIRROR=false;

/* ---------- 9:16 frame, scaled to fit ---------- */
const frame=$('frame'),holder=$('holder');
function fitFrame(){
  const clean=document.body.classList.contains('clean');
  const vw=innerWidth-(clean?0:32),vh=innerHeight-(clean?0:document.querySelector('.controls').offsetHeight+30);
  const s=Math.max(0.1,Math.min(vw/1080,vh/1920));
  frame.style.transform=`scale(${s})`;holder.style.width=1080*s+'px';holder.style.height=1920*s+'px';
}
addEventListener('resize',fitFrame);

/* ---------- art ---------- */
const ART='static/tinyswords/';
const IMG={};
function img(name){if(!IMG[name]){const i=new Image();i.src=ART+name+'.png';IMG[name]=i}return IMG[name]}
const ready=i=>i.complete&&i.naturalWidth>0;
const TEAM=['blue','red'];
// Each card's sprite sheet: rows by animation, 192px cells; ax/ay is where the feet sit in a cell.
const UNIT={
  warrior: {sheet:'warrior',ax:101,ay:136,scale:1.45,box:[62,45,80,91],idle:[0,6],run:[1,6],atk:{right:[2,6],down:[4,6],up:[6,6]},atkDur:0.45,tall:92},
  // The brute only hits buildings: a pawn at 2.2x that hammers the tower.
  brute:  {sheet:'pawn',ax:96,ay:128,scale:3.0,box:[66,69,60,59],idle:[0,6],run:[1,6],atk:{right:[2,6],down:[2,6],up:[2,6]},atkDur:0.6,tall:59},
  archers:{sheet:'archer',ax:99,ay:134,scale:1.35,box:[66,59,67,75],idle:[0,6],run:[1,6],atk:{right:[4,8],down:[6,8],up:[2,8]},atkDur:0.6,tall:76},
  goblins:  {sheet:'torch',ax:90,ay:133,scale:1.05,box:[51,44,76,89],idle:[0,7],run:[1,6],atk:{right:[2,6],down:[3,6],up:[4,6]},atkDur:0.4,tall:80},
  dynamiter: {sheet:'tnt',ax:100,ay:135,scale:1.25,box:[57,67,88,68],idle:[0,6],run:[1,6],atk:{right:[2,7],down:[2,7],up:[2,7]},atkDur:0.6,tall:68},
};
const CARD_COST={warrior:3,archers:3,brute:5,goblins:2,dynamiter:3};
const FOOT={warrior:0.5,archers:0.4,goblins:0.32,brute:0.75,dynamiter:0.42};
function preload(){for(const t of TEAM)for(const n of['warrior','archer','torch','tnt','pawn','tower','castle'])img(t+'/'+n);
  for(const n of['ruins/tower','ruins/castle','fx/arrow','fx/dynamite','fx/dead','fx/explosion','fx/fire','terrain/water','terrain/foam','terrain/water_rocks','terrain/bridge','decor/tree','decor/sheep','decor/04','decor/05','decor/07','decor/08','decor/09','decor/10','decor/11'])img(n)}
preload();

/* ---------- arena canvas ---------- */
const cv=$('cv');let ctx=cv.getContext('2d'),U=10,P=U/64,OX=0;  // OX: canvas px from the canvas edge to the playfield's left edge   // U: canvas px per board tile; P: canvas px per art px
const land=document.createElement('canvas');
const OL='#1d1a2b',GOLD='#ffcb45',TAU=Math.PI*2;
const TC=[{m:'#3d8bff',d:'#1f5bcc',l:'#a9d0ff'},{m:'#f24a40',d:'#b3261f',l:'#ffb0a8'}];
const DISPLAY='"Lilita One","Arial Rounded MT Bold","Arial Black",sans-serif',MONO='"JetBrains Mono",ui-monospace,Menlo,monospace';
function sizeArena(){
  // The arena keeps the board's 18:28 shape; its height decides the width of the whole board.
  const h=$('field').clientHeight;
  // The board spans the frame edge to edge; the 18x28 playfield sits centred and the strips either side are scenery.
  const fw=$('field').clientWidth;
  cv.style.width=fw+'px';cv.style.height=h+'px';cv.width=fw*2;cv.height=h*2;U=cv.height/H;P=U/64;OX=(cv.width-W*U)/2;paintLand();
}
function rr(x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath()}
function C(x,y,r){ctx.beginPath();ctx.arc(x,y,r,0,TAU)}
function E(x,y,rx,ry){ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,TAU)}
function fs(f,s,lw){ctx.fillStyle=f;ctx.fill();if(s!==0){ctx.strokeStyle=s||OL;ctx.lineWidth=lw||0.13;ctx.stroke()}}
function crown(cx,cy,q){ctx.beginPath();ctx.moveTo(cx-q,cy+q*.7);ctx.lineTo(cx-q,cy-q*.45);ctx.lineTo(cx-q*.45,cy+q*.1);ctx.lineTo(cx,cy-q*.8);ctx.lineTo(cx+q*.45,cy+q*.1);ctx.lineTo(cx+q,cy-q*.45);ctx.lineTo(cx+q,cy+q*.7);ctx.closePath()}
function label(txt,x,y,px,fill,lw,font){ctx.font=`${px}px ${font||DISPLAY}`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineJoin='round';ctx.lineWidth=lw||px*0.28;ctx.strokeStyle=OL;ctx.strokeText(txt,x,y);ctx.fillStyle=fill;ctx.fillText(txt,x,y)}
// One cell of a sheet, feet (ax, ay) at canvas (x, y). k scales on top of P.
function cell(im,cw,ch,col,row,ax,ay,x,y,k,flip,alpha){
  if(!ready(im))return;
  const s=P*(k||1);ctx.save();ctx.imageSmoothingEnabled=false;if(alpha!=null)ctx.globalAlpha*=alpha;
  ctx.translate(Math.round(x),Math.round(y));if(flip)ctx.scale(-1,1);
  ctx.drawImage(im,col*cw,row*ch,cw,ch,-ax*s,-ay*s,cw*s,ch*s);ctx.restore();
}
function strip(name,cw,ch,i,ax,ay,x,y,k,alpha){const im=img(name);if(!ready(im))return;const n=Math.floor(im.width/cw);cell(im,cw,ch,Math.max(0,Math.min(n-1,i)),0,ax,ay,x,y,k,false,alpha)}

/* static ground: grass, sand lanes, the river banks' edge tiles, bridges, ground letters */
function paintLand(){
  land.width=cv.width;land.height=cv.height;const g=land.getContext('2d');g.imageSmoothingEnabled=false;
  const T=U,top=(RIVER-1)*U,bot=(RIVER+1)*U;
  // grass and dirt lanes: a pixel-art texture generated once (see groundTexture), scaled up crisp
  g.drawImage(groundTexture(),OX-EX*U,0,(W+2*EX)*U,land.height);
  g.clearRect(0,top,land.width,bot-top);
  g.fillStyle='rgba(242,74,64,.05)';g.fillRect(0,0,land.width,top);g.fillStyle='rgba(61,139,255,.06)';g.fillRect(0,bot,land.width,land.height-bot);
  g.fillStyle='#4a8a33';g.fillRect(0,top-0.12*U,land.width,0.12*U);g.fillStyle='#3d7a2b';g.fillRect(0,bot,land.width,0.08*U);
  // decorations away from the lanes
  const dec=(n,x,y,k)=>{const d=img('decor/'+n);if(ready(d))g.drawImage(d,0,0,d.width,d.height,OX+x*U-d.width*P*k/2,y*U-d.height*P*k,d.width*P*k,d.height*P*k)};
  for(const[n,x,y]of[['04',1.6,11.6],['07',16.6,11.7],['08',2.0,16.8],['09',15.9,17.2],['10',7.1,9.4],['11',11.2,19.0],['05',12.2,8.8],['04',6.4,19.6]])dec(n,x,y,1);
  // (no names on the grass: the start banner introduces the two sides)
}
/* Ground texture, drawn once at 32 texels per board tile (2 Tiny Swords pixels each) so it matches the sprites'
   pixel scale. Grass: soft patches, tufts with light tips, a few flowers. Lanes: sand with speckles and pebbles,
   a wobbly edge, a darker sand rim and a grass shadow. Seeded, so every match looks the same. */
let GROUND=null;
const EX=4;  // tiles of scenery generated beyond each side of the playfield
function groundTexture(){
  if(GROUND)return GROUND;
  const S=32,w=(W+2*EX)*S,h=H*S,c=document.createElement('canvas');c.width=w;c.height=h;
  const g=c.getContext('2d'),id=g.createImageData(w,h),px=id.data;
  const hash=(x,y,k)=>{let n=(Math.imul(x,374761393)+Math.imul(y,668265263)+Math.imul(k,1013904223))|0;n=Math.imul(n^(n>>>13),1274126177);return((n^(n>>>16))>>>0)/4294967296};
  const smooth=(x,y,k)=>{const x0=Math.floor(x),y0=Math.floor(y),fx=x-x0,fy=y-y0,u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
    const a=hash(x0,y0,k),b=hash(x0+1,y0,k),c=hash(x0,y0+1,k),d=hash(x0+1,y0+1,k);return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v};
  const hex=s=>[parseInt(s.slice(1,3),16),parseInt(s.slice(3,5),16),parseInt(s.slice(5,7),16)];
  const G=['#74b84a','#6caf44','#5e9f3b','#4f8f34','#8fca5a','#a8db70'].map(hex);   // grass: base, patch, shade, deep, light, tip
  const D=['#e8cf8c','#dbbd74','#f3dfa3','#c49e5c','#b48a4a'].map(hex);             // sand: base, speckle, light, rim, pebble
  const put=(x,y,col)=>{if(x<0||y<0||x>=w||y>=h)return;const i=(y*w+x)*4;px[i]=col[0];px[i+1]=col[1];px[i+2]=col[2];px[i+3]=255};
  // lanes in texels, as boxes [cx, cy, half-width, half-height]
  const boxes=[];const R=(x0,y0,x1,y1)=>boxes.push([(x0+x1)/2*S+EX*S,(y0+y1)/2*S,(x1-x0)/2*S,(y1-y0)/2*S]);
  for(const lx of LANES){R(lx-0.8,5.5,lx+0.8,RIVER-0.6);R(lx-0.8,RIVER+0.6,lx+0.8,22.5)}
  R(4,4.75,14,6.25);R(4,21.75,14,23.25);R(8.25,2.4,9.75,5.5);R(8.25,22.5,9.75,25.6);
  const kind=new Uint8Array(w*h);   // 0 grass, 1 grass shadow, 2 sand rim, 3 sand
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    let d=1e9;for(const[cx,cy,hw,hh]of boxes)d=Math.min(d,Math.max(Math.abs(x-cx)-hw,Math.abs(y-cy)-hh));
    const wob=(smooth(x/7,y/7,3)-0.5)*5;   // ±2.5 texels of wobble along the edge
    const k=d<wob-2?3:d<wob?2:d<wob+2?1:0,i=y*w+x;kind[i]=k;
    if(k===3){const r=hash(x,y,5);put(x,y,r<0.06?D[1]:r<0.1?D[2]:D[0])}
    else if(k===2)put(x,y,D[3]);
    else if(k===1)put(x,y,G[3]);
    else{const n=smooth(x/28,y/28,1),m=smooth(x/9,y/9,2);put(x,y,n>0.62?G[1]:n<0.3&&m>0.55?G[1]:G[0])}
  }
  // pebbles on the sand
  for(let n=0;n<900;n++){const x=Math.floor(hash(n,1,7)*w),y=Math.floor(hash(n,2,7)*h);
    if(kind[y*w+x]===3&&kind[y*w+x+1]===3){put(x,y,D[4]);put(x+1,y,D[4]);put(x,y-1,D[2])}}
  // grass tufts: three blades with a dark base and light tips
  for(let n=0;n<5200;n++){const x=Math.floor(hash(n,3,9)*w),y=Math.floor(hash(n,4,9)*h);
    let ok=true;for(let dy=-3;dy<=1&&ok;dy++)for(let dx=-1;dx<=5;dx++){const xx=x+dx,yy=y+dy;if(xx<0||yy<0||xx>=w||yy>=h||kind[yy*w+xx]!==0){ok=false;break}}
    if(!ok)continue;
    const big=hash(n,5,9)>0.7;
    put(x,y,G[2]);put(x+2,y,G[2]);put(x+4,y,G[2]);put(x+1,y,G[3]);put(x+3,y,G[3]);
    put(x,y-1,G[4]);put(x+2,y-1,G[2]);put(x+4,y-1,G[4]);put(x+2,y-2,G[4]);
    if(big){put(x+2,y-3,G[5]);put(x,y-2,G[5]);put(x+4,y-2,G[5])}}
  // a few flowers
  for(let n=0;n<160;n++){const x=Math.floor(hash(n,6,11)*w),y=Math.floor(hash(n,7,11)*h);if(kind[y*w+x]!==0||kind[(y+1)*w+x]!==0)continue;
    const col=hash(n,8,11)<0.5?[255,248,230]:[255,214,92];put(x,y,col);put(x-1,y,col);put(x+1,y,col);put(x,y-1,col);put(x,y,[240,170,60]);put(x,y+1,G[3])}
  g.putImageData(id,0,0);GROUND=c;return c;
}
function drawWater(clock){
  const top=(RIVER-1.6)*U,h=3.2*U,wi=img('terrain/water');
  ctx.fillStyle='#47aba9';ctx.fillRect(-OX,top,cv.width,h);
  const fo=img('terrain/foam');
  if(ready(fo)){const T=U,f0=Math.floor(clock*8);
    for(const[edge,dy]of[[(RIVER-1)*U,-T],[(RIVER+1)*U,0]])for(let x=-Math.ceil(OX/T)*T,i=0;x<cv.width-OX;x+=T,i++){
      const f=(f0+i*3)%8;ctx.drawImage(fo,f*192,0,192,192,x+T/2-1.75*T,edge+dy+T/2-1.75*T,3.5*T,3.5*T)}}
  const wr=img('terrain/water_rocks');
  if(ready(wr))for(const[x,i]of[[1.3,0],[16.6,3]]){const f=(Math.floor(clock*6)+i)%8;ctx.drawImage(wr,f*128,0,128,128,(x-1)*U,(RIVER-1)*U,2*U,2*U)}
}
function drawBridges(){
  const b=img('terrain/bridge');if(!ready(b))return;const k=1.35,T=64*P*k;
  for(const lx of LANES){const x=lx*U-T/2,y0=(RIVER-1.5*k)*U;
    ctx.drawImage(b,0,64,64,64,x,y0,T,T);ctx.drawImage(b,0,128,64,64,x,y0+T,T,T);ctx.drawImage(b,0,192,64,64,x,y0+2*T,T,T)}
}
// Trees filling the strips beside the playfield (and lining its edges), back to front, clear of the river.
let FOREST_AT=null,FOREST_LIST=[];
function FOREST(){
  const side=OX/U;if(FOREST_AT===side)return FOREST_LIST;FOREST_AT=side;FOREST_LIST=[];
  const cols=[];for(let x=-0.2;x>-side-0.8;x-=1.25)cols.push(x);
  for(const c of cols)for(let y=1.2,k=0;y<H+1;y+=1.55,k++){
    if(Math.abs(y-RIVER)<1.9)continue;const j=((k*7+Math.round(c*13))%5)/10;
    FOREST_LIST.push([c-j*0.4,y+j,k%4],[W-c+j*0.4,y+0.7-j,(k+2)%4])}
  FOREST_LIST.sort((a,b)=>a[1]-b[1]);return FOREST_LIST;
}
function drawEdgeDecor(clock){
  // trees along both sides, swaying; a sheep on each bank
  const tr=img('decor/tree');
  if(ready(tr))for(const[x,y,i]of FOREST()){const f=(Math.floor(clock*5)+i)%4;cell(tr,192,192,f,0,96,176,x*U,y*U,1.0)}
  const sh=img('decor/sheep');
  if(ready(sh))for(const[x,y,i]of[[16.4,3.2,0],[1.8,26.6,4]]){const f=(Math.floor(clock*6)+i)%8;cell(sh,128,128,f,0,64,86,x*U,y*U,0.9,i>0)}
}

/* buildings: princess towers and kings, an archer on each tower, ruins that burn */
function towerShooting(S,t){return S.shots.some(s=>s.k==='ball'&&Math.abs(s.x1-t.x)<0.01&&Math.abs(s.y1-t.y)<0.01&&S.t-s.t<0.3)}
function drawTower(S,t,clock){
  const king=t.kind==='K',x=t.x*U,base=(t.y+(king?1.4:1.0))*U;
  if(!t.alive){
    if(king)cell(img('ruins/castle'),320,256,0,0,160,254,x,base,1);else cell(img('ruins/tower'),128,256,0,0,64,230,x,base,1);
    const fi=img('fx/fire');
    for(const[dx,dy,i]of(king?[[-1.2,-1.3,0],[0.9,-1.1,3]]:[[0,-1.0,1]]))cell(fi,128,128,(Math.floor(clock*10)+i)%7,0,64,114,x+dx*U,base+dy*U,0.7);
    return;
  }
  const shake=(S.t-t.hit<0.08&&S.t>0.2)?Math.sin(clock*90)*0.05*U:0;
  if(king)cell(img(TEAM[t.side]+'/castle'),320,256,0,0,160,250,x+shake,base,1);
  else{
    cell(img(TEAM[t.side]+'/tower'),128,256,0,0,64,235,x+shake,base,1);
    // the tower's archer, facing its target
    const shooting=towerShooting(S,t),face=t.aim==null?(t.side===0?1:-1):(Math.cos(t.aim)>=0?1:-1);
    const up=t.aim!=null&&Math.abs(Math.sin(t.aim))>0.7,row=shooting?(up?(Math.sin(t.aim)<0?2:6):4):0;
    const col=shooting?Math.min(7,Math.floor((S.t%0.8)/0.1)):Math.floor(clock*8)%6;
    cell(img(TEAM[t.side]+'/archer'),192,192,col,row,99,134,x+shake,base-2.15*U,0.8,face<0);
  }
}
function hpBar(x,y,w,h,frac,side,num){
  rr(x-w/2,y,w,h,h*0.4);fs('#1b1830',OL,Math.max(2,0.1*U));
  if(frac>0){rr(x-w/2,y,Math.max(h*0.6,w*frac),h,h*0.4);fs(TC[side].m,0)}
  if(num!=null)label(String(num),x,y+h*0.55,h*1.45,'#fff',h*0.45);
}
// A speech bubble as one path: a rounded box with a tail on its left edge pointing at (tx, ty), so it has one
// clean outline and no seam where the tail joins.
function bubble(x,y,w,h,r,tx,ty,tw){const cy=y+h/2;ctx.beginPath();ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);ctx.arcTo(x+w,y,x+w,y+r,r);
  ctx.lineTo(x+w,y+h-r);ctx.arcTo(x+w,y+h,x+w-r,y+h,r);ctx.lineTo(x+r,y+h);ctx.arcTo(x,y+h,x,y+h-r,r);
  ctx.lineTo(x,cy+tw);ctx.lineTo(tx,ty);ctx.lineTo(x,cy-tw);ctx.lineTo(x,y+r);ctx.arcTo(x,y,x+r,y,r);ctx.closePath()}
// Tower health, Clash style: a team badge (crown or turret) on the left, a glossy fill, the number on top, and a
// yellow trail that drains away after each hit so damage is visible at a glance.
const TRAIL={};let trailClock=0;
function towerBar(t,clock){
  const king=t.kind==='K',bw=(king?3.6:3.0)*U,bh=0.62*U,frac=Math.max(0,t.hp/t.max),key=t.side+t.kind;
  // Bars sit just above each tower, as in Clash; the top king's castle reaches the board's edge, so its bar stays there.
  const y=king?(t.side===1?0.12*U:(t.y-2.55)*U):(t.y-2.9)*U;
  const tr=TRAIL[key];if(!tr||frac>tr.v)TRAIL[key]={v:frac};else tr.v=Math.max(frac,tr.v-Math.max(0,clock-trailClock)*0.9);
  const x0=t.x*U-bw/2,r=bh*0.45,tc=TC[t.side];
  rr(x0,y,bw,bh,r);fs('#241c38',OL,Math.max(2,0.11*U));
  ctx.save();rr(x0,y,bw,bh,r);ctx.clip();
  ctx.fillStyle='#ffe066';ctx.fillRect(x0,y,bw*TRAIL[key].v,bh);
  const g=ctx.createLinearGradient(0,y,0,y+bh);g.addColorStop(0,tc.l);g.addColorStop(0.45,tc.m);g.addColorStop(1,tc.d);
  ctx.fillStyle=g;ctx.fillRect(x0,y,bw*frac,bh);
  ctx.fillStyle='rgba(255,255,255,.35)';ctx.fillRect(x0,y+bh*0.14,bw*frac,bh*0.16);
  ctx.restore();rr(x0,y,bw,bh,r);ctx.strokeStyle=OL;ctx.lineWidth=Math.max(2,0.11*U);ctx.stroke();
  // badge
  const bx=x0,byc=y+bh/2,br=bh*0.82;
  C(bx,byc,br);fs(tc.d,OL,Math.max(2,0.11*U));C(bx,byc,br*0.72);fs(tc.m,0);
  ctx.save();ctx.translate(bx,byc);ctx.scale(br,br);
  if(king){crown(0,0.05,0.48);fs(GOLD,OL,0.1)}
  else{ctx.beginPath();ctx.moveTo(-0.38,0.45);ctx.lineTo(-0.38,-0.2);ctx.lineTo(-0.46,-0.2);ctx.lineTo(-0.46,-0.48);ctx.lineTo(-0.26,-0.48);ctx.lineTo(-0.26,-0.34);
    ctx.lineTo(-0.1,-0.34);ctx.lineTo(-0.1,-0.48);ctx.lineTo(0.1,-0.48);ctx.lineTo(0.1,-0.34);ctx.lineTo(0.26,-0.34);ctx.lineTo(0.26,-0.48);ctx.lineTo(0.46,-0.48);
    ctx.lineTo(0.46,-0.2);ctx.lineTo(0.38,-0.2);ctx.lineTo(0.38,0.45);ctx.closePath();fs('#fff',OL,0.09)}
  ctx.restore();
  label(String(Math.ceil(t.hp)),x0+bw/2+br*0.35,y+bh*0.55,bh*1.15,'#fff',bh*0.36);
}

/* troops */
const FACE={};
function facing(u){if(u.dir==='left')FACE[u.id]=-1;else if(u.dir==='right')FACE[u.id]=1;else if(FACE[u.id]==null)FACE[u.id]=u.side===0?1:-1;return FACE[u.id]}
function troop(u,t,clock,alpha){
  const A=UNIT[u.type],im=img(TEAM[u.side]+'/'+A.sheet),x=u.x*U,y=(u.y+0.45)*U,flip=facing(u)<0;
  let row,col;
  const age=u.atk==null?99:t-u.atk;
  if(u.act==='attack'&&age<A.atkDur){const d=u.dir==='up'?'up':u.dir==='down'?'down':'right';[row]=A.atk[d];col=Math.floor(age/A.atkDur*A.atk[d][1])}
  else if(u.act==='walk'){row=A.run[0];col=Math.floor(clock*10+u.id*1.7)%A.run[1]}
  else{row=A.idle[0];col=Math.floor(clock*8+u.id)%A.idle[1]}
  const r=FOOT[u.type];E(x,y,r*1.15*U,r*0.42*U);ctx.fillStyle='rgba(0,0,0,.25)';ctx.fill();
  const cw=A.cw||192;cell(im,cw,cw,col,row,A.ax,A.ay,x,y,A.scale,flip,alpha);
}
function troopBar(u){const A=UNIT[u.type],top=(u.y+0.45)*U-A.tall*P*A.scale-0.25*U;
  hpBar(u.x*U,top,(u.type==='brute'?1.6:1.15)*U,0.28*U,u.hp/u.max,u.side)}

function draw(S,clock){
  ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;ctx.imageSmoothingEnabled=false;
  ctx.fillStyle='#62a14a';ctx.fillRect(0,0,cv.width,cv.height);
  ctx.setTransform(1,0,0,1,OX,0);
  drawWater(clock);ctx.drawImage(land,-OX,0);drawBridges();
  const left=Math.max(0,Math.ceil(S.dur-S.t));
  // the clock appears once the start banner has gone
  if(!bannerUp()){rr(7.1*U,(RIVER-0.85)*U,3.8*U,1.7*U,0.85*U);fs('#1b1830',OL,0.12*U);
  label(Math.floor(left/60)+':'+String(left%60).padStart(2,'0'),9*U,(RIVER+0.06)*U,1.1*U,'#fff',0.2*U);}

  drawEdgeDecor(clock);
  const things=[];for(const t of S.towers)things.push({y:t.y+(t.kind==='K'?1.4:1.0),t});for(const u of S.units)things.push({y:u.y+0.45,u});
  things.sort((a,b)=>a.y-b.y);
  for(const o of things){if(o.t)drawTower(S,o.t,clock);else troop(o.u,S.t,clock,S.t-o.u.hit<0.08?0.6:null)}
  for(const t of S.towers)if(t.alive)towerBar(t,clock);trailClock=clock;
  for(const u of S.units)if(u.hp<u.max||u.max>=900)troopBar(u);

  for(const s of S.shots){const p=Math.min(1,(S.t-s.t)/0.25),x=(s.x1+(s.x2-s.x1)*p)*U,y=(s.y1+(s.y2-s.y1)*p)*U,a=Math.atan2(s.y2-s.y1,s.x2-s.x1);
    if(s.k==='bomb'){const lift=Math.sin(p*Math.PI)*0.9*U;cell(img('fx/dynamite'),64,64,Math.floor(p*12)%6,0,34,27,x,y-lift,0.9)}
    else{const yy=s.k==='ball'?y-1.4*U*(1-p):y,im=img('fx/arrow');if(ready(im)){ctx.save();ctx.translate(x,yy);ctx.rotate(a);ctx.imageSmoothingEnabled=false;ctx.drawImage(im,0,0,64,64,-40*P,-35*P,64*P,64*P);ctx.restore()}}}

  for(const f of S.fx){const a=S.t-f.t,x=f.x*U,y=f.y*U;
    if(f.kind==='deploy'){
      if(a<0.45){const k=a/0.45;ctx.globalAlpha=1-k;ctx.strokeStyle='#fff';ctx.lineWidth=0.18*U;ctx.beginPath();ctx.ellipse(x,y+0.4*U,(0.6+1.6*k)*U,(0.25+0.6*k)*U,0,0,TAU);ctx.stroke();ctx.globalAlpha=1}
      const life=a/1.4,pop=Math.min(1,a/0.12),cy=y+(f.side===0?3.2:-3.2)*U-(f.side===0?-1:1)*life*0.4*U,s=U*pop;
      ctx.globalAlpha=life<0.7?1:Math.max(0,1-(life-0.7)/0.3);
      ctx.setTransform(s,0,0,s,OX+x,cy);rr(-1.5,-1.75,3,3.5,0.3);fs('#fff4d6',TC[f.side].d,0.22);rr(-1.5,-1.75,3,3.5,0.3);ctx.strokeStyle=OL;ctx.lineWidth=0.07;ctx.stroke();
      rr(-1.25,-1.5,2.5,2.05,0.2);fs(TC[f.side].l,0);
      if(f.lat!=null){rr(-1.35,1.95,2.7,0.95,0.45);fs(f.side===0?TC[0].d:'#ffe066',OL,0.08)}
      ctx.setTransform(s,0,0,s,OX+x-1.5*s,cy-1.6*s);ctx.beginPath();ctx.arc(0,0.12,0.58,-Math.PI*0.25,Math.PI*1.25);ctx.lineTo(0,-0.78);ctx.closePath();fs('#f255f0',OL,0.12);
      ctx.setTransform(1,0,0,1,OX,0);
      const A=UNIT[f.type];
      // portrait: the idle frame cropped to the character and fitted to the card's window
      const pim=A&&img(TEAM[f.side]+'/'+A.sheet);
      if(pim&&ready(pim)){const[bx,by,bw,bh]=A.box,cw=A.cw||192,fit=Math.min(2.3*s/bw,1.85*s/bh),dw=bw*fit,dh=bh*fit;
        ctx.save();ctx.imageSmoothingEnabled=false;ctx.drawImage(pim,bx,A.idle[0]*cw+by,bw,bh,x-dw/2,cy-0.47*s-dh/2,dw,dh);ctx.restore()}
      label(f.label,x,cy+1.12*s,0.78*s,'#fff',0.2*s);
      label(String(CARD_COST[f.type]||''),x-1.5*s,cy-1.48*s,0.78*s,'#fff',0.22*s);
      if(f.lat!=null){ctx.font=`800 ${0.62*s}px ${MONO}`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle=f.side===0?'#fff':OL;ctx.fillText(f.lat.toFixed(f.lat<1?2:1)+'s',x,cy+2.44*s)}
      ctx.globalAlpha=1}
    else if(f.kind==='boom'&&a<0.5){strip('fx/explosion',192,192,Math.floor(a/0.5*9),96,96,x,y,f.r*0.9)}
    else if(f.kind==='pop'){cell(img('fx/dead'),128,128,Math.floor(a/0.1)%7,a<0.7?0:1,65,99,x,y+0.45*U,0.7)}
    else if(f.kind==='fall'){
      if(a<0.9)strip('fx/explosion',192,192,Math.floor(a/0.9*9),96,96,x,y,2.6);
      const k=a/1.4;ctx.globalAlpha=Math.max(0,1-k*k);ctx.setTransform(U,0,0,U,OX+x,y-(1+k*2.5)*U);crown(0,0,1.1);fs(GOLD,OL,0.14);ctx.setTransform(1,0,0,1,OX,0);ctx.globalAlpha=1}
  }
  // thinking bubble in the open grass beside and behind each king that is still waiting on its model, its tail
  // pointing at the castle: troops attack from the front, so the fight is never under it
  for(const i of[1,0]){const sd=S.sides[i],kt=S.towers.find(t=>t.side===i&&t.kind==='K');
    if(!sd||S.over||sd.thinking_since==null||!kt.alive)continue;const el=S.t-sd.thinking_since;if(el<0.6)continue;
    const bx=14.1,by=i===1?1.45:H-1.45;ctx.setTransform(U,0,0,U,OX,0);
    // ring on the left with padding, the seconds left-aligned after a clear gap
    bubble(bx-2.3,by-0.9,4.6,1.8,0.6,bx-3.0,by,0.4);fs('#fff',OL,0.12);
    ctx.beginPath();ctx.arc(bx-1.45,by,0.5,-Math.PI/2,-Math.PI/2+TAU*Math.min(1,el/8));ctx.strokeStyle=TC[i].m;ctx.lineWidth=0.2;ctx.stroke();
    ctx.setTransform(1,0,0,1,OX,0);
    ctx.font=`800 ${0.9*U}px ${MONO}`;ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillStyle=TC[i].d;ctx.fillText(el.toFixed(1)+'s',(bx-0.65)*U,(by+0.05)*U)}
}

/* ---------- decision rails ---------- */
const tapes=[$('tp0'),$('tp1')];
function sizeTapes(){for(const c of tapes){c.width=Math.round(c.clientWidth*2);c.height=84}}
// A 10-second rail: one tick per decision (tall with a pink dot when it played a card), a yellow bar for the call still out, now at the right edge.
function drawTape(i,S){
  const c=tapes[i],g=c.getContext('2d'),w=c.width,h=c.height,span=10,pad=14,t0=S.t-span,X=t=>pad+(t-t0)/span*(w-2*pad),mid=54,col=TC[i];
  const pill=(x,y,ww,hh)=>{g.beginPath();g.roundRect?g.roundRect(x,y,ww,hh,Math.min(ww,hh)/2):g.rect(x,y,ww,hh);g.fill()};
  g.clearRect(0,0,w,h);
  g.font=`700 24px ${MONO}`;g.textBaseline='top';g.fillStyle='rgba(255,255,255,.6)';
  g.textAlign='left';g.fillText('10s ago',pad,0);g.textAlign='right';g.fillText('now',w-pad,0);
  g.fillStyle='rgba(255,255,255,.12)';pill(pad,mid-3,w-2*pad,6);
  const sd=S.sides[i];
  for(const d of sd.recent||[]){if(d.a<t0)continue;const x=X(d.a);
    if(d.c){g.fillStyle='#fff';pill(x-4,mid-22,8,44);g.fillStyle='#f255f0';g.beginPath();g.arc(x,mid-22,8,0,TAU);g.fill();g.strokeStyle=OL;g.lineWidth=3;g.stroke()}
    else{g.fillStyle=col.l;pill(x-3,mid-14,6,28)}}
  const nx=X(S.t);
  if(sd.thinking_since!=null&&!S.over){const x1=X(Math.max(sd.thinking_since,t0,0));g.fillStyle='rgba(255,224,102,.9)';pill(x1,mid-11,Math.max(4,nx-x1),22)}
  g.fillStyle='#fff';g.beginPath();g.arc(nx,mid,7,0,TAU);g.fill();
}

/* ---------- HUD ---------- */
const cache={};
function set(key,v,fn){if(cache[key]!==v){cache[key]=v;fn(v)}}
function hud(S){
  for(const i of[0,1]){const s=S.sides[i];
    // Whole elixir points are solid; the point still charging shows as a translucent segment growing into the next one.
    set('p'+i,(s.elixir/10).toFixed(3),v=>{const b=$('pp'+i).style;b.setProperty('--c',v);b.setProperty('--v',(Math.floor(s.elixir+1e-6)/10).toFixed(1))});
    set('e'+i,Math.floor(s.elixir+1e-6),v=>$('ex'+i).textContent=v);
    set('cap'+i,s.elixir>=9.99&&!S.over,v=>{$('pp'+i).classList.toggle('capped',v);$('tk'+i).classList.toggle('capped',v)});
    set('d'+i,s.decisions,v=>$('dc'+i).textContent=v);
    set('lk'+i,s.wasted.toFixed(1),v=>{const L=$('lk'+i);L.querySelector('b').textContent=s.wasted>=0.1?'−'+v:v;L.classList.toggle('on',s.wasted>=0.1)});
    set('lkb'+i,Math.floor(s.wasted),v=>{const L=$('lk'+i);if(!v)return;L.classList.remove('bump');void L.offsetWidth;L.classList.add('bump')});
    const thinking=s.thinking_since!=null&&!S.over&&S.t-s.thinking_since>0.5;
    let lbl,num,cls='status';
    if(thinking){lbl='thinking…';num=(S.t-s.thinking_since).toFixed(1)+'s';cls='status thinking'}
    else if(s.last&&s.last.why==='error'){lbl='call failed';num='–';cls='status thinking'}
    else if(i===0&&s.avg!=null){lbl='avg decision';num=s.avg.toFixed(2)+'s'}
    else if(s.last){lbl='decided in';num=s.last.lat.toFixed(1)+'s'}
    else{lbl='ready';num='–'}
    const st=$('st'+i);set('sl'+i,lbl,v=>st.firstChild.textContent=v);set('sn'+i,num,v=>st.lastChild.textContent=v);set('sc'+i,cls,v=>st.className=v);
    drawTape(i,S);
  }
}

/* ---------- captions: plain-language narration for sound-off viewing ---------- */
const capEl=$('cap');let capQueue=[],capShownAt=-99,capFlags={},seenFalls=0;
function say(key,html){if(capFlags[key])return;capFlags[key]=1;capQueue.push(html)}
// Captions shrink until they fit the rail, so a long one never runs into the board.
function fitCap(){let fs=46;capEl.style.fontSize=fs+'px';while(capEl.scrollHeight>capEl.clientHeight+1&&fs>28){fs-=2;capEl.style.fontSize=fs+'px'}}
function showCap(html,now){capShownAt=now;if(RECORD){capEl.innerHTML=html;fitCap();return}capEl.classList.add('out');setTimeout(()=>{capEl.innerHTML=html;fitCap();capEl.classList.remove('out')},180)}
const N=i=>`<span class="${i?'s':'j'}">${NAMES[i]}</span>`;
function captions(S,now){
  if(!S||!S.sides.length)return;
  const sol=S.sides[1],jev=S.sides[0];
  const sec=v=>v<1?v.toFixed(2):v.toFixed(1);
  say('open',LAT?`${N(0)} answers in <span class="n">~${sec(LAT[0])}s</span>. ${N(1)} thinks for <span class="n">~${sec(LAT[1])}s</span>. Same game, same rules.`
    :`Same game, same rules. Every move is a live model call.`);
  if(!LAT&&jev.avg!=null&&sol.decisions>=1)say('speed',`${N(0)} decides in <span class="n">${jev.avg.toFixed(2)}s</span>. ${N(1)} took <span class="n">${sol.last.lat.toFixed(1)}s</span>.`);
  if(sol.thinking_since!=null&&S.t-sol.thinking_since>2.5)say('wait',`${N(1)} is still thinking. The match clock keeps running.`);
  if(jev.decisions>=40)say('count',`${N(0)} has made <span class="n">${jev.decisions}</span> decisions. ${N(1)} has made <span class="n">${sol.decisions}</span>.`);
  const falls=S.towers.filter(t=>!t.alive);
  for(const t of falls){const key='t'+t.side+t.kind;if(capFlags[key])continue;
    const by=1-t.side,clock=Math.max(0,Math.ceil(S.dur-S.t));
    if(t.kind==='K'){say(key,`${N(by)} takes the king tower. Game over.`);capQueue=[capQueue.pop()];capShownAt=-99}
    else{const c=[0,1].map(i=>S.towers.filter(t=>t.side!==i&&!t.alive).length);const lead=c[0]===c[1]?-1:c[0]>c[1]?0:1;
      say(key,`Tower down at <span class="n">0:${String(clock).padStart(2,'0')}</span>. `+(lead<0?`It's ${c[0]}–${c[1]}.`:`${N(lead)} leads ${Math.max(...c)}–${Math.min(...c)}.`))}}
  if(capQueue.length&&now-capShownAt>3.4)showCap(capQueue.shift(),now);
}
function resetCaptions(){capQueue=[];capFlags={};capShownAt=-99;capEl.innerHTML='&nbsp;'}

/* ---------- intro and result cards ---------- */
function setPlayers(players){
  NAMES=players.map(p=>p.name);
  for(const i of[0,1]){const p=players[i];
    for(const id of['nm','inm','th'])$(id+i).textContent=p.name;
    $('md'+i).textContent=p.model+(p.effort?' · '+p.effort:'');$('imd'+i).textContent=p.model;
    if(p.role)$('rl'+i).textContent=$('irl'+i).textContent=p.role;
    $('bn'+i).textContent=p.name;}
  MIRROR=players[0].model===players[1].model;
  document.title=NAMES[1]+' vs '+NAMES[0]+': System One Arena';
  paintLand();
}
function setLabels(mock){
  const badge={demo:'SIMULATION',replay:mock?'REPLAY · MOCK':'RECORDED LIVE',live:mock?'MOCK OPENROUTER':'LIVE MODEL CALLS'}[MODE];
  const line={demo:'Same strategy code on both sides. Only decision time differs.',
    replay:mock?'Recorded with mock OpenRouter: no model was called.':'Recorded live: every move was a real model call.',
    live:mock?'Answers come from mock OpenRouter: no model is called.':'Every move is a real model call. The clock never waits.'}[MODE];
  $('badge').textContent=badge;$('tagline').textContent=line;
  $('fine').textContent={demo:'Browser simulation of the arena engine: both sides run the same rule-based playbook, with decision times sampled around 0.35s and 6s, the arena\'s latency profiles for each API.',
    replay:mock?'Replay of a mock match: answers came from mock OpenRouter.':'Replay of a live match: each move came from its model through OpenRouter.',
    live:mock?'Mock match: answers came from mock OpenRouter, not a model.':'Live match: each move came from its model through OpenRouter.'}[MODE];
}
function introLatency(a,b){LAT=a!=null&&b!=null?[a,b]:null;
  for(const[i,v]of[[0,a],[1,b]])$('bl'+i).textContent=v==null?'':'~'+(v<1?v.toFixed(2):v.toFixed(1))+'s per move';for(const[i,v]of[[0,a],[1,b]]){const e=$('ilat'+i);if(v==null){e.hidden=true;continue}
  e.firstChild.textContent='~'+(v<1?v.toFixed(2):v.toFixed(1))+'s';e.hidden=false}}
function showResult(r,dur,t){
  const w=r.winner,sd=r.sides;
  $('verdict').textContent=NAMES[w]+' wins';$('verdict').classList.toggle('lost',w!==0);
  $('crowns').innerHTML='<svg viewBox="0 0 24 20"><use href="#crown"/></svg>'.repeat(Math.max(1,sd[w].crowns));
  $('resSub').textContent=r.reason==='king'?`${sd[0].crowns}–${sd[1].crowns} on towers · king tower down with ${Math.max(0,Math.ceil(dur-r.seconds))}s left on the clock`
    :`${sd[0].crowns}–${sd[1].crowns} on towers · decided at the final whistle`;
  const row=(k,f,better)=>{const v=[0,1].map(i=>f(sd[i]));[0,1].forEach(i=>{const e=$('r_'+k+i);e.textContent=v[i].txt;e.classList.toggle('best',better(v[i].n,v[1-i].n))})};
  row('t',s=>{const a=s.avg_decision_s;return{n:a==null?99:a,txt:a==null?'–':a.toFixed(a<1?2:1)+'s'}},(a,b)=>a<b);
  row('d',s=>({n:s.decisions,txt:String(s.decisions)}),(a,b)=>a>b);
  // Elixir lost at the cap, in troops: the deck's cards average about 3 elixir.
  row('w',s=>{const n=Math.round(s.elixir_wasted/3);return{n,txt:n?'≈'+n:'0'}},(a,b)=>a<b);
  row('c',s=>({n:s.crowns,txt:String(s.crowns)}),(a,b)=>a>b);
  $('thesis').innerHTML=MIRROR?`Same model on both sides. <em>${NAMES[w]}</em> took this one.`:w===0?`In real time, <em>a late answer is a wrong answer.</em>`
    :`This time ${NAMES[w]} won. <em>Speed is not the whole story.</em>`;
  $('bAgain').hidden=!(MODE==='live'&&CONFIG&&CONFIG.can_start);
  // The series so far between these two, from the archived matches: one match is an anecdote.
  $('series').hidden=true;$('r_cost').hidden=true;$('cheaper').hidden=true;
  if(MODE!=='demo')fetch('api/matches').then(r=>r.json()).then(j=>{
    // Cost per decision, from this match's logged OpenRouter costs (the frames do not carry them).
    const me=j.matches.find(m=>m.id===(MODE==='replay'?QS.get('replay'):matchKey));
    const rr=me&&me.result,cost=rr&&rr.cost_usd,calls=rr&&rr.calls;
    if(cost&&calls&&calls[0]&&calls[1]&&cost[0]>0&&cost[1]>0){
      const per=[0,1].map(i=>cost[i]/calls[i]),fmt=v=>'$'+(v*1000).toFixed(2);
      $('r_k0').textContent=fmt(per[0]);$('r_k1').textContent=fmt(per[1]);
      $('r_k0').classList.toggle('best',per[0]<per[1]);$('r_k1').classList.toggle('best',per[1]<per[0]);$('r_cost').hidden=false;
      const w=rr.winner,lo=per[w]<per[1-w],x=Math.max(per[0],per[1])/Math.min(per[0],per[1]);
      if(lo&&x>=1.5){$('cheaper').innerHTML=`${NAMES[w]} won at <b>${x.toFixed(x<10?0:0)}×</b> lower cost per decision.`;$('cheaper').hidden=false}
    }
    const same=j.matches.filter(m=>m.archived&&m.result&&!m.mock&&m.players&&m.players.join()===NAMES.join());
    if(same.length<2)return;
    const wins=[0,1].map(i=>same.filter(m=>m.result.winner===i).length);
    $('series').innerHTML=`Across ${same.length} recorded matches: <b class="j">${NAMES[0]} ${wins[0]}</b>, <b class="o">${NAMES[1]} ${wins[1]}</b>`;
    $('series').hidden=false}).catch(()=>{});
  $('result').classList.add('show');
}

/* ---------- sources ---------- */
function lerpFrame(a,b,k){
  if(!a||k>=1)return b;k=Math.max(0,k);
  const pos={};for(const u of a.units)pos[u.id]=u;
  return{...b,t:a.t+(b.t-a.t)*k,units:b.units.map(u=>{const p=pos[u.id];return p?{...u,x:p.x+(u.x-p.x)*k,y:p.y+(u.y-p.y)*k}:u})};
}
let view=null,elapsed=0,clock=0,paused=QS.has('pause'),overAt=null,resultFor=null,matchKey=null,last=performance.now();
const EMPTY={t:0,dur:60,over:false,units:[],towers:[[0,'L',4,22.5],[0,'R',14,22.5],[0,'K',9,25.6],[1,'L',4,5.5],[1,'R',14,5.5],[1,'K',9,2.4]]
  .map(([side,kind,x,y])=>({side,kind,x,y,hp:kind==='K'?6000:3800,max:kind==='K'?6000:3800,alive:true,aim:null,hit:-9})),shots:[],fx:[],
  sides:[0,1].map(()=>({elixir:5,wasted:0,decisions:0,crowns:0,thinking_since:null,last:null,avg:null,recent:[]}))};
function newMatch(key){for(const k in TRAIL)delete TRAIL[k];matchKey=key;bannerStart=elapsed;bannerWall=performance.now();overAt=null;resultFor=null;resetCaptions();for(const k in cache)delete cache[k];for(const k in FACE)delete FACE[k];$('result').classList.remove('show')}

// demo: the engine runs here
let sim=null,acc=0;
function demoRestart(){sim=new window.DemoSim({seed:14,duration:40});acc=0;elapsed=0;newMatch('demo'+performance.now());$('intro').classList.remove('show');
  if(AT){while(sim.t<AT&&!sim.over)sim.step(1/60);elapsed=INTRO+1e-3;bannerStart=-99}}
function demoView(dt){if(elapsed>INTRO){$('intro').classList.remove('show');acc+=dt;while(acc>=1/60&&!sim.over){sim.step(1/60);acc-=1/60}}return sim.frame()}

// replay: recorded frames on their own clock, after the intro card
let rframes=null;
function replayRestart(){elapsed=AT?INTRO+AT:0;newMatch('replay'+performance.now());if(AT)bannerStart=-99;$('intro').classList.remove('show')}
function replayView(){
  if(!rframes)return null;const t=elapsed-INTRO;
  if(t<0)return rframes[0];$('intro').classList.remove('show');
  let i=rframes.findIndex(f=>f.t>t);if(i<0)return rframes[rframes.length-1];if(i===0)return rframes[0];
  const a=rframes[i-1],b=rframes[i];return lerpFrame(a,b,(t-a.t)/((b.t-a.t)||1));
}

// live: the service pushes every frame; draw between the last two
let fa=null,fb=null,fbAt=0,gap=50;
function liveView(now){return fb?lerpFrame(fa,fb,(now-fbAt)/gap):null}
function onLiveFrame(f,id,now){
  if(id!==matchKey){newMatch(id);fa=null;if(f.t>0.5)bannerStart=-99}  // joined mid-match: no banner
  if(fb&&f.t<fb.t)fa=null;
  fa=fb&&f.t>=fb.t?fb:null;if(fa)gap=Math.max(16,Math.min(200,now-fbAt));fb=f;fbAt=now;
  if(!f.over)$('intro').classList.remove('show');
}

/* ---------- loop ---------- */
function tick(dt,now){
  elapsed+=dt;clock+=dt;
  view=MODE==='demo'?demoView(dt):MODE==='replay'?replayView():liveView(now);
  const S=view||EMPTY;
  if(S.over&&overAt==null)overAt=elapsed;
  if(S.over&&S.result&&overAt!=null&&elapsed-overAt>OUTRO_DELAY&&resultFor!==matchKey){resultFor=matchKey;showResult(S.result,S.dur,S.t)}
  draw(S,clock);hud(S);if(view)captions(S,elapsed);banner(view);
}
// Start-of-match banner: the two halves slam in from the sides, hold, then fade as the first troops land.
// Driven by match time, so it plays the same live, in replays and in recordings.
// Seconds since the match began. Live, from the wall clock (a background tab pauses animation frames, which would
// otherwise bring the banner back mid-match); in replays and recordings, from the stepped playback clock.
function bannerTime(){return bannerStart<0?-1:MODE==='live'?(performance.now()-bannerWall)/1000:elapsed-bannerStart}
function bannerUp(){const t=bannerTime();return !!view&&!view.over&&t>=0&&t<BANNER_OFF}
function banner(S){
  const el=$('banner'),t=bannerTime(),show=bannerUp();
  if(el.hidden!==!show)el.hidden=!show;if(!show)return;
  const p=Math.min(1,t/0.35),ease=1-Math.pow(1-p,3),slide=(1-ease)*620;
  $('bh1').style.transform=`translateX(${-slide}px)`;$('bh0').style.transform=`translateX(${slide}px)`;
  const pop=t<0.35?0:Math.min(1,(t-0.35)/0.15),vs=$('banner').querySelector('.bvs');
  vs.style.transform=`translate(-50%,-50%) scale(${0.4+0.6*pop})`;vs.style.opacity=pop;
  $('banner').querySelector('.bk').style.opacity=Math.min(1,t/0.35);
  el.style.opacity=t<BANNER_OFF-0.4?1:Math.max(0,(BANNER_OFF-t)/0.4);
}
function loop(now){
  const dt=paused?0:Math.min(0.1,(now-last)/1000);last=now;tick(dt,now);
  requestAnimationFrame(loop);
}
// For tools/record.py: step(dt) renders the next frame and says how far along the video is.
window.arenaRecord={ready:false,step(dt){tick(dt,performance.now());
  return{t:elapsed,ended:resultFor===matchKey,afterEnd:resultFor===matchKey?elapsed-overAt-OUTRO_DELAY:0}}};

/* ---------- controls ---------- */
function startMatch(){
  $('introNote').textContent='Starting…';
  fetch('api/matches',{method:'POST',headers:AUTH}).then(r=>r.json().then(j=>{if(!r.ok)throw new Error(j.detail||r.status)}))
    .catch(e=>{$('introNote').textContent='Could not start: '+e.message;$('intro').classList.add('show')});
}
function restart(){if(MODE==='demo')demoRestart();else if(MODE==='replay')replayRestart()}
$('bStart').onclick=$('bStartIntro').onclick=startMatch;
$('bAgain').onclick=()=>{$('result').classList.remove('show');$('intro').classList.add('show');startMatch()};
$('bReplay').onclick=restart;
$('bPause').onclick=()=>{paused=!paused;$('bPause').textContent=paused?'Resume':'Pause'};
$('bClean').onclick=()=>{document.body.classList.toggle('clean');fitFrame()};
document.addEventListener('keydown',e=>{if(e.target.closest&&e.target.closest('button')&&e.key===' ')return;
  if(e.key===' '&&MODE!=='live'){e.preventDefault();$('bPause').click()}else if((e.key==='r'||e.key==='R')&&MODE!=='live')restart();else if(e.key==='c'||e.key==='C')$('bClean').click()});

/* ---------- boot ---------- */
fitFrame();sizeArena();sizeTapes();
for(const im of Object.values(IMG))im.addEventListener('load',paintLand,{once:true});
if(document.fonts)document.fonts.ready.then(paintLand);
const playback=MODE!=='live';
$('bReplay').hidden=$('bPause').hidden=!playback;if(paused)$('bPause').textContent='Resume';
if(!playback)$('hint').textContent='C toggles clean frame. For a 1080×1920 capture, size the window to 9:16 and use Clean frame. To record a finished match, open it with ?replay=<id>.';

if(MODE==='demo'){
  setLabels(false);introLatency(0.35,6);$('introNote').textContent='Simulation: no model is called.';demoRestart();window.arenaRecord.ready=true;
}else{
  fetch('api/config',{cache:'no-store',headers:AUTH}).then(r=>r.json()).then(c=>{
    CONFIG=c;setPlayers(c.players);setLabels(c.mock);
    if(MODE==='replay'){
      const id=QS.get('replay');$('introNote').textContent='Loading replay…';
      Promise.all([fetch('api/matches/'+encodeURIComponent(id)+'/frames').then(r=>{if(!r.ok)throw new Error('no such match');return r.text()}),
        fetch('api/matches').then(r=>r.json())]).then(([t,list])=>{
        rframes=t.trim().split('\n').map(l=>JSON.parse(l));
        const m=list.matches.find(m=>m.id===id)||{};setLabels(!!m.mock);
        // A capped match says so on screen: the cap holds back the fast side only, which makes the result fairer.
        const gap=m.config&&m.config.min_interval;
        if(gap&&!m.mock)$('tagline').textContent='Real model calls. Each side: at most one decision every '+(gap===1?'second':gap+'s')+'.';
        const res=rframes[rframes.length-1].result;if(res)introLatency(res.sides[0].avg_decision_s,res.sides[1].avg_decision_s);
        $('introNote').textContent=RECORD?'':'Replay of match '+id+'.';replayRestart();window.arenaRecord.ready=true;
      }).catch(e=>{$('introNote').textContent='Replay unavailable: '+e.message});
    }else{
      $('bStart').hidden=$('bStartIntro').hidden=!c.can_start;
      $('introNote').textContent=c.running?'A match is running…':!c.can_start?'Waiting for the next match…':c.mock?'Mock OpenRouter: no model will be called.':'Every move will be a live model call.';
      const es=new EventSource('api/stream');
      es.addEventListener('frame',e=>{const m=JSON.parse(e.data);onLiveFrame(m.frame,m.match,performance.now())});
      es.onerror=()=>{$('introNote').textContent='Reconnecting to the arena…'};
    }
  }).catch(()=>{$('introNote').textContent='The arena service is not reachable.'});
}
if(!RECORD)requestAnimationFrame(loop);
})();
