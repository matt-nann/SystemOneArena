/* Browser-only demo: a port of arena/engine/sim.py and playbook.py for the static demo (?demo).
   Both sides run the same playbook; only the decision latency differs, and a timer stands in
   for the model call. frame() returns the same shape the service streams, so the viewer draws
   both the same way. Live and replayed matches never use this file. */
(function(){
const W=18,H=28,RIVER=14,LANES=[4,14];
const CARDS={
  warrior:{name:'Warrior',cost:3,count:1,hp:900,dmg:120,cd:1.0,range:0.6,speed:2.0,r:0.55},
  archers:{name:'Archers',cost:3,count:2,hp:220,dmg:70,cd:0.9,range:4.5,speed:2.0,r:0.38},
  goblins:{name:'Goblins',cost:2,count:4,hp:70,dmg:45,cd:0.8,range:0.5,speed:2.8,r:0.26},
  brute:{name:'Brute',cost:5,count:1,hp:2200,dmg:170,cd:1.4,range:0.6,speed:1.4,r:0.8,bo:true},
  dynamiter:{name:'Dynamiter',cost:3,count:1,hp:200,dmg:130,cd:1.5,range:4.0,speed:2.0,r:0.4,splash:1.6},
};
const DECK=['warrior','archers','brute','goblins','dynamiter'];
const IDLE_RECHECK=0.25, OWN_HALF=25.6-RIVER+2.5;
function mulberry32(seed){let a=seed>>>0;return()=>{a=(a+0x6D2B79F5)>>>0;let t=Math.imul(a^(a>>>15),1|a);t=(t+Math.imul(t^(t>>>7),61|t))^t;return((t^(t>>>14))>>>0)/4294967296}}
const dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
function facing(vx,vy,cur){if(Math.abs(vx)<1e-6&&Math.abs(vy)<1e-6)return cur;if(Math.abs(vx)>Math.abs(vy)*1.3)return vx>0?'right':'left';return vy>0?'down':'up'}

function playbook(st,options){
  options=options.filter(c=>c!=='wait');
  const val=ts=>ts.reduce((s,t)=>s+CARDS[t.type].cost/CARDS[t.type].count,0);
  const first=p=>p.find(c=>options.includes(c))||null;
  let best=null,gap0=0.4;
  for(let l=0;l<2;l++){const lane=st.lanes[l];
    const en=lane.their.filter(t=>t.k<=OWN_HALF);if(!en.length)continue;
    const ours=lane.your.filter(t=>t.k<=OWN_HALF);const g=val(en)-val(ours);
    if(g>gap0){best=[l,en];gap0=g}}
  if(best){const kinds=best[1].map(t=>t.type);let p;
    if(kinds.filter(k=>k==='goblins').length>=3)p=['dynamiter','archers','warrior','goblins'];
    else if(kinds.includes('brute'))p=['goblins','warrior','archers','dynamiter'];
    else if(kinds.includes('archers')||kinds.includes('dynamiter'))p=['warrior','goblins','archers','dynamiter'];
    else p=['goblins','archers','warrior','dynamiter'];
    return[first(p),best[0]]}
  for(let l=0;l<2;l++){const mine=st.lanes[l].your;
    const tank=mine.some(t=>t.type==='brute'||t.type==='warrior'),sup=mine.filter(t=>t.type!=='brute'&&t.type!=='warrior').length;
    if(tank&&sup<3&&st.elixir>=4){const c=first(['archers','dynamiter','goblins','warrior']);if(c)return[c,l]}}
  if(st.elixir>=7){const l=st.lanes[0].theirHp<=st.lanes[1].theirHp?0:1;const c=first(['brute','warrior','archers','dynamiter','goblins']);if(c)return[c,l]}
  return[null,0];
}

class Sim{
  constructor(cfg){
    this.cfg=Object.assign({seed:13,duration:60,elixir:1,towerHp:3800,kingHp:6000,lat:[[0.35,0.12],[6,1.5]]},cfg);
    this.rand=mulberry32(this.cfg.seed);this.lrand=mulberry32(this.cfg.seed*7+1);
    this.t=0;this.over=false;this.winner=null;this.units=[];this.shots=[];this.fx=[];this.events=[];
    this.sides=[0,1].map(()=>({elixir:5,wasted:0,decisions:0,plays:0,late:0,crowns:0,hand:DECK.slice(0,4),queue:DECK.slice(4),pending:null,last:null,lats:[],log:[]}));
    this.towers=[];this.nid=1;this.hurt=[];
    for(const[side,kind,x,y]of[[0,'L',4,22.5],[0,'R',14,22.5],[0,'K',9,25.6],[1,'L',4,5.5],[1,'R',14,5.5],[1,'K',9,2.4]]){
      const k=kind==='K',hp=k?this.cfg.kingHp:this.cfg.towerHp;
      this.towers.push({side,kind,x,y,hp,max:hp,alive:true,cd:0,r:k?1.4:1.1,range:k?6:6.5,dmg:k?70:60,rate:k?0.9:0.8,hit:-9,aim:null})}
  }
  tower(s,k){return this.towers.find(t=>t.side===s&&t.kind===k)}
  princess(s,l){return this.tower(s,l===0?'L':'R')}
  static fwd(s){return s===0?-1:1}
  ownHalf(s,u){return s===0?u.y>RIVER-2.5:u.y<RIVER+2.5}
  affordable(s){const S=this.sides[s];return S.hand.filter(c=>CARDS[c].cost<=S.elixir)}
  laneCtx(s,l){const en=this.units.filter(u=>u.side===1-s&&u.lane===l&&this.ownHalf(s,u));
    if(en.length)return{spot:'defend',ids:en.map(u=>u.id)};
    if(this.units.some(u=>u.side===s&&u.lane===l&&(u.type==='brute'||u.type==='warrior')))return{spot:'support'};
    return{spot:'bridge'}}
  state(s){const S=this.sides[s],king=this.tower(s,'K'),tr=u=>({type:u.type,k:Math.round(Math.abs(u.y-king.y)*10)/10});
    return{elixir:Math.floor(S.elixir+1e-6),lanes:[0,1].map(l=>({your:this.units.filter(u=>u.side===s&&u.lane===l).map(tr),their:this.units.filter(u=>u.side!==s&&u.lane===l).map(tr),theirHp:Math.ceil(this.princess(1-s,l).hp)}))}}
  latency(s){const[m,j]=this.cfg.lat[s];let g=0;for(let i=0;i<6;i++)g+=this.lrand();g=(g-3)/Math.sqrt(0.5);return Math.max(0.08,m+g*j)}
  ask(s){const S=this.sides[s];
    if(!this.affordable(s).length){S.pending={auto:true,start:this.t,due:this.t+IDLE_RECHECK};return}
    const[card,lane]=playbook(this.state(s),this.affordable(s));
    S.pending={start:this.t,due:this.t+this.latency(s),ctx:[this.laneCtx(s,0),this.laneCtx(s,1)],card,lane}}
  apply(i){const S=this.sides[i],p=S.pending;S.pending=null;if(p.auto)return;
    const lat=this.t-p.start;let card=p.card,late=false;const ctx=p.ctx[p.lane];
    if(card&&!(S.hand.includes(card)&&CARDS[card].cost<=S.elixir))card=null;
    if(card&&ctx.spot==='defend'){const alive=new Set(this.units.map(u=>u.id));late=!ctx.ids.some(id=>alive.has(id));S.late+=late}
    if(card)this.deploy(i,card,p.lane,ctx.spot,lat);
    S.decisions++;S.lats.push(lat);S.log.push({s:p.start,a:this.t,c:card});if(S.log.length>60)S.log.shift();
    S.last={card,lat,at:this.t,late};
    if(late)this.events.push({k:'late',side:i,t:this.t});
  }
  spotPos(s,l,spot){const f=Sim.fwd(s),lx=LANES[l],p=this.princess(s,l),k=this.tower(s,'K');
    if(spot==='defend')return p.alive?[lx,p.y+f*2.6]:[9+(lx-9)*0.45,k.y+f*3.2];
    if(spot==='support'){const leads=this.units.filter(u=>u.side===s&&u.lane===l&&(u.type==='brute'||u.type==='warrior'));
      if(leads.length){let lead=leads[0];for(const u of leads)if(f*(u.y-lead.y)>0)lead=u;let y=lead.y-f*2.2;y=s===0?Math.max(y,RIVER+1.2):Math.min(y,RIVER-1.2);return[lx,y]}}
    return[lx,RIVER-f*1.8]}
  deploy(s,card,lane,spot,lat){const me=this.sides[s],c=CARDS[card];me.elixir-=c.cost;me.plays++;
    const i=me.hand.indexOf(card);me.queue.push(card);me.hand[i]=me.queue.shift();
    const[px,py]=this.spotPos(s,lane,spot),n=c.count;
    for(let k=0;k<n;k++){const ox=n>1?((k%2)-0.5)*1.0+(this.rand()-0.5)*0.2:(this.rand()-0.5)*0.3,oy=n>2?(Math.floor(k/2)-0.5)*0.9:0;
      this.units.push({id:this.nid++,side:s,type:card,lane,x:px+ox,y:py+oy,hp:c.hp,max:c.hp,cd:0.4,hit:-9,atk:null,dir:s===0?'up':'down',act:'walk'})}
    this.fx.push({kind:'deploy',side:s,type:card,x:px,y:py,t:this.t,label:c.name,lat})}
  step(dt){if(this.over)return;this.t+=dt;
    for(const S of this.sides){S.elixir+=this.cfg.elixir*dt;if(S.elixir>10){S.wasted+=S.elixir-10;S.elixir=10}}
    this.sides.forEach((S,i)=>{const p=S.pending;if(p&&this.t>=p.due)this.apply(i);if(!S.pending)this.ask(i)});
    this.move(dt);this.separate();this.towersFire(dt);
    for(const[o,d]of this.hurt){o.hp-=d;o.hit=this.t}this.hurt=[];
    for(const u of this.units)if(u.hp<=0)this.fx.push({kind:'pop',side:u.side,x:u.x,y:u.y,t:this.t});
    this.units=this.units.filter(u=>u.hp>0);
    for(const tw of this.towers)if(tw.alive&&tw.hp<=0){tw.alive=false;tw.hp=0;const tk=this.sides[1-tw.side];tk.crowns+=tw.kind==='K'?3-tk.crowns:1;
      this.fx.push({kind:'fall',side:tw.side,x:tw.x,y:tw.y,t:this.t});this.events.push({k:'tower',side:1-tw.side,king:tw.kind==='K',t:this.t});
      if(tw.kind==='K'){this.over=true;this.winner=1-tw.side;this.reason='king'}}
    this.shots=this.shots.filter(s=>this.t-s.t<0.25);this.fx=this.fx.filter(f=>this.t-f.t<1.6);
    if(!this.over&&this.t>=this.cfg.duration){this.over=true;this.reason='time';const a=this.sides[0].crowns,b=this.sides[1].crowns;
      if(a!==b)this.winner=a>b?0:1;else{const hp=[0,1].map(s=>this.towers.filter(t=>t.side===s).reduce((x,t)=>x+t.hp,0));this.winner=hp[0]>=hp[1]?0:1}}
  }
  move(dt){for(const u of this.units){if(u.hp<=0)continue;const c=CARDS[u.type],foe=1-u.side;let tg=null,bd=1e9,isT=false;
    if(!c.bo)for(const e of this.units){if(e.side!==foe||e.hp<=0)continue;const d=dist(u,e);if(d<5.5&&d<bd){bd=d;tg=e}}
    if(!tg){const p=this.princess(foe,u.lane);tg=p.alive?p:this.tower(foe,'K');isT=true;bd=dist(u,tg)}
    const tr=isT?tg.r:CARDS[tg.type].r;u.cd-=dt;
    if(bd-tr-c.r<=c.range){u.act='attack';u.dir=facing(tg.x-u.x,tg.y-u.y,u.dir);
      if(u.cd<=0){u.cd=c.cd;
        if(c.splash){for(const e of this.units)if(e.side===foe&&e.hp>0&&Math.hypot(e.x-tg.x,e.y-tg.y)<=c.splash)this.hurt.push([e,c.dmg]);if(isT)this.hurt.push([tg,c.dmg]);this.fx.push({kind:'boom',side:u.side,x:tg.x,y:tg.y,t:this.t,r:c.splash})}
        else this.hurt.push([tg,c.dmg]);
        if(c.range>1)this.shots.push({side:u.side,k:c.splash?'bomb':'arrow',x1:u.x,y1:u.y,x2:tg.x,y2:tg.y,t:this.t});u.atk=this.t}}
    else{let tx=tg.x,ty=tg.y;const crossing=(u.y-RIVER)*(ty-RIVER)<0||Math.abs(u.y-RIVER)<1.4;
      if(crossing){const lx=LANES[u.lane];if(Math.abs(u.x-lx)>0.9){tx=lx;ty=u.y}else tx=u.x+(lx-u.x)*0.5}
      const d=Math.hypot(tx-u.x,ty-u.y)||1;u.act='walk';u.dir=facing(tx-u.x,ty-u.y,u.dir);u.x+=(tx-u.x)/d*c.speed*dt;u.y+=(ty-u.y)/d*c.speed*dt}}}
  separate(){const us=this.units;for(let i=0;i<us.length;i++)for(let j=i+1;j<us.length;j++){const a=us[i],b=us[j];if(a.side!==b.side)continue;
    const m=(CARDS[a.type].r+CARDS[b.type].r)*0.9,dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy);
    if(d>0.001&&d<m){const p=(m-d)/2;a.x-=dx/d*p;a.y-=dy/d*p;b.x+=dx/d*p;b.y+=dy/d*p}}}
  towersFire(dt){for(const tw of this.towers){if(!tw.alive)continue;tw.cd-=dt;if(tw.cd>0)continue;let tg=null,bd=tw.range;
    for(const e of this.units){if(e.side===tw.side||e.hp<=0)continue;const d=dist(tw,e);if(d<bd){bd=d;tg=e}}
    if(tg){tw.cd=tw.rate;this.hurt.push([tg,tw.dmg]);tw.aim=Math.atan2(tg.y-tw.y,tg.x-tw.x);this.shots.push({side:tw.side,k:'ball',x1:tw.x,y1:tw.y,x2:tg.x,y2:tg.y,t:this.t})}}}
}

Sim.prototype.frame=function(){
  const sides=this.sides.map(s=>{const p=s.pending,thinking=!!p&&!p.auto;
    const r6=s.lats.slice(-6);
    return{elixir:s.elixir,wasted:s.wasted,decisions:s.decisions,crowns:s.crowns,errors:0,
      thinking_since:thinking?p.start:null,last:s.last?{card:s.last.card,why:s.last.card?'push':'wait',lat:s.last.lat}:null,last_error:null,
      avg:r6.length?r6.reduce((a,b)=>a+b,0)/r6.length:null,recent:s.log.filter(d=>this.t-d.a<=10.5)}});
  return{t:this.t,dur:this.cfg.duration,over:this.over,winner:this.winner,reason:this.reason||'',
    units:this.units.map(u=>({id:u.id,side:u.side,type:u.type,x:u.x,y:u.y,hp:u.hp,max:u.max,atk:u.atk,hit:u.hit,cd:u.cd,dir:u.dir,act:u.act})),
    towers:this.towers.map(t=>({side:t.side,kind:t.kind,x:t.x,y:t.y,hp:t.hp,max:t.max,alive:t.alive,aim:t.aim,hit:t.hit})),
    shots:this.shots.slice(),fx:this.fx.slice(),sides,result:this.over?this.result():null};
};
Sim.prototype.result=function(){
  const avg=xs=>xs.length?xs.reduce((a,b)=>a+b,0)/xs.length:null;
  return{winner:this.winner,reason:this.reason,seconds:Math.round(this.t*10)/10,
    sides:this.sides.map(s=>({decisions:s.decisions,plays:s.plays,elixir_wasted:Math.round(s.wasted*10)/10,crowns:s.crowns,
      late_defences:s.late,failed_calls:0,invalid_moves:0,avg_decision_s:avg(s.lats),avg_model_ms:null}))};
};
window.DemoSim=Sim;
})();
