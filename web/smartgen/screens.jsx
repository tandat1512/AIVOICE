/* global React, LiquidOrb, Icon, LangDropdown, LANGS */
const { useState:uS, useEffect:uE, useRef:uR } = React;

/* auto-cycling orb for showcase areas */
function ShowcaseOrb({ colors, glow=1.1, bars=true, cycle=['listening','translating','speaking','listening','idle'] }){
  const [mode,setMode]=uS('listening');
  uE(()=>{
    let i=0; const id=setInterval(()=>{ i=(i+1)%cycle.length; setMode(cycle[i]); }, 2600);
    return ()=>clearInterval(id);
  },[]);
  return <LiquidOrb mode={mode} colors={colors} glow={glow} bars={bars}/>;
}

/* =================== Landing =================== */
function Landing({ colors, bars }){
  const FEATS = [
    { ic:'bolt',   h:'Streaming < 100ms',  p:'Tầng STT kép Sherpa-ONNX + PhoWhisper cho bản xem trước tức thời rồi tự hiệu đính tại điểm ngắt câu.' },
    { ic:'shield', h:'Chạy cục bộ 100%',   p:'Không Deepgram, không cloud STT, không API trả phí. Mọi cuộc trò chuyện không rời khỏi máy của bạn.' },
    { ic:'waves',  h:'STT → Dịch → TTS',   p:'Nhận dạng, dịch bằng MarianMT và đọc lại bằng giọng tổng hợp — liền mạch trong một luồng.' },
    { ic:'youtube',h:'Mọi nguồn âm thanh', p:'Bắt audio từ micro, video YouTube hay cuộc họp Google Meet chỉ bằng một cú nhấp.' },
    { ic:'globe',  h:'Đa ngôn ngữ',        p:'Việt ↔ Anh và mở rộng sang Nhật, Hàn, Trung, Pháp với cùng một pipeline.' },
    { ic:'layers', h:'Chống ảo giác',      p:'Heuristic an toàn loại bỏ vòng lặp "hallucination" của Whisper khi có tiếng ồn nền.' },
  ];
  return (
    <div className="landing">
      <div className="app-bg"><div className="aurora a1"></div><div className="aurora a2"></div></div>
      <div className="nav">
        <div className="brand" onClick={()=>window.__go('app')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div></div>
        </div>
        <div style={{flex:1}}></div>
        <a onClick={()=>window.__go('app')}>Studio</a>
        <a onClick={()=>window.__go('text')}>Text</a>
        <a onClick={()=>window.__go('currency')}>Currency</a>
        <a onClick={()=>window.__go('image')}>Image</a>
        <a onClick={()=>window.__go('audio')}>Audio</a>
        <a onClick={()=>window.__go('travel')}>Travel</a>
        <a onClick={()=>window.__go('glossary')}>Glossary</a>
        <a onClick={()=>window.__go('extension')}>Extension</a>
        <a href="https://github.com/tandat1512/AIVOICE" target="_blank">GitHub</a>
        <a className="cta" onClick={()=>window.__go('app')}>Mở ứng dụng</a>
      </div>

      <div className="hero">
        <div>
          <span className="eyebrow"><span className="dot"></span>REALTIME · STT → TTS · 100% OPEN-SOURCE</span>
          <h1>Dịch giọng nói<br/><span className="grad">trực tiếp</span>, không độ trễ.</h1>
          <p>SmartGen lắng nghe micro, YouTube hay Google Meet, phiên âm và dịch ngay tức thì giữa Tiếng Việt và Tiếng Anh — rồi đọc lại bằng giọng tổng hợp mượt mà.</p>
          <div className="btns">
            <button className="primary" onClick={()=>window.__go('app')}>Bắt đầu dịch <Icon name="arrow"/></button>
            <button className="secondary" onClick={()=>window.__go('extension')}>Xem Extension</button>
          </div>
          <div className="hero-stats">
            <div className="s"><b className="g">&lt;100ms</b><span>Độ trễ</span></div>
            <div className="s"><b>2 tầng</b><span>STT engine</span></div>
            <div className="s"><b>6+</b><span>Ngôn ngữ</span></div>
          </div>
        </div>
        <div className="hero-orb"><ShowcaseOrb colors={colors} bars={bars}/></div>
      </div>

      <div className="feat">
        <h2>Một pipeline, năm bước, không khoảng nghỉ.</h2>
        <p className="sub">Tái hiện sơ đồ thiết kế gốc nhưng hoàn toàn mã nguồn mở và chạy cục bộ.</p>
        <div className="pipeline-viz">
          {[['Micro','PCM 16kHz'],['STT kép','Sherpa + PhoWhisper'],['MarianMT','Dịch'],['Delta','Diff renderer'],['Hiển thị + TTS','Giọng đọc']].map((n,i,a)=>(
            <React.Fragment key={i}>
              <div className="pv-node"><div className="b">{n[0]}</div><small>{n[1]}</small></div>
              {i<a.length-1 && <span className="pv-arrow">→</span>}
            </React.Fragment>
          ))}
        </div>
        <div className="feat-grid" style={{marginTop:18}}>
          {FEATS.map((f,i)=>(
            <div className="card" key={i}>
              <div className="ic"><Icon name={f.ic}/></div>
              <h4>{f.h}</h4><p>{f.p}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="foot">
        <span>SmartGen — realtime streaming translate · no paid APIs</span>
        <span>VI ↔ EN · STT-TTS · 2026</span>
      </div>
    </div>
  );
}
window.Landing = Landing;

/* =================== Settings Modal =================== */
function SettingsModal({ settings, setSettings, onClose }){
  const set = (k,v)=>setSettings(s=>({...s,[k]:v}));
  const [voices,setVoices]           = uS([]);
  const [sttModels,setSttModels]     = uS([]);
  const [trModels,setTrModels]       = uS([]);

  uE(()=>{
    if(!window.SG) return;
    window.SG.fetchVoices().then(d=>{
      setVoices(d.voices||[]);
      if(!settings.voice && d.default) set('voice', d.default);
    }).catch(()=>{});
    window.SG.fetchSttModels().then(d=>{
      setSttModels(d.available||[]);
    }).catch(()=>{});
    window.SG.fetchTranslateModels().then(d=>{
      setTrModels(d.models||[]);
    }).catch(()=>{});
  },[]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="x" onClick={onClose}><Icon name="x" width="20" height="20"/></div>
        <h2>Cài đặt</h2>
        <p className="desc">Mô hình, giọng đọc và tốc độ phát.</p>

        <div className="field">
          <label>Mô hình nhận dạng (STT)</label>
          <select className="voice-select" value={settings.sttModel||'sherpa'}
                  onChange={e=>set('sttModel',e.target.value)}>
            {!sttModels.length && (
              <option value="sherpa">Sherpa + PhoWhisper Large (GPU ★★★)</option>
            )}
            {sttModels.map(m=>(
              <option key={m.id} value={m.backend||m.id}>{m.name}</option>
            ))}
          </select>
          {sttModels.find(m=>(m.backend||m.id)===( settings.sttModel||'sherpa')) && (
            <small style={{color:'var(--text-3)',marginTop:4,display:'block'}}>
              {sttModels.find(m=>(m.backend||m.id)===(settings.sttModel||'sherpa'))?.desc}
            </small>
          )}
        </div>

        <div className="field">
          <label>Mô hình dịch</label>
          <select className="voice-select" value={settings.translateModel||'nllb-600m'}
                  onChange={e=>set('translateModel',e.target.value)}>
            {!trModels.length && <option value="nllb-600m">NLLB-200 distilled (600M)</option>}
            {trModels.map(m=>(
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Giọng đọc (TTS)</label>
          <select className="voice-select" value={settings.voice||''} onChange={e=>set('voice',e.target.value)}>
            {!voices.length && <option value="">(mặc định máy chủ)</option>}
            {voices.map(v=>(
              <option key={v.id} value={v.id}>{v.name||v.id}{v.lang?' · '+v.lang:''}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Tốc độ đọc</label>
          <div className="slider-row">
            <input type="range" min="0.5" max="2" step="0.1" value={settings.speed} onChange={e=>set('speed',parseFloat(e.target.value))}/>
            <span className="val">{settings.speed.toFixed(1)}×</span>
          </div>
        </div>

        <div className="field">
          <label>Độ trễ ngắt câu (VAD)</label>
          <div className="slider-row">
            <input type="range" min="200" max="1000" step="50" value={settings.vad} onChange={e=>set('vad',parseInt(e.target.value))}/>
            <span className="val">{settings.vad}ms</span>
          </div>
        </div>

        <button className="primary" onClick={onClose}>Lưu thay đổi</button>
      </div>
    </div>
  );
}
window.SettingsModal = SettingsModal;

const REST_LANG = {
  vi: 'vie_Latn',
  en: 'eng_Latn',
  ja: 'jpn_Jpan',
  ko: 'kor_Hang',
  zh: 'zho_Hans',
  fr: 'fra_Latn',
};

const CURRENCIES = ['VND','USD','EUR','JPY','KRW','CNY','GBP','AUD','CAD','SGD','THB'];
const OCR_ENGINES = [
  ['auto','Auto'],
  ['google','Google Vision'],
  ['paddle','PaddleOCR'],
  ['tesseract','Tesseract'],
  ['none','Off'],
];

function TextTranslateStudio({ panelSolid, settings, srcLang, setSrcLang, tgtLang, setTgtLang, openSettings }){
  const [text,setText] = uS('Xin chào, tôi muốn đặt phòng cho tối nay.');
  const [loading,setLoading] = uS(false);
  const [result,setResult] = uS(null);
  const [err,setErr] = uS('');
  const [trModels,setTrModels] = uS([]);
  const [toast,setToast] = uS(null);
  const [useGlossary,setUseGlossary] = uS(true);

  uE(()=>{
    if(!window.SG) return;
    window.SG.fetchTranslateModels().then(d=>setTrModels(d.models||[])).catch(()=>{});
  },[]);

  function flash(msg){ setToast(msg); setTimeout(()=>setToast(null),1600); }
  function swap(){ setSrcLang(tgtLang); setTgtLang(srcLang); }

  async function translate(){
    const clean = text.trim();
    if(!clean){ setErr('Nhập văn bản cần dịch.'); return; }
    setLoading(true); setErr('');
    try{
      const data = await window.SG.translateText({
        text: clean,
        src_lang: REST_LANG[srcLang] || srcLang,
        tgt_lang: REST_LANG[tgtLang] || tgtLang,
        translate_model: settings.translateModel || 'nllb-600m',
        use_glossary: useGlossary,
      });
      setResult(data);
    }catch(e){
      setErr(e.message || 'Dịch thất bại.');
    }finally{
      setLoading(false);
    }
  }

  function copy(textToCopy){
    if(navigator.clipboard) navigator.clipboard.writeText(textToCopy || '');
    flash('Đã sao chép');
  }

  async function replay(){
    if(!result?.translated_text || tgtLang!=='en') return;
    try{ await window.SG.ttsSay(result.translated_text, { voice: settings.voice, speed: settings.speed }); }
    catch(e){ flash('Không phát được giọng đọc'); }
  }

  function exportResult(format){
    if(!result) return;
    window.SG.exportFile({
      format,
      title:'SmartGen Text Translate',
      source_text:result.source_text,
      translated_text:result.translated_text,
    }).catch(e=>flash(e.message || 'Export thất bại'));
  }

  const selectedModel = trModels.find(m=>m.id===(settings.translateModel||'nllb-600m'));

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Text Translate</div></div>
        </div>
        <div className="spacer"></div>
        <div className="icon-btn" title="Cài đặt" onClick={openSettings}><Icon name="gear"/></div>
      </div>

      <div className="langbar">
        <LangDropdown value={srcLang} onChange={setSrcLang} label="Ngôn ngữ nguồn"/>
        <div className="swap" title="Đảo chiều" onClick={swap}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={setTgtLang} label="Ngôn ngữ dịch"/>
      </div>

      <div className="text-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>Văn bản nguồn</h3>
            <div className="pane-tools">
              <button className="ptool" title="Xóa" onClick={()=>{setText('');setResult(null);}}><Icon name="clear"/></button>
            </div>
          </div>
          <textarea className="text-input" value={text} onChange={e=>setText(e.target.value)} spellCheck="false"/>
          {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
          <div className="text-actions">
            <button className="rec-btn" onClick={translate} disabled={loading}>
              <span className="pulse"></span>{loading?'Đang dịch...':'Translate'}
            </button>
            <span className="latency">{selectedModel ? selectedModel.name : (settings.translateModel || 'nllb-600m')}</span>
            <label className="mini-check"><input type="checkbox" checked={useGlossary} onChange={e=>setUseGlossary(e.target.checked)}/> Glossary</label>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Kết quả</h3>
            <div className="pane-tools">
              <button className="ptool" title="Sao chép" onClick={()=>copy(result?.translated_text)}><Icon name="copy"/></button>
              <button className="ptool" title="Đọc lại" onClick={replay} disabled={tgtLang!=='en' || !result?.translated_text}><Icon name="speaker"/></button>
            </div>
          </div>
          <div className="text-result">
            {!result && <div className="empty-hint">Bản dịch sẽ hiển thị ở đây.</div>}
            {result && (
              <React.Fragment>
                <p className="line translated">{result.translated_text}</p>
                <div className="export-row">
                  {['txt','json','docx'].map(f=><button key={f} onClick={()=>exportResult(f)}>{f.toUpperCase()}</button>)}
                </div>
                {result.memory_suggestions?.length ? (
                  <div className="memory-box">
                    <h4>Translation Memory</h4>
                    {result.memory_suggestions.map(item=>(
                      <div className="memory-hit" key={item.id}>
                        <b>{Math.round((item.score||0)*100)}%</b> {item.source_text}<br/>
                        <span>{item.translated_text}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </React.Fragment>
            )}
          </div>
        </div>
      </div>

      {toast && <div className="toast"><Icon name="check" width="15" height="15"/>{toast}</div>}
    </div>
  );
}
window.TextTranslateStudio = TextTranslateStudio;

/* =================== Currency Convert =================== */
function CurrencyConvertStudio({ panelSolid }){
  const [amount,setAmount] = uS('100');
  const [from,setFrom] = uS('USD');
  const [to,setTo] = uS('VND');
  const [loading,setLoading] = uS(false);
  const [result,setResult] = uS(null);
  const [err,setErr] = uS('');

  async function convert(){
    const value = Number(amount);
    if(!Number.isFinite(value) || value < 0){ setErr('Nhập số tiền hợp lệ.'); return; }
    setLoading(true); setErr('');
    try{
      const data = await window.SG.convertCurrency({ amount:value, from, to });
      setResult(data);
    }catch(e){
      setErr(e.message || 'Quy đổi tiền tệ thất bại.');
    }finally{
      setLoading(false);
    }
  }

  function swap(){ setFrom(to); setTo(from); }

  function money(value, code){
    try{
      return new Intl.NumberFormat('vi-VN', { style:'currency', currency:code, maximumFractionDigits: code==='VND' ? 0 : 2 }).format(value);
    }catch(_){
      return `${Number(value).toLocaleString('vi-VN')} ${code}`;
    }
  }
  const resultFrom = result ? (result.from || result.from_currency) : from;
  const resultTo = result ? (result.to || result.to_currency) : to;

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Currency Convert</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="text-stage currency-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>Quy đổi ngoại tệ</h3>
          </div>
          <div className="currency-form">
            <label>
              <span>Số tiền</span>
              <input value={amount} onChange={e=>setAmount(e.target.value)} inputMode="decimal" placeholder="100"/>
            </label>
            <div className="currency-row">
              <label>
                <span>Từ</span>
                <select value={from} onChange={e=>setFrom(e.target.value)}>
                  {CURRENCIES.map(c=><option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <button className="swap currency-swap" title="Đảo chiều" onClick={swap}><Icon name="swap"/></button>
              <label>
                <span>Sang</span>
                <select value={to} onChange={e=>setTo(e.target.value)}>
                  {CURRENCIES.map(c=><option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            </div>
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <button className="rec-btn" onClick={convert} disabled={loading}>
              <span className="pulse"></span>{loading?'Đang quy đổi...':'Convert'}
            </button>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Kết quả</h3>
          </div>
          <div className="text-result currency-result">
            {!result && <div className="empty-hint">Kết quả quy đổi sẽ hiển thị ở đây.</div>}
            {result && (
              <React.Fragment>
                <div className="currency-total">{money(result.converted, resultTo)}</div>
                <div className="currency-meta">
                  <div>{money(result.amount, resultFrom)} = {money(result.converted, resultTo)}</div>
                  <div>Rate: 1 {resultFrom} = {Number(result.rate).toLocaleString('vi-VN')} {resultTo}</div>
                  <div>Nguồn: {result.source}</div>
                </div>
              </React.Fragment>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
window.CurrencyConvertStudio = CurrencyConvertStudio;

/* =================== Image Translate =================== */
function ImageTranslateStudio({ panelSolid, settings, srcLang, setSrcLang, tgtLang, setTgtLang }){
  const [file,setFile] = uS(null);
  const [preview,setPreview] = uS('');
  const [loading,setLoading] = uS(false);
  const [result,setResult] = uS(null);
  const [err,setErr] = uS('');
  const [ocrEngine,setOcrEngine] = uS('auto');

  function chooseFile(e){
    const next = e.target.files && e.target.files[0];
    setFile(next || null);
    setResult(null); setErr('');
    if(preview) URL.revokeObjectURL(preview);
    setPreview(next ? URL.createObjectURL(next) : '');
  }

  function swap(){ setSrcLang(tgtLang); setTgtLang(srcLang); }

  async function translate(){
    if(!file){ setErr('Chọn ảnh cần dịch.'); return; }
    setLoading(true); setErr('');
    try{
      const data = await window.SG.translateImage({
        file,
        srcLang: REST_LANG[srcLang] || srcLang,
        tgtLang: REST_LANG[tgtLang] || tgtLang,
        translateModel: settings.translateModel || 'nllb-600m',
        ocrEngine,
        ocrLang: REST_LANG[srcLang] || srcLang,
      });
      setResult(data);
      if(data.error) setErr(data.error);
    }catch(e){
      setErr(e.message || 'Dịch ảnh thất bại.');
    }finally{
      setLoading(false);
    }
  }

  function exportResult(format){
    if(!result) return;
    window.SG.exportFile({
      format,
      title:'SmartGen Image Translate',
      source_text:result.extracted_text,
      translated_text:result.translated_text,
    }).catch(e=>setErr(e.message || 'Export thất bại'));
  }

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Image Translate</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="langbar">
        <LangDropdown value={srcLang} onChange={setSrcLang} label="Ngôn ngữ ảnh"/>
        <div className="swap" title="Đảo chiều" onClick={swap}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={setTgtLang} label="Ngôn ngữ dịch"/>
      </div>

      <div className="text-stage image-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>Ảnh gốc</h3>
          </div>
          <div className="image-upload">
            <label className="file-drop">
              <input type="file" accept="image/*" onChange={chooseFile}/>
              <span>{file ? file.name : 'Chọn ảnh menu, hóa đơn hoặc biển báo'}</span>
            </label>
            <label className="travel-currency">
              <span>OCR engine</span>
              <select value={ocrEngine} onChange={e=>setOcrEngine(e.target.value)}>
                {OCR_ENGINES.map(([id,label])=><option key={id} value={id}>{label}</option>)}
              </select>
            </label>
            {preview
              ? <img className="image-preview" src={preview} alt="Preview"/>
              : <div className="empty-hint">Preview ảnh sẽ hiển thị ở đây.</div>}
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <button className="rec-btn" onClick={translate} disabled={loading}>
              <span className="pulse"></span>{loading?'Đang OCR + dịch...':'Translate Image'}
            </button>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Kết quả OCR</h3>
          </div>
          <div className="text-result">
            {!result && <div className="empty-hint">Text OCR và bản dịch sẽ hiển thị ở đây.</div>}
            {result && (
              <React.Fragment>
                <div className="ocr-status">OCR: {result.ocr_status} · {result.ocr_engine || 'n/a'} · {result.ocr_lang || 'auto'}</div>
                <h4>Văn bản trích xuất</h4>
                <p className="line">{result.extracted_text || 'Không có text.'}</p>
                <h4>Bản dịch</h4>
                <p className="line translated">{result.translated_text || 'Chưa có bản dịch.'}</p>
                <div className="export-row">
                  {['txt','json','docx'].map(f=><button key={f} onClick={()=>exportResult(f)}>{f.toUpperCase()}</button>)}
                </div>
                {result.blocks?.length ? (
                  <div className="memory-box">
                    <h4>OCR blocks</h4>
                    {result.blocks.slice(0,12).map((b,i)=>(
                      <div className="memory-hit" key={i}>
                        <b>{b.confidence == null ? '' : Math.round(b.confidence*100)/100}</b> {b.text}
                        {b.translation && <span><br/>{b.translation}</span>}
                      </div>
                    ))}
                  </div>
                ) : null}
                {result.detected_currency?.length ? (
                  <div className="currency-meta">
                    {result.detected_currency.map((item,i)=>(
                      <div key={i}>{item.text}: {item.amount} {item.currency}</div>
                    ))}
                  </div>
                ) : null}
              </React.Fragment>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
window.ImageTranslateStudio = ImageTranslateStudio;

/* =================== Audio File Translate =================== */
// Last segment whose start <= t (segments are sorted by start); -1 if none yet.
function findActiveSeg(segs, t){
  let lo = 0, hi = segs.length - 1, ans = -1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1;
    if (segs[mid].start <= t){ ans = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  return ans;
}
function AudioFileTranslateStudio({ panelSolid, settings, srcLang, setSrcLang, tgtLang, setTgtLang }){
  const [file,setFile] = uS(null);
  const [audioUrl,setAudioUrl] = uS('');
  const [loading,setLoading] = uS(false);
  const [result,setResult] = uS(null);
  const [err,setErr] = uS('');
  const [showTs,setShowTs] = uS(true);
  const [syncPaused,setSyncPaused] = uS(false);
  const audioRef = uR(null);          // native <audio> element
  const listRef = uR(null);           // scroll container (.audio-result)
  const segRefs = uR([]);             // per-row DOM nodes
  const activeIdxRef = uR(-1);        // currently highlighted segment
  const progScrollRef = uR(false);    // true while a code-driven scroll is settling
  const pausedRef = uR(false);        // sync mirror of syncPaused for the scroll handler
  const progTimerRef = uR(0);

  function chooseFile(e){
    const next = e.target.files && e.target.files[0];
    setFile(next || null);
    setResult(null); setErr('');
    if(audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(next ? URL.createObjectURL(next) : '');
  }

  function swap(){ setSrcLang(tgtLang); setTgtLang(srcLang); }

  async function translate(){
    if(!file){ setErr('Chọn file audio cần dịch.'); return; }
    setLoading(true); setErr('');
    try{
      const data = await window.SG.translateAudioFile({
        file,
        srcLang: REST_LANG[srcLang] || srcLang,
        tgtLang: REST_LANG[tgtLang] || tgtLang,
        translateModel: settings.translateModel || 'nllb-600m',
      });
      setResult(data);
      if(data.error) setErr(data.error);
    }catch(e){
      setErr(e.message || 'Dịch file audio thất bại.');
    }finally{
      setLoading(false);
    }
  }

  function fmtTime(seconds){
    const s = Math.max(0, Number(seconds)||0);
    const m = Math.floor(s/60);
    const r = Math.floor(s%60);
    return `${m}:${String(r).padStart(2,'0')}`;
  }

  function exportResult(format){
    if(!result) return;
    window.SG.exportFile({
      format,
      title:'SmartGen Audio File Translate',
      source_text:result.full_text,
      translated_text:result.full_translation,
      segments:result.segments || [],
    }).catch(e=>setErr(e.message || 'Export thất bại'));
  }

  const segs = result?.segments || [];

  function scrollToNode(node){
    const c = listRef.current;
    if(!c || !node) return;
    const top = c.scrollTop + (node.getBoundingClientRect().top - c.getBoundingClientRect().top) - (c.clientHeight - node.clientHeight)/2;
    progScrollRef.current = true;
    c.scrollTo({ top, behavior:'smooth' });
    clearTimeout(progTimerRef.current);
    progTimerRef.current = setTimeout(()=>{ progScrollRef.current = false; }, 600);
  }

  function resumeSync(){
    pausedRef.current = false; setSyncPaused(false);
    scrollToNode(segRefs.current[activeIdxRef.current]);
  }

  function seekTo(i){
    const a = audioRef.current; if(!a) return;
    a.currentTime = segs[i].start;
    if(a.paused) a.play().catch(()=>{});
    resumeSync();
  }

  uE(()=>{
    const a = audioRef.current, c = listRef.current;
    if(!a || !c || !segs.length) return;
    activeIdxRef.current = -1; pausedRef.current = false; setSyncPaused(false);

    function onTime(){
      const idx = findActiveSeg(segs, a.currentTime);
      if(idx === activeIdxRef.current) return;
      segRefs.current[activeIdxRef.current]?.classList.remove('active');
      const node = segRefs.current[idx];
      node?.classList.add('active');
      activeIdxRef.current = idx;
      if(node && !pausedRef.current) scrollToNode(node);
    }
    function onScroll(){
      if(progScrollRef.current) return;
      if(!pausedRef.current){ pausedRef.current = true; setSyncPaused(true); }
    }
    a.addEventListener('timeupdate', onTime);
    c.addEventListener('scroll', onScroll);
    return ()=>{
      a.removeEventListener('timeupdate', onTime);
      c.removeEventListener('scroll', onScroll);
      clearTimeout(progTimerRef.current);
    };
  }, [result]);

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Audio File Translate</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="langbar">
        <LangDropdown value={srcLang} onChange={setSrcLang} label="Ngôn ngữ audio"/>
        <div className="swap" title="Đảo chiều" onClick={swap}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={setTgtLang} label="Ngôn ngữ dịch"/>
      </div>

      <div className="text-stage image-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>File ghi âm</h3>
          </div>
          <div className="image-upload">
            <label className="file-drop">
              <input type="file" accept="audio/*,.m4a,.mp3,.wav,.flac,.ogg,.webm" onChange={chooseFile}/>
              <span>{file ? file.name : 'Chọn file WAV, MP3, M4A, FLAC, OGG hoặc WEBM'}</span>
            </label>
            {audioUrl
              ? <audio ref={audioRef} className="audio-preview" src={audioUrl} controls></audio>
              : <div className="empty-hint">Audio preview sẽ hiển thị ở đây.</div>}
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <button className="rec-btn" onClick={translate} disabled={loading}>
              <span className="pulse"></span>{loading?'Đang STT + dịch...':'Translate Audio'}
            </button>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Transcript song ngữ</h3>
            {result && (
              <div className="ts-toolbar">
                <button onClick={()=>setShowTs(v=>!v)}>{showTs?'Ẩn thời gian':'Hiện thời gian'}</button>
                {syncPaused && <button className="resume-sync" onClick={resumeSync}>Đồng bộ lại</button>}
              </div>
            )}
          </div>
          <div className={'text-result audio-result'+(showTs?'':' ts-hidden')} ref={listRef}>
            {!result && <div className="empty-hint">Timeline transcript và bản dịch sẽ hiển thị ở đây.</div>}
            {result && (
              <React.Fragment>
                <div className="ocr-status">STT: {result.stt_status}</div>
                <div className="export-row">
                  {['txt','json','srt','docx'].map(f=><button key={f} onClick={()=>exportResult(f)}>{f.toUpperCase()}</button>)}
                </div>
                {result.segments?.length ? result.segments.map((seg,i)=>(
                  <div className="audio-seg" key={i} ref={el=>segRefs.current[i]=el} onClick={()=>seekTo(i)}>
                    <div className="audio-time">{fmtTime(seg.start)} - {fmtTime(seg.end)}</div>
                    <div className="audio-src">{seg.text}</div>
                    <div className="audio-tgt">{seg.translation}</div>
                  </div>
                )) : <p className="line">Không có transcript.</p>}
              </React.Fragment>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
window.AudioFileTranslateStudio = AudioFileTranslateStudio;

/* =================== YouTube Transcript (read-along) =================== */
function extractYtId(s){
  const m = (s||'').match(/(?:v=|youtu\.be\/|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
  if(m) return m[1];
  if(/^[A-Za-z0-9_-]{11}$/.test((s||'').trim())) return s.trim();
  return null;
}

function ensureYTApi(){
  return new Promise(resolve=>{
    if(window.YT && window.YT.Player){ resolve(); return; }
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = ()=>{ if(typeof prev==='function') prev(); resolve(); };
    if(!document.getElementById('yt-iframe-api')){
      const s = document.createElement('script');
      s.id = 'yt-iframe-api'; s.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(s);
    }
  });
}

function YouTubeTranscriptStudio({ panelSolid }){
  const [url,setUrl] = uS('');
  const [snippets,setSnippets] = uS([]);
  const [lang,setLang] = uS('');
  const [loading,setLoading] = uS(false);
  const [err,setErr] = uS('');
  const [showTs,setShowTs] = uS(true);
  const [syncPaused,setSyncPaused] = uS(false);

  const playerRef = uR(null);
  const playerHostRef = uR(null);
  const snippetsRef = uR([]);          // mirror for the poll closure
  const listRef = uR(null);
  const segRefs = uR([]);
  const activeIdxRef = uR(-1);
  const progScrollRef = uR(false);
  const pausedRef = uR(false);
  const progTimerRef = uR(0);
  const pollRef = uR(0);

  function fmtTime(seconds){
    const s = Math.max(0, Number(seconds)||0);
    const m = Math.floor(s/60);
    const r = Math.floor(s%60);
    return `${m}:${String(r).padStart(2,'0')}`;
  }

  function scrollToNode(node){
    const c = listRef.current;
    if(!c || !node) return;
    const top = c.scrollTop + (node.getBoundingClientRect().top - c.getBoundingClientRect().top) - (c.clientHeight - node.clientHeight)/2;
    progScrollRef.current = true;
    c.scrollTo({ top, behavior:'smooth' });
    clearTimeout(progTimerRef.current);
    progTimerRef.current = setTimeout(()=>{ progScrollRef.current = false; }, 600);
  }
  function resumeSync(){
    pausedRef.current = false; setSyncPaused(false);
    scrollToNode(segRefs.current[activeIdxRef.current]);
  }
  function seekTo(i){
    const p = playerRef.current; if(!p || !p.seekTo) return;
    p.seekTo(snippetsRef.current[i].start, true);
    if(p.playVideo) p.playVideo();
    resumeSync();
  }
  function onScroll(){
    if(progScrollRef.current) return;
    if(!pausedRef.current){ pausedRef.current = true; setSyncPaused(true); }
  }
  function stopPoll(){ if(pollRef.current){ clearInterval(pollRef.current); pollRef.current = 0; } }
  function startPoll(){
    stopPoll();
    pollRef.current = setInterval(()=>{
      const p = playerRef.current;
      if(!p || !p.getCurrentTime) return;
      const segs = snippetsRef.current;
      if(!segs.length) return;
      const idx = findActiveSeg(segs, p.getCurrentTime());
      if(idx === activeIdxRef.current) return;
      segRefs.current[activeIdxRef.current]?.classList.remove('active');
      const node = segRefs.current[idx];
      node?.classList.add('active');
      activeIdxRef.current = idx;
      if(node && !pausedRef.current) scrollToNode(node);
    }, 250);
  }

  async function load(){
    const id = extractYtId(url);
    if(!id){ setErr('Link YouTube không hợp lệ.'); return; }
    setErr(''); setLoading(true);
    activeIdxRef.current = -1; pausedRef.current = false; setSyncPaused(false); segRefs.current = [];
    try{
      const r = await fetch('/api/youtube/transcript?id='+encodeURIComponent(id)+'&src=');
      const j = await r.json();
      if(j.error){ setErr(j.error); setSnippets([]); snippetsRef.current = []; return; }
      const snn = j.snippets || [];
      snippetsRef.current = snn; setSnippets(snn); setLang(j.lang||'');
      await ensureYTApi();
      const c = listRef.current; if(c) c.scrollTop = 0;
      if(playerRef.current && playerRef.current.loadVideoById){
        playerRef.current.loadVideoById(id);
        startPoll();
      } else {
        playerRef.current = new YT.Player(playerHostRef.current, {
          videoId:id,
          playerVars:{ rel:0, modestbranding:1 },
          events:{ onReady:()=>startPoll() }
        });
      }
    }catch(e){ setErr(e.message || 'Tải transcript thất bại.'); }
    finally{ setLoading(false); }
  }

  uE(()=>()=>{
    stopPoll(); clearTimeout(progTimerRef.current);
    try{ if(playerRef.current && playerRef.current.destroy) playerRef.current.destroy(); }catch(_){}
  }, []);

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">YouTube Transcript</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="text-stage image-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>Video YouTube</h3>
          </div>
          <div className="image-upload">
            <div className="yt-urlbar">
              <input type="text" value={url} onChange={e=>setUrl(e.target.value)}
                placeholder="Dán link YouTube (https://youtu.be/...)"
                onKeyDown={e=>{ if(e.key==='Enter') load(); }}/>
              <button onClick={load} disabled={loading}>{loading?'Đang tải...':'Tải transcript'}</button>
            </div>
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <div className="yt-player"><div ref={playerHostRef}></div></div>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Transcript{lang ? ' · '+lang : ''}</h3>
            {snippets.length>0 && (
              <div className="ts-toolbar">
                <button onClick={()=>setShowTs(v=>!v)}>{showTs?'Ẩn thời gian':'Hiện thời gian'}</button>
                {syncPaused && <button className="resume-sync" onClick={resumeSync}>Đồng bộ lại</button>}
              </div>
            )}
          </div>
          <div className={'text-result audio-result'+(showTs?'':' ts-hidden')} ref={listRef}>
            {!snippets.length && <div className="empty-hint">Dán link YouTube rồi nhấn “Tải transcript”. Transcript sẽ hiện ở đây và tự bám theo video.</div>}
            {snippets.map((seg,i)=>(
              <div className="audio-seg" key={i} ref={el=>segRefs.current[i]=el} onClick={()=>seekTo(i)}>
                <div className="audio-time">{fmtTime(seg.start)}</div>
                <div className="audio-src">{seg.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
window.YouTubeTranscriptStudio = YouTubeTranscriptStudio;

/* =================== Travel Assistant =================== */
function TravelAssistantStudio({ panelSolid, settings, srcLang, setSrcLang, tgtLang, setTgtLang }){
  const [file,setFile] = uS(null);
  const [preview,setPreview] = uS('');
  const [text,setText] = uS('ラーメン 980円\nコーヒー 450円');
  const [homeCurrency,setHomeCurrency] = uS('VND');
  const [loading,setLoading] = uS(false);
  const [result,setResult] = uS(null);
  const [err,setErr] = uS('');
  const [ocrEngine,setOcrEngine] = uS('auto');

  function chooseFile(e){
    const next = e.target.files && e.target.files[0];
    setFile(next || null);
    setResult(null); setErr('');
    if(preview) URL.revokeObjectURL(preview);
    setPreview(next ? URL.createObjectURL(next) : '');
  }

  async function assist(){
    if(!file && !text.trim()){ setErr('Upload ảnh hoặc nhập nội dung cần hỗ trợ.'); return; }
    setLoading(true); setErr('');
    try{
      const data = await window.SG.travelAssist({
        file,
        text,
        srcLang: REST_LANG[srcLang] || srcLang,
        targetLanguage: REST_LANG[tgtLang] || tgtLang,
        homeCurrency,
        translateModel: settings.translateModel || 'nllb-600m',
        ocrEngine,
        ocrLang: REST_LANG[srcLang] || srcLang,
      });
      setResult(data);
      if(data.error) setErr(data.error);
    }catch(e){
      setErr(e.message || 'Travel Assistant thất bại.');
    }finally{
      setLoading(false);
    }
  }

  function fmtPrice(price){
    if(!price) return '';
    try{
      return new Intl.NumberFormat('vi-VN', { style:'currency', currency:price.converted_currency, maximumFractionDigits:price.converted_currency==='VND'?0:2 }).format(price.converted_amount);
    }catch(_){
      return `${Number(price.converted_amount).toLocaleString('vi-VN')} ${price.converted_currency}`;
    }
  }

  function exportResult(format){
    if(!result) return;
    window.SG.exportFile({
      format,
      title:'SmartGen Travel Assistant',
      source_text:result.source_text,
      translated_text:(result.items||[]).map(item=>item.translation).join('\n'),
    }).catch(e=>setErr(e.message || 'Export thất bại'));
  }

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Travel Assistant</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="langbar">
        <LangDropdown value={srcLang} onChange={setSrcLang} label="Ngôn ngữ nguồn"/>
        <div className="swap" title="Đảo chiều" onClick={()=>{setSrcLang(tgtLang);setTgtLang(srcLang);}}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={setTgtLang} label="Ngôn ngữ dịch"/>
      </div>

      <div className="text-stage image-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot src"></span>
            <h3>Menu, hóa đơn, biển báo</h3>
          </div>
          <div className="image-upload">
            <label className="file-drop">
              <input type="file" accept="image/*" onChange={chooseFile}/>
              <span>{file ? file.name : 'Upload ảnh hoặc dùng text bên dưới'}</span>
            </label>
            {preview && <img className="image-preview" src={preview} alt="Travel preview"/>}
            <textarea className="text-input travel-textarea" value={text} onChange={e=>setText(e.target.value)} spellCheck="false"/>
            <label className="travel-currency">
              <span>OCR engine</span>
              <select value={ocrEngine} onChange={e=>setOcrEngine(e.target.value)}>
                {OCR_ENGINES.map(([id,label])=><option key={id} value={id}>{label}</option>)}
              </select>
            </label>
            <label className="travel-currency">
              <span>Tiền tệ nhà</span>
              <select value={homeCurrency} onChange={e=>setHomeCurrency(e.target.value)}>
                {CURRENCIES.map(c=><option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <button className="rec-btn" onClick={assist} disabled={loading}>
              <span className="pulse"></span>{loading?'Đang phân tích...':'Assist'}
            </button>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head">
            <span className="dot tgt"></span>
            <h3>Gợi ý du lịch</h3>
          </div>
          <div className="text-result audio-result">
            {!result && <div className="empty-hint">Bản dịch, giá quy đổi và ghi chú sẽ hiển thị ở đây.</div>}
            {result && (
              <React.Fragment>
                <div className="ocr-status">{result.summary}</div>
                {result.ocr_status && <div className="ocr-status">OCR: {result.ocr_status} · {result.ocr_engine || 'n/a'} · {result.ocr_lang || 'auto'}</div>}
                <div className="export-row">
                  {['txt','json','docx'].map(f=><button key={f} onClick={()=>exportResult(f)}>{f.toUpperCase()}</button>)}
                </div>
                {result.items?.map((item,i)=>(
                  <div className="travel-card" key={i}>
                    <div className="audio-src">{item.original}</div>
                    <div className="audio-tgt">{item.translation}</div>
                    {item.price && <div className="travel-price">{item.price.amount} {item.price.currency} ≈ {fmtPrice(item.price)}</div>}
                    {item.note && <div className="travel-note">{item.note}</div>}
                  </div>
                ))}
              </React.Fragment>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
window.TravelAssistantStudio = TravelAssistantStudio;

/* =================== Glossary =================== */
function GlossaryStudio({ panelSolid, srcLang, setSrcLang, tgtLang, setTgtLang }){
  const blank = { source_term:'', target_term:'', note:'' };
  const [items,setItems] = uS([]);
  const [form,setForm] = uS(blank);
  const [editing,setEditing] = uS(null);
  const [loading,setLoading] = uS(false);
  const [err,setErr] = uS('');
  const [toast,setToast] = uS(null);

  uE(()=>{ refresh(); },[]);
  function flash(msg){ setToast(msg); setTimeout(()=>setToast(null),1600); }
  function refresh(){ if(window.SG) window.SG.fetchGlossary().then(setItems).catch(e=>setErr(e.message)); }
  function setField(k,v){ setForm(f=>({...f,[k]:v})); }
  function edit(item){
    setEditing(item.id);
    setForm({ source_term:item.source_term, target_term:item.target_term, note:item.note||'' });
    setSrcLang(Object.keys(REST_LANG).find(k=>REST_LANG[k]===item.src_lang) || srcLang);
    setTgtLang(Object.keys(REST_LANG).find(k=>REST_LANG[k]===item.tgt_lang) || tgtLang);
  }
  function reset(){ setEditing(null); setForm(blank); }

  async function save(){
    if(!form.source_term.trim() || !form.target_term.trim()){ setErr('Nhập đủ thuật ngữ nguồn và đích.'); return; }
    setLoading(true); setErr('');
    const payload = {
      source_term:form.source_term.trim(),
      target_term:form.target_term.trim(),
      src_lang:REST_LANG[srcLang] || srcLang,
      tgt_lang:REST_LANG[tgtLang] || tgtLang,
      note:form.note.trim(),
    };
    try{
      if(editing) await window.SG.updateGlossary(editing, payload);
      else await window.SG.createGlossary(payload);
      reset(); refresh(); flash('Đã lưu glossary');
    }catch(e){ setErr(e.message || 'Lưu glossary thất bại.'); }
    finally{ setLoading(false); }
  }

  async function remove(id){
    try{ await window.SG.deleteGlossary(id); refresh(); flash('Đã xóa'); }
    catch(e){ setErr(e.message || 'Xóa thất bại.'); }
  }

  return (
    <div className="scene text-scene">
      <div className="topbar">
        <div className="brand" onClick={()=>window.__go('landing')}>
          <div className="mark"></div>
          <div><div className="name"><b>Smart</b><span>Gen</span></div><div className="tag">Smart Glossary</div></div>
        </div>
        <div className="spacer"></div>
      </div>

      <div className="langbar">
        <LangDropdown value={srcLang} onChange={setSrcLang} label="Ngôn ngữ nguồn"/>
        <div className="swap" title="Đảo chiều" onClick={()=>{setSrcLang(tgtLang);setTgtLang(srcLang);}}><Icon name="swap"/></div>
        <LangDropdown value={tgtLang} onChange={setTgtLang} label="Ngôn ngữ dịch"/>
      </div>

      <div className="text-stage glossary-stage">
        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head"><span className="dot src"></span><h3>{editing?'Sửa thuật ngữ':'Thêm thuật ngữ'}</h3></div>
          <div className="currency-form">
            <label><span>Source term</span><input value={form.source_term} onChange={e=>setField('source_term',e.target.value)} placeholder="prompt"/></label>
            <label><span>Target term</span><input value={form.target_term} onChange={e=>setField('target_term',e.target.value)} placeholder="câu lệnh"/></label>
            <label><span>Note</span><input value={form.note} onChange={e=>setField('note',e.target.value)} placeholder="Dùng trong AI"/></label>
            {err && <div className="mic-err text-error"><Icon name="alert" width="15" height="15"/>{err}</div>}
            <div className="export-row">
              <button onClick={save} disabled={loading}>{loading?'Đang lưu...':'Save'}</button>
              {editing && <button onClick={reset}>Cancel</button>}
            </div>
          </div>
        </div>

        <div className={'pane text-pane'+(panelSolid?' solid':'')}>
          <div className="pane-head"><span className="dot tgt"></span><h3>Danh sách glossary</h3></div>
          <div className="text-result audio-result">
            {!items.length && <div className="empty-hint">Chưa có thuật ngữ.</div>}
            {items.map(item=>(
              <div className="travel-card" key={item.id}>
                <div className="audio-src">{item.source_term} → {item.target_term}</div>
                <div className="audio-tgt">{item.src_lang} → {item.tgt_lang}{item.note ? ' · '+item.note : ''}</div>
                <div className="export-row">
                  <button onClick={()=>edit(item)}>Edit</button>
                  <button onClick={()=>remove(item.id)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {toast && <div className="toast"><Icon name="check" width="15" height="15"/>{toast}</div>}
    </div>
  );
}
window.GlossaryStudio = GlossaryStudio;

/* =================== Extension Popup =================== */
function ExtensionPopup({ colors, glow, bars }){
  const [on,setOn]=uS(true);
  return (
    <div className="ext-scene">
      <div className="app-bg"><div className="aurora a1"></div><div className="aurora a2"></div></div>
      <div style={{position:'relative',zIndex:1,textAlign:'center'}}>
        <div style={{marginBottom:18,color:'var(--text-3)',font:'500 12px var(--mono)',letterSpacing:'1px'}}>BROWSER EXTENSION · POPUP 380px</div>
        <div className="ext-frame">
          <div className="ext-chrome">
            <span className="dot" style={{background:'#ff5f57'}}></span>
            <span className="dot" style={{background:'#febc2e'}}></span>
            <span className="dot" style={{background:'#28c840'}}></span>
            <div className="brand" style={{marginLeft:8}}>
              <div className="mark" style={{width:22,height:22,borderRadius:7}}></div>
              <div className="name" style={{fontSize:14}}><b>Smart</b><span>Gen</span></div>
            </div>
            <div style={{marginLeft:'auto',color:'var(--text-3)'}}><Icon name="gear" width="16" height="16"/></div>
          </div>
          <div className="ext-body">
            <div style={{display:'flex',gap:8,marginBottom:6}}>
              <div className="seg" style={{flex:1,justifyContent:'center'}}>
                <button className="on" style={{flex:1,justifyContent:'center'}}><Icon name="meet"/>Meet</button>
                <button style={{flex:1,justifyContent:'center'}}><Icon name="youtube"/>Tab</button>
              </div>
            </div>
            <div className="ext-orb"><ShowcaseOrb colors={colors} glow={glow} bars={bars} cycle={on?['listening','speaking','translating']:['idle']}/></div>
            <div style={{textAlign:'center',fontWeight:600,fontSize:14,marginTop:-6}}>{on?'Đang dịch trực tiếp':'Tạm dừng'}</div>
            <div style={{textAlign:'center',font:'500 11px var(--mono)',color:'var(--text-3)',marginTop:3}}>VI → EN · 88ms</div>
            <div className="ext-mini-pane">
              <div className="lab">Nguồn · Tiếng Việt</div>
              Cảm ơn mọi người đã tham gia buổi họp.
            </div>
            <div className="ext-mini-pane" style={{borderColor:'var(--accent)'}}>
              <div className="lab" style={{color:'var(--accent-2)'}}>Bản dịch · English</div>
              Thank you everyone for joining the meeting.
            </div>
            <button className={'rec-btn'+(on?' live':'')} style={{width:'100%',justifyContent:'center',marginTop:12}} onClick={()=>setOn(o=>!o)}>
              <span className="pulse"></span>{on?'Dừng lại':'Bắt đầu'}
            </button>
          </div>
        </div>
        <div style={{marginTop:18}}>
          <button className="secondary" style={{padding:'10px 18px',borderRadius:12,cursor:'pointer',font:'600 14px var(--font)',color:'var(--text)',background:'var(--surface)',border:'1px solid var(--border)'}} onClick={()=>window.__go('landing')}>← Về trang chủ</button>
        </div>
      </div>
    </div>
  );
}
window.ExtensionPopup = ExtensionPopup;
