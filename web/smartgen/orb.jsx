/* global React */
// LiquidOrb — canvas liquid blob + circular waveform ring.
// props: mode ('idle'|'listening'|'translating'|'speaking'), level (0..1 override), colors {a,b,c}, glow
const { useRef, useEffect } = React;

function hexToRgb(h){
  h = h.replace('#','');
  if(h.length===3) h = h.split('').map(c=>c+c).join('');
  const n = parseInt(h,16);
  return [(n>>16)&255,(n>>8)&255,n&255];
}
function rgba(c,a){ const [r,g,b]=hexToRgb(c); return `rgba(${r},${g},${b},${a})`; }

function LiquidOrb({ mode='idle', colors, glow=1, bars=true, dense=1, levelRef=null }){
  const ref = useRef(null);
  const state = useRef({ amp:0.06, target:0.06, t:0, blink:1, raf:0, mode, levelRef });
  useEffect(()=>{ state.current.mode = mode; }, [mode]);
  useEffect(()=>{ state.current.levelRef = levelRef; }, [levelRef]);

  useEffect(()=>{
    const cv = ref.current;
    const ctx = cv.getContext('2d');
    let dpr = Math.min(window.devicePixelRatio||1, 2);
    function size(){
      const r = cv.getBoundingClientRect();
      cv.width = Math.max(2, r.width*dpr); cv.height = Math.max(2, r.height*dpr);
    }
    size();
    const ro = new ResizeObserver(size); ro.observe(cv);

    const C = colors || { a:'#22d3ee', b:'#3b82f6', c:'#6366f1' };

    // smooth pseudo-audio envelopes per mode
    let env = 0, envV = 0, syl = 0;
    function blobPath(cx,cy,baseR,amp,t,seed,wob){
      const N=72, pts=[];
      for(let i=0;i<N;i++){
        const a=(i/N)*Math.PI*2;
        const n = Math.sin(a*3 + t*1.25 + seed)*0.5
                + Math.sin(a*5 - t*0.95 + seed*2)*0.28
                + Math.sin(a*2 + t*0.62 + seed)*0.22
                + Math.sin(a*7 + t*1.7)*0.12;
        const r = baseR*(1 + n*wob*(0.55+amp*0.9));
        pts.push([cx+Math.cos(a)*r, cy+Math.sin(a)*r]);
      }
      ctx.beginPath();
      const last=pts[N-1];
      ctx.moveTo((last[0]+pts[0][0])/2,(last[1]+pts[0][1])/2);
      for(let i=0;i<N;i++){
        const p=pts[i], nx=pts[(i+1)%N];
        ctx.quadraticCurveTo(p[0],p[1],(p[0]+nx[0])/2,(p[1]+nx[1])/2);
      }
      ctx.closePath();
    }

    function frame(){
      const S = state.current;
      const w=cv.width, h=cv.height, cx=w/2, cy=h/2;
      const t = S.t += 0.016;
      const m = S.mode;

      // targets per mode
      let tgt=0.06, blinkTgt=1;
      const ext = S.levelRef && S.levelRef.current;
      if(m==='listening'){
        if(ext!=null && ext>0.0001){ tgt = 0.10 + Math.min(1, ext)*0.95; }   // real mic
        else { tgt = 0.35 + Math.abs(Math.sin(t*2.1))*0.3 + Math.random()*0.12; } // simulated
      }
      else if(m==='translating'){ tgt = 0.22 + Math.sin(t*3)*0.05; }
      else if(m==='speaking'){
        syl += 0.016;
        const s = Math.pow(Math.abs(Math.sin(syl*7)),1.7); // syllabic
        tgt = 0.4 + s*0.55;
        blinkTgt = 0.55 + s*0.45; // flash with syllables
      }
      S.target += (tgt - S.target)*0.12;
      S.amp += (S.target - S.amp)*0.18;
      S.blink += (blinkTgt - S.blink)*0.25;
      const amp = S.amp, blink = S.blink;

      ctx.clearRect(0,0,w,h);
      ctx.save();
      const base = Math.min(w,h)*0.205;
      const g = glow;

      // ---- waveform ring (undulating sound border) ----
      if(bars){
        const ringR = Math.min(w,h)*0.40;
        const NB = Math.round(76*dense);
        for(let i=0;i<NB;i++){
          const a=(i/NB)*Math.PI*2;
          const wob = (Math.sin(a*6 + t*2.2)*0.5+0.5)*0.5 + (Math.sin(a*11 - t*1.6)*0.5+0.5)*0.5;
          const len = (Math.min(w,h)*0.012) + amp*Math.min(w,h)*0.085*wob;
          const r1=ringR, r2=ringR+len;
          const x1=cx+Math.cos(a)*r1, y1=cy+Math.sin(a)*r1;
          const x2=cx+Math.cos(a)*r2, y2=cy+Math.sin(a)*r2;
          ctx.strokeStyle = rgba(i%2? C.a : C.b, (0.25+amp*0.55)*blink);
          ctx.lineWidth = Math.max(1.5, w*0.004);
          ctx.lineCap='round';
          ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
        }
      }

      // ---- outer glow halo ----
      const halo = ctx.createRadialGradient(cx,cy,base*0.4,cx,cy,base*2.4);
      halo.addColorStop(0, rgba(C.b, 0.30*g*blink));
      halo.addColorStop(0.5, rgba(C.c, 0.16*g*blink));
      halo.addColorStop(1, rgba(C.c, 0));
      ctx.fillStyle=halo;
      ctx.fillRect(0,0,w,h);

      // ---- main blob with glow ----
      ctx.save();
      ctx.shadowColor = rgba(C.b, 0.85*g*blink);
      ctx.shadowBlur = base*0.9*g;
      const grad = ctx.createLinearGradient(cx-base,cy-base,cx+base,cy+base);
      grad.addColorStop(0, C.a);
      grad.addColorStop(0.55, C.b);
      grad.addColorStop(1, C.c);
      ctx.fillStyle=grad;
      blobPath(cx,cy,base*(1+amp*0.16),amp,t,0,0.085);
      ctx.fill();
      ctx.restore();

      // inner darker core for depth
      ctx.globalCompositeOperation='source-atop';
      const core = ctx.createRadialGradient(cx-base*0.25,cy-base*0.3,base*0.1,cx,cy,base*1.2);
      core.addColorStop(0, rgba('#ffffff',0.45));
      core.addColorStop(0.35, rgba(C.a,0.0));
      core.addColorStop(1, rgba('#04060c',0.55));
      ctx.fillStyle=core;
      blobPath(cx,cy,base*(1+amp*0.16),amp,t,0,0.085);
      ctx.fill();
      ctx.globalCompositeOperation='source-over';

      // bright rim
      ctx.strokeStyle = rgba('#ffffff', 0.5*blink);
      ctx.lineWidth = Math.max(1, w*0.003);
      blobPath(cx,cy,base*(1+amp*0.16),amp,t,0,0.085);
      ctx.stroke();

      // secondary inner blob (counter-rotating)
      ctx.globalAlpha=0.5;
      const g2=ctx.createLinearGradient(cx+base,cy-base,cx-base,cy+base);
      g2.addColorStop(0, rgba(C.a,0.8)); g2.addColorStop(1, rgba(C.c,0.4));
      ctx.fillStyle=g2;
      blobPath(cx,cy,base*0.62*(1+amp*0.2),amp,-t*0.8,3.2,0.13);
      ctx.fill();
      ctx.globalAlpha=1;

      ctx.restore();
      S.raf = requestAnimationFrame(frame);
    }
    frame();
    return ()=>{ cancelAnimationFrame(state.current.raf); ro.disconnect(); };
  }, [colors, glow, bars, dense]);

  return React.createElement('canvas', { ref });
}
window.LiquidOrb = LiquidOrb;
