/* global React */
const { useState, useRef, useEffect } = React;

/* ---------- Minimal line icons ---------- */
const Ic = {
  mic:    <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Zm7 9a7 7 0 0 1-14 0M12 18v4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>,
  youtube:<g fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="2.5" y="5.5" width="19" height="13" rx="4"/><path d="M10 9.5v5l4.5-2.5L10 9.5Z" fill="currentColor" stroke="none"/></g>,
  meet:   <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="2.5" y="6.5" width="12" height="11" rx="2.5"/><path d="M14.5 10l6-3.5v11l-6-3.5"/></g>,
  swap:   <path d="M7 4 4 7l3 3M4 7h13M17 20l3-3-3-3m3 3H7" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  gear:   <g fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" strokeLinecap="round"/></g>,
  chev:   <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>,
  x:      <path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>,
  clear:  <path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0 1 13h10l1-13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>,
  pause:  <g fill="currentColor"><rect x="7" y="5" width="3.5" height="14" rx="1.2"/><rect x="14" y="5" width="3.5" height="14" rx="1.2"/></g>,
  bolt:   <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor"/>,
  link:   <path d="M9 15l6-6M8 8H6a3 3 0 0 0 0 6h2m8-6h2a3 3 0 0 1 0 6h-2" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>,
  layers: <path d="M12 3 2 8l10 5 10-5-10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>,
  shield: <path d="M12 3 5 6v5c0 4 3 7 7 9 4-2 7-5 7-9V6l-7-3Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>,
  waves:  <path d="M3 12c2-4 4-4 6 0s4 4 6 0 4-4 6 0M3 17c2-3 4-3 6 0s4 3 6 0 4-3 6 0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>,
  arrow:  <path d="M5 12h14m-6-6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>,
  globe:  <g fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"/></g>,
  speaker:<path d="M4 9v6h4l5 4V5L8 9H4Zm12 .5a4 4 0 0 1 0 5m2.5-7.5a7 7 0 0 1 0 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>,
  copy:   <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></g>,
  download:<path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>,
  plus:   <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>,
  minus:  <path d="M5 12h14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>,
  lock:   <g fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></g>,
  unlock: <g fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/></g>,
  cc:     <g fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 10a2.5 2.5 0 0 0-2 4M17 10a2.5 2.5 0 0 0-2 4" strokeLinecap="round"/></g>,
  replay: <path d="M4 12a8 8 0 1 1 2.3 5.6M4 12V7m0 5h5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>,
  alert:  <path d="M12 3 2 20h20L12 3Zm0 6v5m0 3h.01" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  check:  <path d="M5 12l4 4 10-10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>,
};
function Icon({ name, ...p }){ return <svg viewBox="0 0 24 24" {...p}>{Ic[name]}</svg>; }
window.Icon = Icon;

/* ---------- Languages ---------- */
const LANGS = {
  vi:{ code:'VI', name:'Tiếng Việt', en:'Vietnamese', color:'#ef4444' },
  en:{ code:'EN', name:'English', en:'English', color:'#3b82f6' },
  ja:{ code:'JP', name:'日本語', en:'Japanese', color:'#a855f7' },
  ko:{ code:'KR', name:'한국어', en:'Korean', color:'#22c55e' },
  zh:{ code:'CN', name:'中文', en:'Chinese', color:'#f59e0b' },
  fr:{ code:'FR', name:'Français', en:'French', color:'#06b6d4' },
};
window.LANGS = LANGS;

/* ---------- Dropdown ---------- */
function LangDropdown({ value, onChange, label }){
  const [open,setOpen]=useState(false);
  const ref=useRef(null);
  useEffect(()=>{
    function h(e){ if(ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown',h); return ()=>document.removeEventListener('mousedown',h);
  },[]);
  const L=LANGS[value];
  return (
    <div className={'dd'+(open?' open':'')} ref={ref}>
      <div className="dd-trigger" onClick={()=>setOpen(o=>!o)}>
        <span className="flag" style={{background:L.color}}>{L.code}</span>
        <span className="lab"><small>{label}</small><b>{L.name}</b></span>
        <span className="chev"><Icon name="chev" width="16" height="16"/></span>
      </div>
      {open && (
        <div className="dd-menu">
          {Object.keys(LANGS).map(k=>(
            <div key={k} className={'dd-item'+(k===value?' sel':'')} onClick={()=>{onChange(k);setOpen(false);}}>
              <span className="flag" style={{background:LANGS[k].color}}>{LANGS[k].code}</span>
              {LANGS[k].name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
window.LangDropdown = LangDropdown;

/* ---------- Speakers (diarization) ---------- */
const SPEAKERS = [
  { name:'Người nói 1', short:'A', color:'#22d3ee' },
  { name:'Người nói 2', short:'B', color:'#a855f7' },
  { name:'Người nói 3', short:'C', color:'#34d399' },
];
window.SPEAKERS = SPEAKERS;

/* ---------- Bilingual demo scripts ----------
   s = correct transcript (PhoWhisper), guess = misheard interim (Sherpa),
   sp = speaker index, t = translation. guess keeps the same word count as s. */
const SCRIPTS = {
  'vi-en':[
    { sp:0, s:'Xin chào mọi người, cảm ơn đã tham gia buổi họp hôm nay.', guess:'Xin chào mọi người, cảm ơn đã tham ra buổi hộp hôm nay.', t:'Hello everyone, thank you for joining today\u2019s meeting.' },
    { sp:0, s:'Hôm nay chúng ta sẽ điểm qua tiến độ của dự án dịch giọng nói.', guess:'Hôm nay chúng ta sẽ điểm qua tiến bộ của dữ án dịch giọng nói.', t:'Today we will review the progress of the speech translation project.' },
    { sp:1, s:'Nhóm kỹ thuật đã hoàn thành tầng nhận dạng giọng nói thời gian thực.', guess:'Nhóm kĩ thuật đã hoàn thành tần nhận dạng giọng nói thời gian thực.', t:'The engineering team has finished the real-time speech recognition layer.' },
    { sp:1, s:'Độ trễ hiện tại đang ở dưới một trăm mili giây.', guess:'Độ chễ hiện tại đang ở dưới một trăm mili giây.', t:'The current latency is staying under one hundred milliseconds.' },
    { sp:0, s:'Bước tiếp theo là tối ưu mô hình dịch và giọng đọc tổng hợp.', guess:'Bước tiếp theo là tối ưu mô hình dịch và giọng đọc tổng hớp.', t:'The next step is to optimize the translation model and the synthesized voice.' },
    { sp:2, s:'Mọi người có câu hỏi gì trước khi chúng ta tiếp tục không?', guess:'Mọi người có câu hỏi gì trước khi chúng ta tiếp túc không?', t:'Does anyone have questions before we move on?' },
  ],
  'en-vi':[
    { sp:0, s:'Welcome back, let\u2019s start the product demo for our investors.', guess:'Welcome back, lets start the product demo for our investor.', t:'Chào mừng trở lại, hãy bắt đầu phần demo sản phẩm cho nhà đầu tư.' },
    { sp:0, s:'Our system translates live audio from any meeting in real time.', guess:'Our system translate live audio from any meeting in real time.', t:'Hệ thống của chúng tôi dịch âm thanh trực tiếp từ mọi cuộc họp theo thời gian thực.' },
    { sp:1, s:'It captures the speaker, transcribes, translates, and speaks back instantly.', guess:'It capture the speaker, transcribe, translates, and speaks back instantly.', t:'Nó thu giọng người nói, chuyển thành văn bản, dịch và đọc lại ngay lập tức.' },
    { sp:1, s:'Everything runs locally, so your conversations never leave the device.', guess:'Everything run locally, so your conversation never leave the device.', t:'Mọi thứ chạy cục bộ, nên cuộc trò chuyện của bạn không bao giờ rời khỏi thiết bị.' },
    { sp:0, s:'Let me show you how smooth the streaming experience feels.', guess:'Let me show you how smooth the streaming experience feel.', t:'Hãy để tôi cho bạn thấy trải nghiệm streaming mượt mà đến thế nào.' },
  ],
};
window.getScript = (src,tgt)=> SCRIPTS[src+'-'+tgt] || SCRIPTS['vi-en'];
