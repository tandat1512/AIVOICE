/* global React, ReactDOM, LiquidOrb, Icon, LangDropdown, LANGS, SPEAKERS, SG */
const { useState, useRef, useEffect, useCallback } = React;

/* speaker chip (diarization) — colored avatar + name from SPEAKERS */
function Spk({ i }){
  const s = (window.SPEAKERS && window.SPEAKERS[i]) || (window.SPEAKERS && window.SPEAKERS[0]);
  if(!s) return null;
  return (
    <span className="spk">
      <span className="spk-av" style={{background:s.color}}>{s.short}</span>
      <span className="spk-name" style={{color:s.color}}>{s.name}</span>
    </span>
  );
}

function buildStatus(sttModel, translateModel){
  const sttLabel = sttModel === 'sherpa' ? 'Sherpa 30M'
    : sttModel === 'dual'        ? 'Sherpa + EraX'
    : sttModel === 'whisper'     ? 'EraX Whisper'
    : 'Sherpa + PhoWhisper';
  const trLabel = translateModel === 'marian'   ? 'MarianMT'
    : translateModel === 'nllb-1.3b' ? 'NLLB 1.3B'
    : 'NLLB 600M';
  return {
    idle:        { state:'Sẵn sàng',    sub:'Nhấn Bắt đầu để nghe' },
    connecting:  { state:'Đang kết nối', sub:'Mở phiên dịch realtime' },
    loading:     { state:'Đang tải',    sub:'Nạp mô hình STT…' },
    listening:   { state:'Đang nghe',   sub:`STT · ${sttLabel}` },
    translating: { state:'Đang dịch',   sub:`${trLabel}` },
    speaking:    { state:'Đang đọc',    sub:'TTS · Kokoro' },
  };
}

// STT default backend. 'dual' = Sherpa 30M streaming display (<300ms interim)
// + EraX Whisper verify pass for accuracy + punctuation, which NLLB needs to
// translate well. Both models are installed and fit this 4GB GPU. Users can
// still pick another backend the server advertises (see /api/models).
const STT_BACKEND = 'sherpa';

/* =================== Translate Studio =================== */
function Studio({ colors, glow, bars, panelSolid, settings, source, setSource, srcLang, setSrcLang, tgtLang, setTgtLang, openSettings }){
  const [mode,setMode]       = useState('idle');     // idle|listening|translating|speaking
  const [status,setStatus]   = useState('idle');     // idle|connecting|loading|listening|...
  const [running,setRunning] = useState(false);
  const [committed,setCommitted] = useState('');     // source transcript (finalized)
  const [interim,setInterim]     = useState('');     // source transcript (live)
  const [tgtChunks,setTgtChunks] = useState([]);     // [{id,text}] translated sentences
  const [tgtPreview,setTgtPreview] = useState('');   // streaming in-progress translation
  const [latency,setLatency] = useState(0);
  const [loading,setLoading] = useState(false);      // model-loading card
  const [micError,setMicError] = useState(null);
  const [conn,setConn]       = useState('idle');     // tab/Meet capture state
  const [caption,setCaption] = useState(false);
  const [fontScale,setFontScale] = useState(1);
  const [scrollLock,setScrollLock] = useState(true);
  const [toast,setToast]     = useState(null);
  const [ytUrl,setYtUrl]     = useState('');
  const [ytSegs,setYtSegs]   = useState([]);   // [{id,start,dur,text,translated,audioReady}]
  const [ytActiveIdx,setYtActiveIdx] = useState(-1);

  const sessionRef = useRef(null);
  const levelRef   = useRef(0);                       // mic amplitude → orb
  const srcBody = useRef(null), tgtBody = useRef(null);
  const ytHostRef  = useRef(null);                   // embedded YouTube player host
  const ytSegRefs  = useRef([]);                     // per-segment DOM nodes for auto-scroll

  function fmtTime(sec){ const s=Math.max(0,Number(sec)||0),m=Math.floor(s/60),r=Math.floor(s%60); return m+':'+(r<10?'0':'')+r; }

  useEffect(()=>{ if(scrollLock && srcBody.current) srcBody.current.scrollTop = srcBody.current.scrollHeight; },[committed,interim,scrollLock]);
  useEffect(()=>{ if(scrollLock && tgtBody.current) tgtBody.current.scrollTop = tgtBody.current.scrollHeight; },[tgtChunks,tgtPreview,scrollLock]);
  useEffect(()=>{ if(!running) setConn('idle'); },[source,running]);
  useEffect(()=>()=>{ if(sessionRef.current) sessionRef.current.stop(); },[]);
  useEffect(()=>{
    if(!scrollLock||source!=='youtube'||ytActiveIdx<0||!srcBody.current) return;
    const node=ytSegRefs.current[ytActiveIdx]; if(!node) return;
    const c=srcBody.current;
    const top=c.scrollTop+(node.getBoundingClientRect().top-c.getBoundingClientRect().top)-(c.clientHeight-node.clientHeight)/2;
    c.scrollTo({top,behavior:'smooth'});
  },[ytActiveIdx,scrollLock]);

  // live-apply settings to an active session
  useEffect(()=>{ if(sessionRef.current) sessionRef.current.setSpeed(settings.speed); },[settings.speed]);
  useEffect(()=>{ if(sessionRef.current && settings.voice) sessionRef.current.setVoice(settings.voice); },[settings.voice]);
  useEffect(()=>{ if(sessionRef.current) sessionRef.current.setVad(settings.vad); },[settings.vad]);

  function flash(msg){ setToast(msg); setTimeout(()=>setToast(null),1600); }

  /* ---- start / stop the real backend session ---- */
  function start(){
    if(running || !window.SG){ if(!window.SG) flash('Backend chưa sẵn sàng'); return; }
    setMicError(null);
    setCommitted(''); setInterim(''); setTgtChunks([]); setTgtPreview(''); setLatency(0);
    setRunning(true); setLoading(true); setStatus('connecting');
    if(source!=='mic') setConn('connecting');

    if(source==='youtube'){
      const sess = window.SG.createYoutubeDub({
        url: ytUrl,
        hostEl: ytHostRef.current,
        tgt: tgtLang,
        voice: settings.voice,
        speed: settings.speed,
        onStatus: (s)=>{ setStatus(s); if(s==='loading') setLoading(true); },
        onReady: ()=>{ setLoading(false); setConn('connected'); },
        onMode:  (m)=> setMode(m),
        onTranscript: ({segments,currentIdx})=>{ setYtSegs(segments||[]); setYtActiveIdx(typeof currentIdx==='number'?currentIdx:-1); },
        onTranslation: ({committed,preview})=>{ setTgtChunks(committed); setTgtPreview(preview); },
        onError: (msg)=>{ setRunning(false); setLoading(false); setConn('idle'); setStatus('idle'); setMode('idle'); setMicError(msg); },
        onClose: ()=>{ setRunning(false); setMode('idle'); setStatus('idle'); setLoading(false); setConn('idle'); setYtSegs([]); setYtActiveIdx(-1); },
      });
      sessionRef.current = sess;
      sess.start();
      return;
    }

    const sess = window.SG.createSession({
      src: srcLang, tgt: tgtLang,
      backend: settings.sttModel || STT_BACKEND,
      translateModel: settings.translateModel || '',
      voice: settings.voice, speed: settings.speed, muted: false,
      vad: settings.vad,
      source,
      levelRef,
      onStatus: (s)=>{ setStatus(s); if(s==='loading') setLoading(true); },
      onReady: ()=>{ setLoading(false); if(source!=='mic') setConn('connected'); },
      onMode:  (m)=> setMode(m),
      onTranscript: ({committed,interim})=>{ setCommitted(committed); setInterim(interim); },
      onTranslation: ({committed,preview})=>{ setTgtChunks(committed); setTgtPreview(preview); },
      onLatency: (ms)=> setLatency(ms),
      onError: (msg)=>{
        // Reset running so the user can click Bắt đầu again after an error
        setRunning(false); setLoading(false); setConn('idle'); setStatus('idle'); setMode('idle');
        setMicError(msg);
      },
      onClose: ()=>{ setRunning(false); setMode('idle'); setStatus('idle'); setLoading(false); setConn('idle'); },
    });
    sessionRef.current = sess;
    sess.start();
  }

  function stop(){
    if(sessionRef.current){ sessionRef.current.stop(); sessionRef.current=null; }
    setRunning(false); setMode('idle'); setStatus('idle'); setLoading(false); setConn('idle'); setInterim('');
    setYtSegs([]); setYtActiveIdx(-1);
  }

  function clearAll(){ setCommitted(''); setInterim(''); setTgtChunks([]); setTgtPreview(''); setYtSegs([]); setYtActiveIdx(-1); }

  // For tab/Meet sources the "Kết nối" button starts the session — capture happens
  // through getDisplayMedia inside start().
  function connect(){ start(); }

  function changeLang(s,t){
    setSrcLang(s); setTgtLang(t);
    if(sessionRef.current) sessionRef.current.setLang(s,t);
  }

  async function replay(text){
    if(running || !text) return;
    setMode('speaking');
    try{ await window.SG.ttsSay(text, { voice: settings.voice, speed: settings.speed }); }
    catch(e){ flash('Không phát được giọng đọc'); }
    setMode('idle');
  }

  function copyPane(which){
    const txt = which==='src' ? committed : tgtChunks.map(c=>c.text).join('\n');
    if(navigator.clipboard) navigator.clipboard.writeText(txt);
    flash('Đã sao chép bản ghi');
  }
  function exportTxt(){
    const body = tgtChunks.map(c=>`${LANGS[tgtLang].code}: ${c.text}`).join('\n');
    const head = 'SmartGen — '+LANGS[srcLang].name+' → '+LANGS[tgtLang].name+'\n\n';
    const blob = new Blob([head + LANGS[srcLang].code + ': ' + committed + '\n\n' + body], {type:'text/plain'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='smartgen-transcript.txt'; a.click();
  }

  const STATUS = buildStatus(settings.sttModel || STT_BACKEND, settings.translateModel || 'nllb-600m');
  const _ytTotal = ytSegs.length;
  const _ytTr    = ytSegs.filter(s=>s.translated!==null).length;
  const _ytTts   = ytSegs.filter(s=>s.audioReady).length;
  const YT_STATUS = {
    idle:        { state:'Sẵn sàng',        sub:'Dán link rồi nhấn Bắt đầu' },
    connecting:  { state:'Đang tải',        sub:'Đang lấy phụ đề video…' },
    loading:     { state:'Đang tải',        sub:_ytTotal?`${_ytTotal} đoạn phụ đề`:'Đang lấy phụ đề video…' },
    listening:   { state:'Sẵn sàng',        sub:_ytTotal?`Dịch ${_ytTr}/${_ytTotal} · TTS ${_ytTts}/${_ytTotal}`:'Nhấn Play để bắt đầu lồng tiếng' },
    translating: { state:'Đang lồng tiếng', sub:`Dịch ${_ytTr}/${_ytTotal} · TTS ${_ytTts}/${_ytTotal}` },
    speaking:    { state:'Đang lồng tiếng', sub:'Phụ đề → bản dịch → giọng đọc' },
  };
  // Dynamic status strings from the health-poll phase (e.g. "Chờ server… (3)") fall
  // through to a generic label; map them to a displayable pair.
  const rawStatus = mode === 'idle' ? status : mode;
  const st = (source==='youtube' ? YT_STATUS : STATUS)[rawStatus] || {
    state: 'Đang chờ server',
    sub: rawStatus,  // show the live "Chờ server… (N)" as subtitle
  };
  const ttsActive = mode==='speaking';
  const SL = LANGS[srcLang], TL = LANGS[tgtLang];
  const bodyStyle = { fontSize: (1*fontScale)+'rem' };
  const lastTgt = tgtChunks[tgtChunks.length-1];
  const hasSrc = committed || interim;
  const hasDiarization = tgtChunks.some(c=>c.speaker>0);   // only show speaker chips when >1 speaker detected

  return (
    <div className="scene">
      {/* top bar */}
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Realtime Voice Translate</div></div>
        </div>
        <div className="spacer"></div>
        <div className="seg" role="tablist">
          <button className={source==='mic'?'on':''} onClick={()=>!running&&setSource('mic')}><Icon name="mic"/>Mic</button>
          <button className={source==='youtube'?'on':''} onClick={()=>!running&&setSource('youtube')}><Icon name="youtube"/>YouTube</button>
          <button className={source==='meet'?'on':''} onClick={()=>!running&&setSource('meet')}><Icon name="meet"/>Meet</button>
        </div>
        <div className={'icon-btn'+(caption?' active':'')} title="Chế độ phụ đề" onClick={()=>setCaption(c=>!c)}><Icon name="cc"/></div>
        <div className="icon-btn" title="Cài đặt" onClick={openSettings}><Icon name="gear"/></div>
      </div>

      {/* language selectors */}
      <div className="langbar">
        <LangDropdown value={srcLang} onChange={(v)=>changeLang(v,tgtLang)} label="Ngôn ngữ nguồn"/>
        <div className="swap" title="Đảo chiều" onClick={()=>changeLang(tgtLang,srcLang)}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={(v)=>changeLang(srcLang,v)} label="Ngôn ngữ dịch"/>
      </div>

      {/* three-column stage */}
      <div className="stage">
        {/* SOURCE pane */}
        <div className={'pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>{source==='youtube' ? 'Lồng tiếng' : ('Phiên âm · '+SL.name)}</h3>
            <div className="pane-tools">
              <button className="ptool" title="Thu nhỏ chữ" onClick={()=>setFontScale(s=>Math.max(.85,+(s-.1).toFixed(2)))}><Icon name="minus"/></button>
              <button className="ptool" title="Phóng chữ" onClick={()=>setFontScale(s=>Math.min(1.35,+(s+.1).toFixed(2)))}><Icon name="plus"/></button>
              <button className={'ptool'+(scrollLock?' on':'')} title="Khóa auto-scroll" onClick={()=>setScrollLock(v=>!v)}><Icon name={scrollLock?'lock':'unlock'}/></button>
              <button className="ptool" title="Sao chép" onClick={()=>copyPane('src')}><Icon name="copy"/></button>
            </div>
          </div>
          <div className="pane-body" ref={srcBody} style={bodyStyle}>
            {source==='youtube' ? (
              ytSegs.length===0 ? (
                <div className="empty-hint">Dán link YouTube rồi nhấn <b>Bắt đầu</b>.<br/>Phụ đề gốc và bản dịch sẽ xuất hiện ở đây, tự bám theo video.</div>
              ) : (
                <React.Fragment>
                  {ytSegs.map((seg,i)=>(
                    <div key={seg.id}
                      ref={el=>ytSegRefs.current[i]=el}
                      className={'audio-seg'+(i===ytActiveIdx?' active':'')}
                      style={{opacity:seg.audioReady?1:seg.translated!==null?0.75:0.45,transition:'opacity 0.3s'}}>
                      <div className="audio-time">{fmtTime(seg.start)}</div>
                      <div className="audio-src">{seg.text}</div>
                      {seg.translated!==null&&seg.translated!==''&&<div className="audio-tgt">{seg.translated}</div>}
                    </div>
                  ))}
                </React.Fragment>
              )
            ) : (
              <React.Fragment>
                {!hasSrc && (
                  <div className="empty-hint">Nguồn âm thanh sẽ xuất hiện ở đây.<br/>Chọn <span className="k">{source==='mic'?'Mic':'Meet'}</span> rồi nhấn <span className="k">Bắt đầu</span>.</div>
                )}
                {hasSrc && (
                  <p className="line">
                    <span>{committed}</span>{committed && interim ? ' ' : ''}
                    {interim && <span className="interim">{interim}</span>}
                    {running && <span className="caret"></span>}
                  </p>
                )}
              </React.Fragment>
            )}
          </div>
        </div>

        {/* CENTER orb */}
        <div className="center">
          <div className="pipe">
            <div className={'chip'+(mode!=='idle'?' on':'')}><span className="led"></span>{source==='youtube'?'Phụ đề':'STT'}</div>
            <span className="arrow"><Icon name="arrow" width="13" height="13"/></span>
            <div className={'chip'+(mode==='translating'||mode==='speaking'?' on':'')}><span className="led"></span>Dịch</div>
            <span className="arrow"><Icon name="arrow" width="13" height="13"/></span>
            <div className={'chip'+(mode==='speaking'?' on':'')}><span className="led"></span>TTS</div>
          </div>

          <div className="orb-wrap">
            {source==='youtube'
              ? <div className="yt-embed" ref={ytHostRef}></div>
              : <LiquidOrb mode={mode} colors={colors} glow={glow} bars={bars} levelRef={levelRef}/>}
            {loading && source!=='youtube' && (
              <div className="load-card">
                <div className="load-title">Đang kết nối mô hình AI…</div>
                <div className="load-row">
                  <div className="load-row-top">
                    <span>STT · Sherpa + PhoWhisper</span>
                    <span className="load-pct"><span className="spin"></span></span>
                  </div>
                  <div className="load-bar"><i className="indet"></i></div>
                </div>
              </div>
            )}
          </div>
          <div className="orb-status">
            <div className="state">{st.state}</div>
            <div className="sub">{st.sub}</div>
          </div>

          {source!=='mic' && (
            <div className={'urlbar '+conn}>
              <Icon name={source==='youtube'?'youtube':'meet'}/>
              {source==='youtube'
                ? <input
                    value={ytUrl}
                    onChange={e=>setYtUrl(e.target.value)}
                    placeholder="Dán link YouTube (https://youtu.be/...)"
                    disabled={running}
                  />
                : <input
                    defaultValue={
                      conn==='connected'
                        ? 'Google Meet đang phát truyền âm thanh'
                        : 'Nhấn Bắt đầu → chọn tab Google Meet → bật “Chia sẻ âm thanh tab”'
                    }
                    readOnly
                  />}
              {conn==='connected'
                ? <span className="conn-ok"><Icon name="check" width="14" height="14"/>{source==='youtube'?'Đang lồng tiếng':'Kết nối thành công'}</span>
                : conn==='connecting'
                  ? <span className="conn-ok" style={{opacity:.6}}><span className="spin"></span></span>
                  : null}
            </div>
          )}

          {micError && <div className="mic-err"><Icon name="alert" width="15" height="15"/>{micError}</div>}

          <div className="controls">
            <button className={'rec-btn'+(running?' live':'')} onClick={()=>running?stop():start()}>
              <span className="pulse"></span>{running?'Dừng lại':'Bắt đầu'}
            </button>
            <div className="ghost-btn" title="Tải bản ghi (.txt)" onClick={exportTxt}><Icon name="download"/></div>
            <div className="ghost-btn" title="Xóa hội thoại" onClick={clearAll}><Icon name="clear"/></div>
          </div>
          <div className="latency">Độ trễ <b>{latency||'—'}{latency?'ms':''}</b> · {source==='mic'?'Micro':source==='youtube'?'YouTube':'Google Meet (tab)'}</div>
        </div>

        {/* TARGET pane */}
        <div className={'pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Bản dịch · {TL.name}</h3>
            <span className={'live-tts'+(ttsActive?' on':'')}><span className="bars"><i></i><i></i><i></i><i></i></span> TTS</span>
            <div className="pane-tools">
              <button className="ptool" title="Sao chép" onClick={()=>copyPane('tgt')}><Icon name="copy"/></button>
            </div>
          </div>
          <div className="pane-body" ref={tgtBody} style={bodyStyle}>
            {tgtChunks.length===0 && !tgtPreview && (
              <div className="empty-hint">Bản dịch <span className="k">{TL.en}</span> realtime<br/>sẽ chạy song song tại đây.</div>
            )}
            {tgtChunks.map((c,i)=>{
              const isLast = i===tgtChunks.length-1;
              const speaking = ttsActive && isLast;
              const showSpk = hasDiarization && (i===0 || tgtChunks[i-1].speaker !== c.speaker);
              return (
                <p key={c.id} className={'line translated'+(speaking?' active':'')}>
                  {showSpk && <Spk i={c.speaker||0}/>}
                  {c.text}
                  {speaking
                    ? <span className="ttsmark"><Icon name="speaker" width="15" height="15"/></span>
                    : (!running && <button className="replay" title="Đọc lại" onClick={()=>replay(c.text)}><Icon name="replay" width="14" height="14"/></button>)}
                </p>
              );
            })}
            {tgtPreview && (
              <p className="line translated"><span className="interim">{tgtPreview}</span><span className="caret"></span></p>
            )}
          </div>
        </div>
      </div>

      {/* caption overlay */}
      {caption && (
        <div className="caption-overlay">
          <button className="cap-close" onClick={()=>setCaption(false)}><Icon name="x" width="16" height="16"/></button>
          {hasSrc && <div className="cap-src">{committed} {interim}</div>}
          <div className="cap-tgt">{lastTgt ? lastTgt.text : (tgtPreview || 'Phụ đề dịch sẽ hiển thị tại đây…')}</div>
        </div>
      )}

      {toast && <div className="toast"><Icon name="check" width="15" height="15"/>{toast}</div>}
    </div>
  );
}
window.Studio = Studio;
