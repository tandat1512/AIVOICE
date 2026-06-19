/* global React, ReactDOM, Studio, Landing, SettingsModal, ExtensionPopup, TextTranslateStudio, CurrencyConvertStudio, ImageTranslateStudio, AudioFileTranslateStudio, YouTubeTranscriptStudio, TravelAssistantStudio, GlossaryStudio, useTweaks, TweaksPanel, TweakSection, TweakColor, TweakSlider, TweakToggle, TweakRadio */
const { useState:US, useEffect:UE } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "palette": ["#22d3ee","#3b82f6","#6366f1"],
  "glow": 1,
  "orbBars": true,
  "panel": "glass",
  "bg": "navy"
}/*EDITMODE-END*/;

function hexA(h,a){ h=h.replace('#',''); if(h.length===3)h=h.split('').map(c=>c+c).join(''); const n=parseInt(h,16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; }

function App(){
  const [t,setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view,setView] = US('landing');
  const [srcLang,setSrcLang] = US('vi');
  const [tgtLang,setTgtLang] = US('en');
  const [source,setSource] = US('mic');
  const [showSettings,setShowSettings] = US(false);
  const [settings,setSettings] = US({ voice:'', speed:1.0, vad:500, sttModel:'sherpa', translateModel:'nllb-600m' });

  UE(()=>{ window.__go = setView; },[]);

  // apply theme tweaks to CSS variables
  UE(()=>{
    const r = document.documentElement.style;
    const [a,b,c] = t.palette;
    r.setProperty('--accent-2',a); r.setProperty('--accent',b); r.setProperty('--accent-3',c);
    r.setProperty('--accent-soft', hexA(b,0.14));
    r.setProperty('--glow', String(t.glow));
    r.setProperty('--bg', t.bg==='black' ? '#010207' : '#05070e');
  },[t.palette, t.glow, t.bg]);

  const colors = { a:t.palette[0], b:t.palette[1], c:t.palette[2] };
  const panelSolid = t.panel==='solid';

  return (
    <React.Fragment>
      {view!=='landing' && <div className="app-bg"><div className="aurora a1"></div><div className="aurora a2"></div></div>}

      {view==='landing' && <Landing colors={colors} bars={t.orbBars}/>}
      {view==='app' && (
        <Studio
          colors={colors} glow={t.glow} bars={t.orbBars} panelSolid={panelSolid} settings={settings}
          source={source} setSource={setSource}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
          openSettings={()=>setShowSettings(true)}
        />
      )}
      {view==='text' && (
        <TextTranslateStudio
          panelSolid={panelSolid} settings={settings}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
          openSettings={()=>setShowSettings(true)}
        />
      )}
      {view==='currency' && <CurrencyConvertStudio panelSolid={panelSolid}/>}
      {view==='image' && (
        <ImageTranslateStudio
          panelSolid={panelSolid} settings={settings}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
        />
      )}
      {view==='audio' && (
        <AudioFileTranslateStudio
          panelSolid={panelSolid} settings={settings}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
        />
      )}
      {view==='youtube' && (
        <YouTubeTranscriptStudio panelSolid={panelSolid}/>
      )}
      {view==='travel' && (
        <TravelAssistantStudio
          panelSolid={panelSolid} settings={settings}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
        />
      )}
      {view==='glossary' && (
        <GlossaryStudio
          panelSolid={panelSolid}
          srcLang={srcLang} setSrcLang={setSrcLang}
          tgtLang={tgtLang} setTgtLang={setTgtLang}
        />
      )}
      {view==='extension' && <ExtensionPopup colors={colors} glow={t.glow} bars={t.orbBars}/>}

      {showSettings && <SettingsModal settings={settings} setSettings={setSettings} onClose={()=>setShowSettings(false)}/>}

      {/* floating view switcher */}
      <div style={{position:'fixed',bottom:20,left:'50%',transform:'translateX(-50%)',zIndex:80}}>
        <div className="view-switch">
          <button className={view==='landing'?'on':''} onClick={()=>setView('landing')}>Landing</button>
          <button className={view==='app'?'on':''} onClick={()=>setView('app')}>Studio</button>
          <button className={view==='text'?'on':''} onClick={()=>setView('text')}>Text</button>
          <button className={view==='currency'?'on':''} onClick={()=>setView('currency')}>Currency</button>
          <button className={view==='image'?'on':''} onClick={()=>setView('image')}>Image</button>
          <button className={view==='audio'?'on':''} onClick={()=>setView('audio')}>Audio</button>
          <button className={view==='youtube'?'on':''} onClick={()=>setView('youtube')}>YouTube</button>
          <button className={view==='travel'?'on':''} onClick={()=>setView('travel')}>Travel</button>
          <button className={view==='glossary'?'on':''} onClick={()=>setView('glossary')}>Glossary</button>
          <button className={view==='extension'?'on':''} onClick={()=>setView('extension')}>Extension</button>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Giao diện" />
        <TweakColor label="Bảng màu" value={t.palette} options={[
          ["#22d3ee","#3b82f6","#6366f1"],
          ["#c084fc","#a855f7","#7c3aed"],
          ["#34d399","#10b981","#0ea5e9"],
          ["#fbbf24","#fb7185","#f43f5e"]
        ]} onChange={v=>setTweak('palette',v)} />
        <TweakSlider label="Cường độ phát sáng" value={t.glow} min={0.4} max={1.8} step={0.1} onChange={v=>setTweak('glow',v)} />
        <TweakRadio label="Nền" value={t.bg} options={['navy','black']} onChange={v=>setTweak('bg',v)} />
        <TweakSection label="Hiệu ứng & bố cục" />
        <TweakToggle label="Vành sóng âm" value={t.orbBars} onChange={v=>setTweak('orbBars',v)} />
        <TweakRadio label="Kiểu pane" value={t.panel} options={['glass','solid']} onChange={v=>setTweak('panel',v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
